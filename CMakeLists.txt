cmake_minimum_required(VERSION 3.20)
project(FFTARecomp C CXX)

# clang-tidy reads this (gbarecompx/tools/check_clang_tidy.sh); harmless to
# always write.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ── Framework root ───────────────────────────────────────────────────────────
# The gbarecomp submodule IS the framework: james2doyle/gbarecompx (the fork
# carrying the launch screen, tinyfiledialogs picker, emibios default and the
# former local-patch work as committed history). No in-tree preference branch,
# no working-tree patches.
set(GBARECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/gbarecompx"
    CACHE PATH "Path to this game's gbarecomp framework checkout")
if(NOT EXISTS "${GBARECOMP_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR
        "GBARECOMP_ROOT is not a gbarecomp checkout: ${GBARECOMP_ROOT}")
endif()

# FFTA always builds the mod runtime: the widescreen feature installs through
# the trusted-plugin lifecycle (src/main.cpp), and the Android shell's Gradle
# build passes no mods flag of its own. Mirrors the reference repos.
set(GBARECOMP_ENABLE_MODS ON CACHE BOOL
    "Build the GBA mod package loader and trusted-plugin runtime" FORCE)

# recomp-ui is removed (Phase 5): the runtime launcher overlay lives in
# gbarecomp_runtime via its own renderer-agnostic sources elsewhere; keep the
# root explicitly empty so the framework's GBARECOMP_RUNTIME_UI EXISTS guard
# self-fails rather than pointing at a now-deleted checkout.
set(GBARECOMP_RUNTIME_UI_ROOT ""
    CACHE PATH "recomp-ui root (removed in Phase 5; left empty on purpose)")

# ── Window backend (Phase 4c) ────────────────────────────────────────────────
# raylib is the product backend. Declared here so a plain
# `cmake -S . -B build` selects it; -DGBARECOMP_USE_RAYLIB=OFF builds the
# stub compile-check instead. option() never overwrites an existing cache
# entry, so the framework's own OFF default still applies to standalone
# framework builds.
option(GBARECOMP_USE_RAYLIB
    "Build the raylib window backend (the product; OFF = stub compile-check)" ON)

# The pinned cross prefix (tools/win_cross_deps.py) provides raylib for the
# Windows release. Prefer it: no FetchContent, no network, deterministic.
# The framework's raylib block only fetches when no `raylib` target exists.
if(MINGW)
    find_package(raylib CONFIG QUIET)
    if(TARGET raylib)
        message(STATUS "ffta: raylib from the cross prefix (${raylib_DIR})")
    else()
        message(STATUS "ffta: raylib not in the cross prefix -- the framework "
                       "will fetch it (tools/win_cross_deps.py build pins it)")
    endif()
endif()

add_subdirectory("${GBARECOMP_ROOT}" gbarecomp_build EXCLUDE_FROM_ALL)

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/generated/recompiled.cpp")
    message(FATAL_ERROR
        "Stale monolithic generated/recompiled.cpp found. Re-run gba_recompile.")
endif()
file(GLOB GAME_GENERATED_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/generated/*.c"
    "${CMAKE_CURRENT_SOURCE_DIR}/generated/*.cpp")

# Android: SDLActivity loads libmain.so, so the game target must be a SHARED
# library named `main`; desktop keeps the FFTARecomp executable name.
# Both carry the FFTA-owned host code (launch wiring + speed pill).
set(FFTA_HOST_SOURCES
    src/main.cpp
    src/ffta_speed_boost.cpp)
if(ANDROID)
    add_library(main SHARED
        ${FFTA_HOST_SOURCES}
        ${GAME_GENERATED_SOURCES})
    set(FFTA_TARGET main)
    # Bind internal calls locally: without this every cross-TU call inside
    # the 138MB .so goes through the PLT (measured 3.8% + BTB/I-cache
    # pressure on device, 2026-10-14 simpleperf). Entry points
    # (android_main/JNI) stay exported and loadable; only intra-lib
    # references bind locally. Audio/guest state untouched.
    target_link_options(main PRIVATE "LINKER:-Bsymbolic-functions")
    # Raylib (NativeActivity) entry: android_main lives in OUR .so —
    # NativeActivity loads it per the manifest's android.app.lib_name.
    # The backend define does not propagate through the runtime's PRIVATE
    # link, so the entry-point selection in src/main.cpp gets it explicitly.
    if(GBARECOMP_RAYLIB_ENABLED)
        # Vendored glue (platform/android/native_app_glue) sizes the app
        # thread for the corpus; the NDK copy is the fallback when absent.
        set(GBARECOMP_GLUE_DIR "${GBARECOMP_ROOT}/platform/android/native_app_glue")
        if(NOT EXISTS "${GBARECOMP_GLUE_DIR}/android_native_app_glue.c")
            message(WARNING "ffta: vendored glue absent; NDK glue fallback (1 MiB stack)")
            set(GBARECOMP_GLUE_DIR "${ANDROID_NDK}/sources/android/native_app_glue")
        endif()
        target_sources(main PRIVATE
            ${GBARECOMP_GLUE_DIR}/android_native_app_glue.c)
        target_include_directories(main PRIVATE
            ${GBARECOMP_GLUE_DIR})
        target_compile_definitions(main PRIVATE GBARECOMP_USE_RAYLIB=1)
        # raylib's own system deps are PRIVATE to its static archive, so the
        # final shared link names them (same set as the backend spike).
        target_link_libraries(main PRIVATE log android EGL GLESv2 OpenSLES m z)
    endif()
else()
    add_executable(FFTARecomp
        ${FFTA_HOST_SOURCES}
        ${GAME_GENERATED_SOURCES})
    set(FFTA_TARGET FFTARecomp)
endif()

set(GAME_RECOMPILED_SOURCES ${GAME_GENERATED_SOURCES})
list(FILTER GAME_RECOMPILED_SOURCES INCLUDE REGEX
    "/recompiled_[0-9]+\\.cpp$")
if(GAME_RECOMPILED_SOURCES)
    set_source_files_properties(${GAME_RECOMPILED_SOURCES} PROPERTIES
        COMPILE_OPTIONS "-O1;-g0")
endif()

target_include_directories(${FFTA_TARGET} PRIVATE
    "${GBARECOMP_ROOT}/src/armv4t"
    "${GBARECOMP_ROOT}/src/gba"
    "${GBARECOMP_ROOT}/src/runtime"
    "${GBARECOMP_ROOT}/src/debug"
    src)

target_link_libraries(${FFTA_TARGET} PRIVATE
    "-Wl,--start-group"
    gbarecomp_runtime
    gbarecomp_debug
    gbarecomp_gba
    gbarecomp_armv4t
    "-Wl,--end-group")

# Phase 4f: the Android base is the raylib/NativeActivity scaffold; the
# user-visible save/state dir comes from the baked applicationId in
# src/main.cpp (no SDL link).

if(ANDROID)
    set(FFTA_DEFAULT_GAME_CONFIG "variants/final_fantasy_tactics_advance/game.toml")
else()
    set(FFTA_DEFAULT_GAME_CONFIG "game.toml")
endif()
if(GBAGAME_BUNDLED_ROM)
    target_compile_definitions(${FFTA_TARGET} PRIVATE GBAGAME_BUNDLED_ROM=1)
endif()
target_compile_definitions(${FFTA_TARGET} PRIVATE
    GBARECOMP_DEFAULT_DEBUG_PORT=19888
    GBARECOMP_WINDOW_TITLE="FFTARecomp"
    GBARECOMP_DEFAULT_GAME_CONFIG="${FFTA_DEFAULT_GAME_CONFIG}")

option(GBAGAME_BUNDLED_ROM "Private build: ROM is staged/bundled, setup UI may be skipped" OFF)

if(ANDROID)
    # The game runs on mobile_run_with_stack()'s 256 MiB pthread; the SDL
    # Java thread never hosts guest code, so no link-time stack is needed.
elseif(MSVC)
    target_link_options(${FFTA_TARGET} PRIVATE /STACK:16777216)
elseif(MINGW)
    target_link_options(${FFTA_TARGET} PRIVATE -Wl,--stack,16777216)
else()
    # Linux: default main-thread stack (typically 8 MB) is ample; the
    # recompiled-guest bodies are flat C calls, not deep recursion.
    target_link_options(${FFTA_TARGET} PRIVATE -Wl,-z,noexecstack)
endif()

# Ship the game-owned, default-enabled mod catalog beside the executable
# (mirrors the reference repos; the widescreen plugin is a trusted built-in
# referenced by the manifest but resolved from the linked registrations).
set(FFTA_PRELOADED_MODS "${CMAKE_CURRENT_SOURCE_DIR}/mods/preloaded")
if(NOT ANDROID AND EXISTS "${FFTA_PRELOADED_MODS}/packages")
    add_custom_command(TARGET ${FFTA_TARGET} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${FFTA_PRELOADED_MODS}"
            "$<TARGET_FILE_DIR:${FFTA_TARGET}>/mods"
        COMMENT "Preloading the FFTA mod catalog")
endif()

# Ship the launcher box art beside the executable (raygui launcher loads
# assets/img/boxart.png next to the exe via GetApplicationDirectory()).
# Tracked as a build input: changing the PNG re-runs staging, even if the
# game binary is otherwise up to date.
set(FFTA_BOXART_SRC "${CMAKE_CURRENT_SOURCE_DIR}/recomp/launcher/boxart.png")
if (NOT ANDROID)
    add_custom_target(stage_boxart ALL
        COMMAND ${CMAKE_COMMAND} -E make_directory
            "$<TARGET_FILE_DIR:${FFTA_TARGET}>/assets/img"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "${FFTA_BOXART_SRC}"
            "$<TARGET_FILE_DIR:${FFTA_TARGET}>/assets/img/boxart.png"
        DEPENDS "${FFTA_BOXART_SRC}"
        COMMENT "Staging launcher box art")
    add_dependencies(${FFTA_TARGET} stage_boxart)
endif()

# ── host unit tests for src/ custom code ────────────────────────────
# GAME-OWNED ONLY (2026-10-17 ownership split): everything here tests src/
# headers. The framework's tests (host-stack guard, frame pacer, backend
# selection, HostWindow closed/delegation, the raylib present pipeline)
# moved to gbarecompx/tests/runtime/ — the fork's CI owns them now, and its
# standalone build no longer has the "cannot compile host_window.cpp"
# blocker that originally kept them here.
option(FFTA_BUILD_TESTS "Build host unit tests for src/ custom code" ON)
if(FFTA_BUILD_TESTS AND NOT ANDROID)
    enable_testing()
    add_executable(ffta_unit_tests
        tests/unit/test_ram_dispatch.cpp
        tests/unit/test_speed_boost.cpp
        tests/unit/test_haptics.cpp)
    target_include_directories(ffta_unit_tests PRIVATE
        "${GBARECOMP_ROOT}/src/armv4t"
        "${GBARECOMP_ROOT}/src/runtime"
        "${GBARECOMP_ROOT}/src/gba"
        src)
    find_package(Threads REQUIRED)
    target_link_libraries(ffta_unit_tests PRIVATE
        gbarecomp_runtime  # haptics host_primary_haptic (no-backend stub here)
        Threads::Threads)
    if(WIN32 AND NOT MSVC)
        target_link_libraries(ffta_unit_tests PRIVATE winmm)
    endif()
    # Assertions stay live in tests: Release's -DNDEBUG silently erases
    # assert() (the vacuous-assert trap; same treatment as the framework's
    # test targets in gbarecompx/CMakeLists.txt).
    target_compile_options(ffta_unit_tests PRIVATE -UNDEBUG)
    add_test(NAME ram_dispatch COMMAND ffta_unit_tests)

    # Widescreen margin policy decision logic (src/ffta_ws_margin.h): the
    # size-0 layer mask + the -1/0 span contract, pinned to the captured
    # register blocks (device conversations x4, desktop pub replay, the
    # battle move state). Red-first via the A/B fixture replay (BRINGUP).
    add_executable(ffta_ws_margin_tests tests/unit/test_ws_margin.cpp)
    target_include_directories(ffta_ws_margin_tests PRIVATE src)
    target_compile_options(ffta_ws_margin_tests PRIVATE -UNDEBUG)
    add_test(NAME ws_margin COMMAND ffta_ws_margin_tests)

    # The HostWindow closed/delegation contracts, the backend-selection
    # predicate, the host-stack guard, the frame pacer and the raylib
    # present pipeline all moved to gbarecompx/tests/runtime/ (2026-10-17
    # ownership split) — the fork's CI runs them; this tree no longer
    # compiles framework sources into test targets.

endif()
