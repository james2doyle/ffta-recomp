#!/usr/bin/env python3
"""Completeness guard for the single-generation window seam (Phase 4b).

Four checks, all against the sources:

  1. single generation — the flat generation and the SDL backend are gone:
     no `WindowBackendOpenParams` in the seam, no `host_make_sdl_backend` in
     the runtime, no `GBARECOMP_HAVE_SDL2` in host_window.cpp /
     host_backend_factory.cpp, and no inline `Backend` struct in
     host_window.cpp. (SDL *scancode* vocabulary in the input/config layer is
     data, not the backend — out of scope.)
  2. pure interfaces — every virtual in every seam interface (the facade
     `WindowBackend` plus `Video`/`Audio`/`Input`/`Fx`/`Overlay`/`Menu`) is
     pure (`= 0`). A defaulted body is the silent-inheritance bug class this
     guard exists for: the SDL backend's `audio_enabled_state()` once stopped
     overriding the interface method, so the base default answered while
     audio was actually playing.
  3. complete backend, per interface — every method of every interface has a
     matching `override` at ITS OWN implementation site (the facade in the
     RaylibBackend class body, each concern in its nested impl class). The
     scan is scoped per site: a method implemented in the wrong impl class, or
     a cross-interface signature collision satisfied by only one impl, is a
     FAILURE here (a union scan over both files accepts both — the Phase 4d
     rewrite is what closed that).
  4. complete test doubles — every class in the framework test tree that
     derives directly from a seam interface overrides the full contract too.
     Compilation is the strict check, but those doubles are only built by the
     framework's own test targets; the consumer's pin-bump gate never compiled
     them, so `NoopInput` stayed abstract through a green parent run
     (2026-10-21). This source scan puts that drift in the parent's default
     gate, where a pin bump sees it.

Why the parsing is fussy: `override` catches signature drift, but not a
method that silently stops overriding (see check 2), and a naive
`\\([^)]*\\)` regex drops `set_host_overlay(void (*overlay)(HostOverlay*))`
because the function-pointer argument contains its own parentheses.

Usage:  python3 tools/check_raylib_backend_complete.py [--tests DIR]
Exit 0 when all four hold, 1 otherwise.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IFACE = ROOT / "gbarecompx/src/runtime/window_backend.h"
DEFAULT_BACKEND_H = ROOT / "gbarecompx/src/runtime/raylib_backend.h"
DEFAULT_BACKEND_CPP = ROOT / "gbarecompx/src/runtime/raylib_backend.cpp"
DEFAULT_HOST_WINDOW = ROOT / "gbarecompx/src/runtime/host_window.cpp"
DEFAULT_FACTORY = ROOT / "gbarecompx/src/runtime/host_backend_factory.cpp"
DEFAULT_TESTS = ROOT / "gbarecompx/tests/runtime"

# The seam interfaces whose methods must all be pure and implemented.
INTERFACE_NAMES = ["WindowBackend", "Video", "Audio", "Input", "Fx",
                   "Overlay", "Menu"]

# Where each interface's implementation must live (Phase 4d: attribution is
# per site, not a union over the backend sources).
IMPL_SITES = {
    "WindowBackend": ("h", "RaylibBackend"),
    "Video":         ("cpp", "RaylibBackend::VideoImpl"),
    "Audio":         ("cpp", "RaylibBackend::AudioImpl"),
    "Input":         ("cpp", "RaylibBackend::InputImpl"),
    "Fx":            ("cpp", "RaylibBackend::FxImpl"),
    "Overlay":       ("cpp", "RaylibBackend::OverlayImpl"),
    "Menu":          ("cpp", "RaylibBackend::MenuImpl"),
}

TYPE_WORDS = {
    "void", "bool", "char", "short", "int", "long", "float", "double",
    "signed", "unsigned", "const", "volatile", "size_t", "auto",
}


def _strip_param_name(param: str) -> str:
    """Drop a trailing parameter NAME, which is not part of the signature.

    `float low` and `float low_frequency` are the same parameter type. Also
    drops leading `::` global-scope qualifiers, and the name inside a
    function-pointer parameter (`void (*overlay)(HostOverlay*)` ==
    `void (*)(HostOverlay*)` — test doubles often omit it).
    """
    param = param.strip()
    param = re.sub(r"^::", "", param)
    param = re.sub(r"\(\s*\*\s*[A-Za-z_]\w*\s*\)", "(*)", param)
    m = re.match(r"^(.*?)([A-Za-z_]\w*)$", param, re.DOTALL)
    if not m:
        return param
    prefix, last = m.group(1), m.group(2)
    if not prefix.strip():
        return param
    if last in TYPE_WORDS:
        return param                      # e.g. "unsigned long"
    if prefix.rstrip().endswith(("*", "&", "&&")):
        return prefix.rstrip()             # e.g. "const char* title"
    # `int base_w` / `float low`: the token before the name is the type itself.
    prev = prefix.rstrip().split()[-1] if prefix.strip() else ""
    if prev in {"int", "char", "short", "long", "float", "double", "bool",
                "void", "signed", "unsigned", "size_t"} or re.match(
                    r"^[A-Za-z_]\w*_t$", prev
                ):
        return prefix.rstrip()
    return param


def norm(text: str) -> str:
    """Canonicalize an argument list for signature comparison.

    Normalizes, in order: pointer/reference spacing (`int* w` == `int *w`), the
    `std::` and `gbarecomp::` qualifiers (`gbarecomp::OpenParams` ==
    `OpenParams`, as test doubles in the seam's own namespace write it), and
    parameter NAMES (not part of a C++ signature).
    """
    text = re.sub(r"\s*([*&])\s*", r"\1", text)
    text = text.replace("std::", "").replace("gbarecomp::", "")
    parts, depth, cur = [], 0, ""
    for ch in text:                        # split on top-level commas only
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    return ",".join(_strip_param_name(p) for p in parts)


def balanced_args(text: str, open_paren: int) -> tuple[str, int] | None:
    """Return (normalized args, index just past the matching ')')."""
    depth = 0
    i = open_paren
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return norm(text[open_paren + 1:i]), i + 1
        i += 1
    return None


def struct_body(text: str, struct_name: str) -> str:
    """Return the text inside `class|struct <name> { ... }`, brace-balanced."""
    m = re.search(rf"\b(?:class|struct)\s+{re.escape(struct_name)}\b[^{{]*\{{",
                  text)
    if not m:
        return ""
    i = m.end() - 1
    depth = 0
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[m.end():i]
        i += 1
    return ""


def interface_methods(body: str) -> dict[tuple[str, str], tuple[bool, bool]]:
    """Map (name, args) -> (is_const, is_pure) for every virtual member.

    Destructors are skipped (they are never pure and never `override`n in the
    backend sources as regular methods).
    """
    out: dict[tuple[str, str], tuple[bool, bool]] = {}
    for m in re.finditer(r"\bvirtual\b[^;{]*?(\w+)\s*\(", body):
        # Destructors are never pure and never `override`n as regular methods.
        # (The `~` cannot be captured in the group: the lazy prefix skips it.)
        if body[m.start(1) - 1:m.start(1)] == "~":
            continue
        name = m.group(1)
        got = balanced_args(body, m.end() - 1)
        if got is None:
            continue
        args, after = got
        semi = body.find(";", after)
        if semi < 0:
            continue
        decl = body[after:semi]
        out.setdefault((name, args),
                       (bool(re.match(r"\s*const\b", decl)),
                        bool(re.search(r"=\s*0\s*$", decl.rstrip()))))
    return out


def override_methods(text: str) -> dict[tuple[str, str], bool]:
    """Map (name, args) -> is_const for every declared override."""
    out: dict[tuple[str, str], bool] = {}
    for m in re.finditer(r"\b(\w+)\s*\(", text):
        got = balanced_args(text, m.end() - 1)
        if got is None:
            continue
        args, after = got
        rest = text[after:after + 40]
        if "override" not in rest.split(";")[0]:
            continue
        out.setdefault((m.group(1), args), bool(re.match(r"\s*const\b", rest)))
    return out


def double_declarations(text: str) -> list[tuple[str, str, str]]:
    """(class, base, body) for every direct seam-interface test double.

    Matches the FIRST base after the colon: every double in the tree derives
    from one concern, and a multi-base double should get a conscious review
    anyway. Both `struct X : Input {` and
    `class X final : public gbarecomp::Input {` parse.
    """
    out: list[tuple[str, str, str]] = []
    for m in re.finditer(
            r"\b(?:class|struct)\s+([A-Za-z_]\w*)\s*(?:final\s*)?:\s*"
            r"(?:(?:public|protected|private)\s+)?"
            r"(?:::)?(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)", text):
        cls, base = m.group(1), m.group(2)
        if base not in INTERFACE_NAMES:
            continue
        body = struct_body(text, cls)
        if body:
            out.append((cls, base, body))
    return out


TEST_SOURCE_SUFFIXES = {".cpp", ".h", ".hpp", ".cc"}


def test_double_failures(
        tests_dir: Path,
        want: dict[str, dict[tuple[str, str], bool]],
) -> tuple[list[str], int, int]:
    """Every test-double override of its interface contract.

    Returns (problems, doubles scanned, interface methods checked). The
    source scan is the parent-side companion to compilation: the framework
    test targets are the only strict build of these doubles, and a consumer
    pin bump never built them (2026-10-21 `NoopInput` regression).
    """
    problems: list[str] = []
    doubles = methods = 0
    for path in sorted(p for p in tests_dir.rglob("*")
                       if p.suffix in TEST_SOURCE_SUFFIXES):
        text = strip_comments(path.read_text())
        for cls, base, body in double_declarations(text):
            doubles += 1
            site = override_methods(body)
            for key, is_const in sorted(want.get(base, {}).items()):
                methods += 1
                if key not in site:
                    problems.append(
                        f"test double {cls} ({path.name}) has no override for "
                        f"{base}::{key[0]}({key[1]})")
                elif site[key] != is_const:
                    problems.append(
                        f"test double {cls} ({path.name}) const-ness drift on "
                        f"{base}::{key[0]}({key[1]})")
    return problems, doubles, methods


def strip_comments(text: str) -> str:
    """Remove // line comments and /* */ blocks before marker scans.

    The single-generation markers must be judged in *code*: a comment that
    explains the retirement ("Phase 4b retired GBARECOMP_HAVE_SDL2 ...") is
    documentation, not a live reference. (Naive on string literals containing
    `//`; none of the scanned files carry one, and the markers are
    identifiers, so the trade is fine.)
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def single_generation_failures(iface_text: str, host_text: str,
                               factory_text: str) -> list[str]:
    out: list[str] = []
    if "WindowBackendOpenParams" in iface_text:
        out.append("flat generation: WindowBackendOpenParams still in the seam")
    if "host_make_sdl_backend" in host_text or "host_make_sdl_backend" in factory_text:
        out.append("SDL backend: host_make_sdl_backend still present")
    if "GBARECOMP_HAVE_SDL2" in host_text:
        out.append("SDL backend: GBARECOMP_HAVE_SDL2 still in host_window.cpp")
    if "GBARECOMP_HAVE_SDL2" in factory_text:
        out.append("SDL backend: GBARECOMP_HAVE_SDL2 still in "
                   "host_backend_factory.cpp")
    if re.search(r"\b(?:class|struct)\s+Backend\b", host_text):
        out.append("SDL backend: an inline `Backend` struct still exists in "
                   "host_window.cpp")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iface", type=Path, default=DEFAULT_IFACE)
    ap.add_argument("--backend-h", type=Path, default=DEFAULT_BACKEND_H)
    ap.add_argument("--backend-cpp", type=Path, default=DEFAULT_BACKEND_CPP)
    ap.add_argument("--host-window", type=Path, default=DEFAULT_HOST_WINDOW)
    ap.add_argument("--factory", type=Path, default=DEFAULT_FACTORY)
    ap.add_argument("--tests", type=Path, default=DEFAULT_TESTS,
                    help="framework test tree scanned for interface doubles")
    args = ap.parse_args(argv)

    for p in (args.iface, args.backend_h, args.backend_cpp, args.host_window,
              args.factory):
        if not p.exists():
            print(f"check_raylib_backend_complete: missing {p}", file=sys.stderr)
            return 1

    iface_text = strip_comments(args.iface.read_text())
    host_text = strip_comments(args.host_window.read_text())
    factory_text = strip_comments(args.factory.read_text())

    # ── 1. single generation ─────────────────────────────────────────────
    failures = single_generation_failures(iface_text, host_text, factory_text)

    # ── 2. pure interfaces ───────────────────────────────────────────────
    want: dict[str, dict[tuple[str, str], bool]] = {}
    for name in INTERFACE_NAMES:
        body = struct_body(iface_text, name)
        if not body:
            failures.append(f"interface: class {name} not found in the seam")
            continue
        want[name] = {}
        for key, (is_const, is_pure) in interface_methods(body).items():
            if not is_pure:
                failures.append(
                    f"impure interface method: {name}::{key[0]}({key[1]}) has "
                    "a defaulted body — pure-virtual interfaces are the "
                    "contract (silent-inheritance bug class)")
            want[name][key] = is_const

    # ── 3. complete backend, per interface ───────────────────────────────
    # Each interface is checked against ITS OWN site (IMPL_SITES): the scoping
    # is the point — a union over both files would let a method implemented in
    # the wrong impl class satisfy the guard.
    header_text = strip_comments(args.backend_h.read_text())
    cpp_text = strip_comments(args.backend_cpp.read_text())
    sites: dict[str, dict[tuple[str, str], bool]] = {}
    for name in INTERFACE_NAMES:
        where, cls = IMPL_SITES[name]
        text, fname = ((header_text, "raylib_backend.h") if where == "h"
                       else (cpp_text, "raylib_backend.cpp"))
        body = struct_body(text, cls)
        if not body:
            failures.append(f"impl site: class {cls} not found in {fname}")
            continue
        sites[name] = override_methods(body)

    missing: list[str] = []
    mismatched: list[str] = []
    total = 0
    for name in INTERFACE_NAMES:
        cls = IMPL_SITES[name][1]
        site = sites.get(name, {})
        for key, is_const in sorted(want.get(name, {}).items()):
            total += 1
            if key not in site:
                missing.append(f"{name}::{key[0]}({key[1]}) — not overridden "
                               f"in {cls}")
            elif site[key] != is_const:
                mismatched.append(
                    f"{name}::{key[0]}({key[1]}) const-ness: interface "
                    f"{'const' if is_const else 'non-const'}, {cls} "
                    f"{'const' if site[key] else 'non-const'}")

    # ── 4. complete test doubles ─────────────────────────────────────────
    # The framework's test tree is scanned, not built: these doubles only
    # compile in the fork's own test targets, and the pin bump that shipped
    # the 2026-10-21 break never built them. Scan the pinned submodule so a
    # consumer-side gate sees the drift at bump time.
    double_problems: list[str] = []
    doubles = double_methods = 0
    if args.tests.is_dir():
        double_problems, doubles, double_methods = test_double_failures(
            args.tests, want)

    if failures or missing or mismatched or double_problems:
        print(f"window seam INCOMPLETE ({total} interface methods)")
        for f in failures:
            print(f"  {f}")
        for m in missing:
            print(f"  MISSING override: {m}")
        for problem in mismatched:
            print(f"  MISMATCH: {problem}")
        for problem in double_problems:
            print(f"  DOUBLE: {problem}")
        return 1

    print(f"window seam complete: {total} interface methods across "
          f"{len(INTERFACE_NAMES)} surfaces, all pure, each overridden at its "
          "own impl site")
    print("single generation: no flat class, no SDL backend")
    print(f"test doubles complete: {doubles} doubles, {double_methods} "
          "interface methods")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
