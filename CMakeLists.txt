cmake_minimum_required(VERSION 3.20)
project(FFTARecomp C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(GBARECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/gbarecomp"
    CACHE PATH "Path to this game's gbarecomp worktree")
if(NOT EXISTS "${GBARECOMP_ROOT}/CMakeLists.txt")
    message(FATAL_ERROR
        "GBARECOMP_ROOT is not a gbarecomp checkout: ${GBARECOMP_ROOT}")
endif()

set(RECOMP_UI_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/recomp-ui"
    CACHE PATH "Path to the shared recomp-ui checkout")

# FFTA always builds the mod runtime: the widescreen feature installs through
# the trusted-plugin lifecycle (src/main.cpp), and the Android shell's Gradle
# build passes no mods flag of its own. Mirrors the reference repos.
set(GBARECOMP_ENABLE_MODS ON CACHE BOOL
    "Build the GBA mod package loader and trusted-plugin runtime" FORCE)
set(GBARECOMP_RUNTIME_UI_ROOT "${RECOMP_UI_ROOT}"
    CACHE PATH "recomp-ui root used by the live GBA runtime adapter")

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
if(ANDROID)
    add_library(main SHARED
        src/main.cpp
        ${GAME_GENERATED_SOURCES})
    set(FFTA_TARGET main)
else()
    add_executable(FFTARecomp
        src/main.cpp
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

if(ANDROID)
    set(FFTA_DEFAULT_GAME_CONFIG "variants/final_fantasy_tactics_advance/game.toml")
else()
    set(FFTA_DEFAULT_GAME_CONFIG "game.toml")
endif()
target_compile_definitions(${FFTA_TARGET} PRIVATE
    GBARECOMP_DEFAULT_DEBUG_PORT=19888
    GBARECOMP_WINDOW_TITLE="FFTARecomp"
    GBARECOMP_DEFAULT_GAME_CONFIG="${FFTA_DEFAULT_GAME_CONFIG}")

option(GBAGAME_RECOMP_UI "Build the recomp-ui pre-boot launcher" ON)
if(GBAGAME_RECOMP_UI)
    include(${RECOMP_UI_ROOT}/recomp_ui.cmake)
    add_library(game_launcher_ui STATIC src/game_launcher_boot.cpp)
    target_include_directories(game_launcher_ui PRIVATE
        "${GBARECOMP_ROOT}/src/runtime"
        "${GBARECOMP_ROOT}/src/gba"
        src)
    recomp_target_launcher_ui(game_launcher_ui
        CONSOLE gba
        BOXART ${CMAKE_CURRENT_SOURCE_DIR}/recomp/launcher/boxart.tga)
    # Android builds provide SDL2 from the shared shell's SDL subproject.
    if(NOT TARGET SDL2::SDL2)
        find_package(SDL2 REQUIRED)
    endif()
    target_link_libraries(game_launcher_ui PUBLIC SDL2::SDL2)
    if(WIN32)
        target_link_libraries(game_launcher_ui PUBLIC opengl32)
    endif()
    target_link_libraries(${FFTA_TARGET} PRIVATE game_launcher_ui)
    set_property(SOURCE src/main.cpp APPEND PROPERTY
        COMPILE_DEFINITIONS GBAGAME_RECOMP_UI)
endif()

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

# ── host unit tests for src/ custom code ────────────────────────────
option(FFTA_BUILD_TESTS "Build host unit tests for src/ custom code" ON)
if(FFTA_BUILD_TESTS AND NOT ANDROID)
    enable_testing()
    # The host-stack-guard test targets the guard APIs from the
    # host-stack-guard-desktop.patch work (applied on the pinned gbarecomp
    # submodule locally, absent on a pristine checkout — CI). Probe the
    # pinned header and compile the test only where the APIs exist.
    include(CheckSymbolExists)
    set(HSG_HEADER "${GBARECOMP_ROOT}/src/runtime/mobile_platform.h")
    file(READ "${HSG_HEADER}" _hsg_header_text)
    if(_hsg_header_text MATCHES "host_stack_guard_arm_current")
        set(HOST_STACK_GUARD_API ON)
        message(STATUS "host-stack-guard APIs present: testing")
    else()
        set(HOST_STACK_GUARD_API OFF)
        message(STATUS "host-stack-guard APIs absent (pristine submodule): "
                       "guard test compiles to a skip")
    endif()
    add_executable(ffta_unit_tests
        tests/unit/test_ram_dispatch.cpp
        tests/unit/test_host_stack_guard.cpp
        "${GBARECOMP_ROOT}/src/runtime/mobile_platform.cpp")
    target_include_directories(ffta_unit_tests PRIVATE
        "${GBARECOMP_ROOT}/src/armv4t"
        "${GBARECOMP_ROOT}/src/runtime"
        src)
    find_package(Threads REQUIRED)
    target_link_libraries(ffta_unit_tests PRIVATE Threads::Threads)
    if(HOST_STACK_GUARD_API)
        target_compile_definitions(ffta_unit_tests PRIVATE HOST_STACK_GUARD_API=1)
    endif()
    add_test(NAME ram_dispatch COMMAND ffta_unit_tests)
endif()
