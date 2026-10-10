// Host unit tests for the host-stack budget guard (mobile_platform.{h,cpp}).
// Registry-free companion to test_ram_dispatch.cpp: run_host_stack_guard_tests()
// is invoked from that harness's main, so the ffta_unit_tests binary keeps a
// single PASS/FAIL line for tools/check.py.
//
// Guards two regressions:
//   1. The predicates must be LIVE on this platform. They were desktop-stubbed
//      (always false) before the 2026-10-09 port; if that gating ever returns,
//      the armed-path checks here fail.
//   2. Two-tier ordering against the calling thread's real stack bounds: the
//      primary margin (host_stack_guard_arm_current reserve) must fire before
//      the critical tier, and the critical tier must stay inside the last
//      fraction of the stack.
//
// No ROM/BIOS needed.
#include "mobile_platform.h"

#include <cstdint>
#include <cstdio>

#if defined(__linux__)
#include <pthread.h>
#endif

// The guard APIs live in the host-stack-guard-desktop.patch work (applied on
// the pinned gbarecomp submodule). A pristine checkout — CI — compiles the
// pinned header, which does not declare them; compile this whole test away
// there instead of breaking the unit build. The patch-applied tree builds
// and runs it as before.
#if defined(__linux__) && defined(HOST_STACK_GUARD_API)
#define HOST_STACK_GUARD_TESTING 1
#endif

namespace {

int guard_failures = 0;

#define GUARD_CHECK(cond)                                                   \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::printf("guard CHECK failed: %s (%s:%d)\n", #cond, __FILE__, \
                        __LINE__);                                          \
            ++guard_failures;                                               \
        }                                                                   \
    } while (0)

}  // namespace

int run_host_stack_guard_tests() {
#if !HOST_STACK_GUARD_TESTING
    std::printf("host-stack guard: APIs unavailable (pristine submodule); "
                "skipped\n");
    return 0;
#else
    char here;

    // Unarmed: both tiers must be inert.
    GUARD_CHECK(!gbarecomp::mobile_stack_over_budget(&here));
    GUARD_CHECK(!gbarecomp::host_stack_critically_low(&here));

#if defined(__linux__)
    // Arm for this thread: 1 MiB primary margin; critical tier =
    // min(stack/16, 0.5 MiB) from the bottom.
    gbarecomp::host_stack_guard_arm_current(1u * 1024u * 1024u);

    pthread_attr_t attr;
    void* base = nullptr;
    std::size_t size = 0;
    if (pthread_getattr_np(pthread_self(), &attr) == 0 &&
        pthread_attr_getstack(&attr, &base, &size) == 0 && base != nullptr &&
        size > 2u * 1024u * 1024u) {
        const std::uintptr_t lo = reinterpret_cast<std::uintptr_t>(base);

        // Current sp is far above both margins.
        GUARD_CHECK(!gbarecomp::mobile_stack_over_budget(&here));
        GUARD_CHECK(!gbarecomp::host_stack_critically_low(&here));

        // 0.375 MiB from the bottom: inside both tiers.
        GUARD_CHECK(gbarecomp::mobile_stack_over_budget(
            reinterpret_cast<const void*>(lo + 0x60000u)));
        GUARD_CHECK(gbarecomp::host_stack_critically_low(
            reinterpret_cast<const void*>(lo + 0x60000u)));

        // 0.6875 MiB: inside the primary margin, outside the critical tier —
        // the tiers must be ordered and distinct.
        GUARD_CHECK(gbarecomp::mobile_stack_over_budget(
            reinterpret_cast<const void*>(lo + 0xB0000u)));
        GUARD_CHECK(!gbarecomp::host_stack_critically_low(
            reinterpret_cast<const void*>(lo + 0xB0000u)));

        // 1.5 MiB: above both margins.
        GUARD_CHECK(!gbarecomp::mobile_stack_over_budget(
            reinterpret_cast<const void*>(lo + 0x180000u)));
        GUARD_CHECK(!gbarecomp::host_stack_critically_low(
            reinterpret_cast<const void*>(lo + 0x180000u)));
    } else {
        std::printf("guard: thread stack bounds unavailable; "
                    "armed-path checks skipped\n");
    }
#endif

    if (guard_failures) {
        std::printf("host-stack guard: %d failure(s)\n", guard_failures);
    }
    return guard_failures;
#endif
}
