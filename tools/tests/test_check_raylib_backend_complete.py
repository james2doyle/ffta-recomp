#!/usr/bin/env python3
"""Self-tests for tools/check_raylib_backend_complete.py.

The completeness guard is load-bearing: if it silently passes, the seam
silently drifts from its contract. So it gets tested like any other code --
including the cases that once broke it (the function-pointer argument, the
overload pair), the Phase 4b checks (pure interfaces, single generation), and
the Phase 4d per-interface attribution cases: a method implemented in the
WRONG impl class, a cross-interface signature collision, and a facade method
implemented in an impl class. The old union scan accepted all three. It also
covers the 2026-10-21 test-double scan: the abstract `NoopInput` regression,
plus the function-pointer and namespace normalizations a double needs.

Run: python3 tools/tests/test_check_raylib_backend_complete.py
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_raylib_backend_complete as checker  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        FAILURES.append(f"{label}: got {got!r}, want {want!r}")


# One slot per interface in the seam header, and one per implementation site
# (the facade in raylib_backend.h, the five concerns in their nested impls).
IFACE_HEADER = """#pragma once
namespace gbarecomp {
struct HostOverlay;
class WindowBackend {
public:
    virtual ~WindowBackend() = default;
%s
};
class Video {
public:
    virtual ~Video() = default;
%s
};
class Audio {
public:
    virtual ~Audio() = default;
%s
};
class Input {
public:
    virtual ~Input() = default;
%s
};
class Fx {
public:
    virtual ~Fx() = default;
%s
};
class Overlay {
public:
    virtual ~Overlay() = default;
%s
};
class Menu {
public:
    virtual ~Menu() = default;
%s
};
}  // namespace gbarecomp
"""

BACKEND_HEADER = """#pragma once
#include "window_backend.h"
namespace gbarecomp {
class RaylibBackend final : public WindowBackend {
public:
%s
};
}  // namespace gbarecomp
"""

BACKEND_CPP = """#include "raylib_backend.h"
namespace gbarecomp {
class RaylibBackend::VideoImpl final : public Video {
public:
%s
};
class RaylibBackend::AudioImpl final : public Audio {
public:
%s
};
class RaylibBackend::InputImpl final : public Input {
public:
%s
};
class RaylibBackend::FxImpl final : public Fx {
public:
%s
};
class RaylibBackend::OverlayImpl final : public Overlay {
public:
%s
};
class RaylibBackend::MenuImpl final : public Menu {
public:
%s
};
}  // namespace gbarecomp
"""

CLEAN_HOST = "// host_window.cpp fixture: no SDL markers\n"
CLEAN_FACTORY = "// factory fixture: no SDL markers\n"


def run(tmp: Path, facade_iface: str = "", video_iface: str = "",
        audio_iface: str = "", input_iface: str = "", fx_iface: str = "",
        overlay_iface: str = "", menu_iface: str = "", facade_impl: str = "",
        video_impl: str = "", audio_impl: str = "", input_impl: str = "",
        fx_impl: str = "", overlay_impl: str = "", menu_impl: str = "",
        host_window: str = CLEAN_HOST, factory: str = CLEAN_FACTORY,
        doubles: str = "") -> int:
    paths = {
        "iface": tmp / "window_backend.h",
        "backend_h": tmp / "raylib_backend.h",
        "backend_cpp": tmp / "raylib_backend.cpp",
        "host_window": tmp / "host_window.cpp",
        "factory": tmp / "host_backend_factory.cpp",
    }
    paths["iface"].write_text(IFACE_HEADER % (
        facade_iface, video_iface, audio_iface, input_iface, fx_iface,
        overlay_iface, menu_iface))
    paths["backend_h"].write_text(BACKEND_HEADER % facade_impl)
    paths["backend_cpp"].write_text(BACKEND_CPP % (
        video_impl, audio_impl, input_impl, fx_impl, overlay_impl, menu_impl))
    paths["host_window"].write_text(host_window)
    paths["factory"].write_text(factory)
    tests = tmp / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "doubles.cpp").write_text(doubles)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return checker.main([
            "--iface", str(paths["iface"]),
            "--backend-h", str(paths["backend_h"]),
            "--backend-cpp", str(paths["backend_cpp"]),
            "--host-window", str(paths["host_window"]),
            "--factory", str(paths["factory"]),
            "--tests", str(tests),
        ])


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 1. Baseline: pure interfaces, every method overridden at its own
        #    site (facade in the header class, concerns in their impls).
        check("complete backend passes",
              run(tmp,
                  facade_iface="    virtual void set_volume(int pct) = 0;\n"
                               "    virtual int volume_percent() const = 0;\n",
                  facade_impl="    void set_volume(int pct) override;\n"
                              "    int volume_percent() const override;\n",
                  video_iface="    virtual void present(const std::uint8_t* p, bool fresh) = 0;\n",
                  video_impl="    void present(const std::uint8_t* p, bool fresh) override;\n"),
              0)

        # 2. A missing override must be reported, not silently accepted.
        check("missing override fails",
              run(tmp,
                  facade_iface="    virtual void set_volume(int pct) = 0;\n"
                               "    virtual void set_fps_readout(bool on) = 0;\n",
                  facade_impl="    void set_volume(int pct) override;\n"),
              1)

        # 3. REGRESSION: a function-pointer parameter contains its own parens.
        check("function-pointer arg parses (regression)",
              run(tmp,
                  overlay_iface="    virtual void set_host_overlay(void (*overlay)(HostOverlay*)) = 0;\n",
                  overlay_impl="    void set_host_overlay(void (*overlay)(HostOverlay*)) override;\n"),
              0)

        # 4. REGRESSION: overloaded interface methods are distinct entries.
        check("overloads tracked separately",
              run(tmp,
                  facade_iface="    virtual bool open(int scale) = 0;\n"
                               "    virtual bool open(long scale) = 0;\n",
                  facade_impl="    bool open(int scale) override;\n"
                              "    bool open(long scale) override;\n"),
              0)

        # 5. REGRESSION: one open() override must not satisfy the other.
        check("overload mismatch fails",
              run(tmp,
                  facade_iface="    virtual bool open(int scale) = 0;\n"
                               "    virtual bool open(long scale) = 0;\n",
                  facade_impl="    bool open(int scale) override;\n"),
              1)

        # 6. const-ness drift must be caught.
        check("const-ness mismatch fails",
              run(tmp,
                  facade_iface="    virtual int value() const = 0;\n",
                  facade_impl="    int value() override;\n"),
              1)

        # 7. Whitespace normalization must not create false mismatches.
        check("spacing tolerated",
              run(tmp,
                  video_iface="    virtual bool drawable_size(int* w, int* h) const = 0;\n",
                  video_impl="    bool drawable_size(int *w, int *h) const override;\n"),
              0)

        # 8. A non-virtual member in the interface must not be required.
        check("non-virtual ignored",
              run(tmp,
                  facade_iface="    int helper_field = 0;\n"
                               "    virtual void set_volume(int pct) = 0;\n",
                  facade_impl="    void set_volume(int pct) override;\n"),
              0)

        # 9. REGRESSION (Phase 4b): an interface method with a defaulted body is
        #    the silent-inheritance bug class (audio_enabled_state()).
        check("impure interface method fails",
              run(tmp,
                  audio_iface="    virtual bool audio_enabled() const { return false; }\n"),
              1)

        # 10. Phase 4b: the flat generation must be gone.
        check("flat marker fails",
              run(tmp,
                  facade_iface="    virtual bool open(const WindowBackendOpenParams& p) = 0;\n",
                  facade_impl="    bool open(const WindowBackendOpenParams& p) override;\n"),
              1)

        # 11. Phase 4b: the SDL factory hook must be gone.
        check("sdl factory marker fails",
              run(tmp,
                  facade_iface="    virtual void close() = 0;\n",
                  facade_impl="    void close() override;\n",
                  host_window="WindowBackend* host_make_sdl_backend() { return nullptr; }\n"),
              1)

        # 12. Phase 4b: the SDL compile define must be gone from the runtime.
        check("sdl define marker fails",
              run(tmp,
                  facade_iface="    virtual void close() = 0;\n",
                  facade_impl="    void close() override;\n",
                  host_window="#if defined(GBARECOMP_HAVE_SDL2)\n#endif\n"),
              1)

        # 13. Phase 4b: an inline SDL `Backend` struct must be gone.
        check("sdl backend struct fails",
              run(tmp,
                  facade_iface="    virtual void close() = 0;\n",
                  facade_impl="    void close() override;\n",
                  host_window="struct Backend : public WindowBackend {};\n"),
              1)

        # 14. Phase 4b: concern interfaces are scanned too (not just the facade).
        check("concern interface missing override fails",
              run(tmp,
                  facade_iface="    virtual void close() = 0;\n",
                  facade_impl="    void close() override;\n",
                  video_iface="    virtual void present(const std::uint8_t* p) = 0;\n"),
              1)

        # 15. A concern implemented in its own nested impl passes.
        check("concern implemented in cpp passes",
              run(tmp,
                  facade_iface="    virtual void close() = 0;\n",
                  facade_impl="    void close() override;\n",
                  video_iface="    virtual void present(const std::uint8_t* p) = 0;\n",
                  video_impl="    void present(const std::uint8_t* p) override;\n"),
              0)

        # 16. Phase 4d: WRONG-CLASS attribution must fail. `present` is a Video
        #     method; implementing it in AudioImpl satisfies the old union scan
        #     but not the per-interface one.
        check("wrong-class attribution fails",
              run(tmp,
                  video_iface="    virtual void present(const std::uint8_t* p) = 0;\n",
                  audio_impl="    void present(const std::uint8_t* p) override;\n"),
              1)

        # 17. Phase 4d: a cross-interface signature collision must fail when
        #     only one of the two impls implements it.
        check("cross-interface collision fails",
              run(tmp,
                  video_iface="    virtual void set_config_dir(const char* dir) = 0;\n",
                  video_impl="    void set_config_dir(const char* dir) override;\n",
                  audio_iface="    virtual void set_config_dir(const char* dir) = 0;\n"),
              1)

        # 18. Phase 4d: a facade method implemented in an impl class (instead of
        #     the RaylibBackend class body) must fail.
        check("facade method in wrong site fails",
              run(tmp,
                  facade_iface="    virtual void close() = 0;\n",
                  video_impl="    void close() override;\n"),
              1)

        # 19. A test double implementing the full interface passes (qualified
        #     and final base forms both parse).
        check("complete test double passes",
              run(tmp,
                  input_iface="    virtual void read(int& out) = 0;\n",
                  input_impl="    void read(int& out) override;\n",
                  doubles="struct FullInput final : public gbarecomp::Input {\n"
                          "    void read(int& out) override {}\n"
                          "};\n"),
              0)

        # 20. REGRESSION (2026-10-21): an abstract test double once compiled
        #     only in the framework's own test target, so the consumer pin bump
        #     stayed green while NoopInput lacked controller_is_primary().
        check("abstract test double fails",
              run(tmp,
                  input_iface="    virtual void read(int& out) = 0;\n",
                  input_impl="    void read(int& out) override;\n",
                  doubles="struct NoopInput final : Input {\n};\n"),
              1)

        # 21. Const-ness drift in a double must fail like it does in the
        #     product backend.
        check("test double const drift fails",
              run(tmp,
                  input_iface="    virtual int value() const = 0;\n",
                  input_impl="    int value() const override;\n",
                  doubles="struct BadInput final : Input {\n"
                          "    int value() override { return 0; }\n"
                          "};\n"),
              1)

        # 22. REGRESSION: doubles often omit the function-pointer parameter
        #     name (`void (*)(HostOverlay*)` vs `void (*overlay)(...)`); it is
        #     not part of the signature.
        check("unnamed function-pointer arg in double passes",
              run(tmp,
                  overlay_iface="    virtual void set_host_overlay(void (*overlay)(HostOverlay*)) = 0;\n",
                  overlay_impl="    void set_host_overlay(void (*overlay)(HostOverlay*)) override;\n",
                  doubles="struct NoopOverlay final : Overlay {\n"
                          "    void set_host_overlay(void (*)(HostOverlay*)) override {}\n"
                          "};\n"),
              0)

        # 23. REGRESSION: a double in the seam namespace may write
        #     `gbarecomp::OpenParams`; the namespace is not part of the type
        #     identity here.
        check("namespace-qualified type in double passes",
              run(tmp,
                  facade_iface="    virtual bool open(const OpenParams& p) = 0;\n",
                  facade_impl="    bool open(const OpenParams& p) override;\n",
                  doubles="struct SpyBackend final : WindowBackend {\n"
                          "    bool open(const gbarecomp::OpenParams& p) override { return true; }\n"
                          "};\n"),
              0)

    if FAILURES:
        print("check_raylib_backend_complete SELF-TESTS FAILED:")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("check_raylib_backend_complete self-tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
