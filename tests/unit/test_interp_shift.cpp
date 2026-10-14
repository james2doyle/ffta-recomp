// Host unit tests for the interp_shift helpers (host_platform.h).
// Registry-free companion to test_ram_dispatch.cpp:
// run_interp_shift_tests() is invoked from that harness's main, so the
// ffta_unit_tests binary keeps a single PASS/FAIL line for
// tools/check.py.
//
// Guards issue-#9 3b (true-midpoint interpolation): the scroll-step
// measurement (wrap-aware dominant layer) and the half-pixel shift blit
// (identity, integer shifts, fractions, edges, sign convention). No
// ROM/BIOS/window needed — pure arithmetic.
//
// The sign-convention test pins the fix for the first 3b device
// validation: the midpoint shifts the CURRENT frame BACK by half the
// measured step (sh = -d); the extrapolating sign (+d) overshoots into
// snaps and read as whiplash on camera whips.
#include "host_platform.h"

#include <cstdint>
#include <cstdio>
#include <vector>

// The helpers live in the gbarecomp-local runtime work. A pristine
// checkout — CI — compiles the pinned header without them; compile this
// whole test away there instead of breaking the unit build.
#if defined(INTERP_SHIFT_API)
#define INTERP_SHIFT_TESTING 1
#endif

namespace {

int shift_failures = 0;

#define SHIFT_CHECK(cond)                                                   \
    do {                                                                    \
        if (!(cond)) {                                                      \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
            ++shift_failures;                                               \
        }                                                                   \
    } while (0)

#if INTERP_SHIFT_TESTING
using gbarecomp::interp_shift::dominant_step;
using gbarecomp::interp_shift::fold_scroll_delta;
using gbarecomp::interp_shift::frame_mean_abs_diff;
using gbarecomp::interp_shift::kScrollSnapshotBytes;
using gbarecomp::interp_shift::shift_blit;

// Scroll snapshot builder: 16 bytes, HOFS/VOFS per layer (9-bit).
void set_scroll(uint8_t io[kScrollSnapshotBytes], unsigned layer, int h,
                int v) {
    io[layer * 4u + 0u] = static_cast<uint8_t>(h & 0xFF);
    io[layer * 4u + 1u] = static_cast<uint8_t>((h >> 8) & 0xFF);
    io[layer * 4u + 2u] = static_cast<uint8_t>(v & 0xFF);
    io[layer * 4u + 3u] = static_cast<uint8_t>((v >> 8) & 0xFF);
}

void step(const uint8_t prev[kScrollSnapshotBytes],
          const uint8_t cur[kScrollSnapshotBytes], int32_t* dh,
          int32_t* dv) {
    dominant_step(prev, cur, dh, dv);
}
#endif

}  // namespace

int run_interp_shift_tests() {
#if !INTERP_SHIFT_TESTING
    std::printf("interp shift: helpers unavailable (pristine "
                "submodule); skipped\n");
    return 0;
#else
    // Fold: 9-bit wrap lands in [-256, 256].
    SHIFT_CHECK(fold_scroll_delta(10) == 10);
    SHIFT_CHECK(fold_scroll_delta(-10) == -10);
    SHIFT_CHECK(fold_scroll_delta(256) == 256);
    SHIFT_CHECK(fold_scroll_delta(-256) == -256);
    SHIFT_CHECK(fold_scroll_delta(257) == -255);
    SHIFT_CHECK(fold_scroll_delta(-257) == 255);
    SHIFT_CHECK(fold_scroll_delta(511) == -1);
    SHIFT_CHECK(fold_scroll_delta(-511) == 1);
    SHIFT_CHECK(fold_scroll_delta(512) == 0);

    // Dominant step over snapshots.
    {
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        int32_t dh = 9, dv = 9;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 0 && dv == 0);  // all still
    }
    {
        // Single layer pans: BG2 +10 HOFS.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(cur, 2, 10, 0);
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 10 && dv == 0);
    }
    {
        // Wrap crossing: 510 -> 2 is +4, not -508.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(prev, 1, 510, 0);
        set_scroll(cur, 1, 2, 0);
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 4 && dv == 0);
    }
    {
        // Wrap crossing the other way: 2 -> 510 is -4.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(prev, 3, 2, 7);
        set_scroll(cur, 3, 510, 7);
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == -4 && dv == 0);
    }
    {
        // Two layers moving IDENTICALLY vote one consensus step.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(cur, 2, 10, 0);
        set_scroll(cur, 3, 10, 0);
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 10 && dv == 0);
    }
    {
        // Still layers ride along: a layer that did not move — even at
        // a nonzero offset — does not vote; the single mover stands.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(prev, 0, 200, 100);
        set_scroll(cur, 0, 198, 100);
        set_scroll(prev, 1, 215, 81);
        set_scroll(cur, 1, 215, 81);
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == -2 && dv == 0);
    }
    {
        // Disagreement (issue #9 rebase, dense capture 2026-10-13):
        // BG0/BG1 pan −3 while BG2/BG3 jump 0 → 648 raw (136 masked).
        // Not a camera pan — no midpoint; live frame on all ticks.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(prev, 0, 191, 49);
        set_scroll(cur, 0, 188, 46);
        set_scroll(prev, 1, 191, 49);
        set_scroll(cur, 1, 188, 46);
        set_scroll(cur, 2, 648, 0);
        set_scroll(cur, 3, 648, 0);
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 0 && dv == 0);
    }
    {
        // Overlay dance legs disagree too (−18 on BG2/3 while BG0/1
        // pan −4): no midpoint either.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(prev, 0, 180, 40);
        set_scroll(cur, 0, 176, 37);
        set_scroll(prev, 2, 630, 0);
        set_scroll(cur, 2, 612, 0);
        set_scroll(prev, 3, 630, 0);
        set_scroll(cur, 3, 612, 0);
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 0 && dv == 0);
    }
    {
        // Movers on different axes can never share one whole-frame
        // shift: no midpoint.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(cur, 0, 3, 0);
        set_scroll(cur, 1, 0, 507);  // -5 folded
        int32_t dh = 0, dv = 0;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 0 && dv == 0);
    }

    {
        // Wrap tie: +256 and -256 are different movers (the ambiguous
        // 9-bit wrap point) — consensus must reject, not average.
        uint8_t prev[kScrollSnapshotBytes] = {};
        uint8_t cur[kScrollSnapshotBytes] = {};
        set_scroll(prev, 0, 0, 0);
        set_scroll(cur, 0, 256, 0);
        set_scroll(prev, 1, 256, 0);
        set_scroll(cur, 1, 0, 0);
        int32_t dh = 7, dv = 7;
        step(prev, cur, &dh, &dv);
        SHIFT_CHECK(dh == 0 && dv == 0);
    }

    // Blit: 4x1 row [10,20,30,40] (RGB triples), rest of channels equal.
    auto make_row = []() {
        std::vector<uint8_t> px(4 * 1 * 3);
        for (int x = 0; x < 4; ++x)
            px[x * 3 + 0u] = px[x * 3 + 1u] = px[x * 3 + 2u] =
                static_cast<uint8_t>(10 * (x + 1));
        return px;
    };
    {
        // Identity: zero shift is byte-exact.
        auto src = make_row();
        std::vector<uint8_t> dst(12, 0xFF);
        shift_blit(src.data(), dst.data(), 4, 1, 0, 0);
        SHIFT_CHECK(dst == src);
    }
    {
        // Integer shift right one: sh=+2 half-px reads src[x+1], clamped.
        auto src = make_row();
        std::vector<uint8_t> dst(12, 0);
        shift_blit(src.data(), dst.data(), 4, 1, 2, 0);
        SHIFT_CHECK(dst[0] == 20 && dst[3] == 30 && dst[6] == 40 &&
                    dst[9] == 40);
    }
    {
        // Integer shift left one (the midpoint direction for a +2 step).
        auto src = make_row();
        std::vector<uint8_t> dst(12, 0);
        shift_blit(src.data(), dst.data(), 4, 1, -2, 0);
        SHIFT_CHECK(dst[0] == 10 && dst[3] == 10 && dst[6] == 20 &&
                    dst[9] == 30);
    }
    {
        // Half pixel: sh=+1 averages neighbours, weights (2,2)/4.
        // (2*10+2*20+2)/4=15, (2*20+2*30+2)/4=25, (2*30+2*40+2)/4=35,
        // edge holds 40.
        auto src = make_row();
        std::vector<uint8_t> dst(12, 0);
        shift_blit(src.data(), dst.data(), 4, 1, 1, 0);
        SHIFT_CHECK(dst[0] == 15 && dst[3] == 25 && dst[6] == 35 &&
                    dst[9] == 40);
    }
    {
        // Oversized shift collapses to the edge pixel.
        auto src = make_row();
        std::vector<uint8_t> dst(12, 0);
        shift_blit(src.data(), dst.data(), 4, 1, 100, 0);
        SHIFT_CHECK(dst[0] == 40 && dst[3] == 40 && dst[6] == 40 &&
                    dst[9] == 40);
        shift_blit(src.data(), dst.data(), 4, 1, -100, 0);
        SHIFT_CHECK(dst[0] == 10 && dst[3] == 10 && dst[6] == 10 &&
                    dst[9] == 10);
    }
    {
        // 1x1 image: every shift is the identity (clamp both axes).
        const uint8_t src[3] = {7, 7, 7};
        uint8_t dst[3] = {0, 0, 0};
        shift_blit(src, dst, 1, 1, 3, -5);
        SHIFT_CHECK(dst[0] == 7 && dst[1] == 7 && dst[2] == 7);
    }
    {
        // Vertical shift on a 1x3 column [10,20,30]: sh_v=+2 reads down.
        std::vector<uint8_t> src(1 * 3 * 3);
        for (int y = 0; y < 3; ++y)
            src[y * 3 + 0u] = src[y * 3 + 1u] = src[y * 3 + 2u] =
                static_cast<uint8_t>(10 * (y + 1));
        std::vector<uint8_t> dst(9, 0);
        shift_blit(src.data(), dst.data(), 1, 3, 0, 2);
        SHIFT_CHECK(dst[0] == 20 && dst[3] == 30 && dst[6] == 30);
    }
    {
         // Vertical half pixel: sh_v=+1 on [10,20,30] blends rows —
         // (2*10+2*20+2)/4=15, (2*20+2*30+2)/4=25, bottom edge holds 30.
         std::vector<uint8_t> src(1 * 3 * 3);
         for (int y = 0; y < 3; ++y)
             src[y * 3 + 0u] = src[y * 3 + 1u] = src[y * 3 + 2u] =
                 static_cast<uint8_t>(10 * (y + 1));
         std::vector<uint8_t> dst(9, 0);
         shift_blit(src.data(), dst.data(), 1, 3, 0, 1);
         SHIFT_CHECK(dst[0] == 15 && dst[3] == 25 && dst[6] == 30);
    }
    {
         // Negative odd vertical shift: sh_v=-1 clamps the top edge and
         // blends below it: [10, (10+20) avg = 15, (20+30) avg = 25].
         std::vector<uint8_t> src(1 * 3 * 3);
         for (int y = 0; y < 3; ++y)
             src[y * 3 + 0u] = src[y * 3 + 1u] = src[y * 3 + 2u] =
                 static_cast<uint8_t>(10 * (y + 1));
         std::vector<uint8_t> dst(9, 0);
         shift_blit(src.data(), dst.data(), 1, 3, 0, -1);
         SHIFT_CHECK(dst[0] == 10 && dst[3] == 15 && dst[6] == 25);
    }
    {
         // Diagonal negative half-pixel on 2x2 [[10,20],[30,40]]:
         // (0,0) clamps to 10; (1,0) blends 10/20 -> 15; (0,1) blends
         // 10/30 -> 20; (1,1) blends all four -> 25. Both negative-
         // remainder corrections fire on a real image.
         std::vector<uint8_t> src(2 * 2 * 3);
         const int vals[4] = {10, 20, 30, 40};
         for (int i = 0; i < 4; ++i)
             src[i * 3 + 0u] = src[i * 3 + 1u] = src[i * 3 + 2u] =
                 static_cast<uint8_t>(vals[i]);
         std::vector<uint8_t> dst(2 * 2 * 3, 0);
         shift_blit(src.data(), dst.data(), 2, 2, -1, -1);
         SHIFT_CHECK(dst[0] == 10 && dst[3] == 15);
         SHIFT_CHECK(dst[6] == 20 && dst[9] == 25);
    }
    {
        // HUD pin: static pixels keep exact bytes, moved pixels keep the
        // shifted image. prev=[A,X] cur=[A,Y] shifted=[S,T] -> [A,T].
        const uint8_t prev[6] = {10, 10, 10, 20, 20, 20};
        const uint8_t cur[6] = {10, 10, 10, 30, 30, 30};
        uint8_t mid[6] = {1, 2, 3, 4, 5, 6};
        gbarecomp::interp_shift::select_static(prev, cur, mid, 6);
        SHIFT_CHECK(mid[0] == 10 && mid[1] == 10 && mid[2] == 10);
        SHIFT_CHECK(mid[3] == 4 && mid[4] == 5 && mid[5] == 6);
    }
    {
        // All static: shifted image fully replaced by exact (in place).
        const uint8_t prev[3] = {9, 9, 9};
        const uint8_t cur[3] = {9, 9, 9};
        uint8_t mid[3] = {1, 2, 3};
        gbarecomp::interp_shift::select_static(prev, cur, mid, 3);
        SHIFT_CHECK(mid[0] == 9 && mid[1] == 9 && mid[2] == 9);
    }

    // Frame-identity metric (rebase veto input): identical → 0.0.
    {
        std::vector<uint8_t> a(8 * 8 * 3, 40), b(8 * 8 * 3, 40);
        SHIFT_CHECK(frame_mean_abs_diff(a.data(), b.data(), 8, 8) == 0.0f);
        // One sampled pixel (x=0,y=0 hits the stride-4 grid) delta 30 on
        // one channel: mean = 30 / (4 samples · 3 channels) = 2.5.
        b[0] = 70;
        SHIFT_CHECK(frame_mean_abs_diff(a.data(), b.data(), 8, 8) == 2.5f);
        // Every sampled pixel +100 on all channels → mean exactly 100.
        for (std::size_t i = 0; i < b.size(); ++i) b[i] = 140;
        SHIFT_CHECK(frame_mean_abs_diff(a.data(), b.data(), 8, 8) ==
                    100.0f);
        // Degenerate sizes are safe (and 0.0 → never vetoes on their own).
        SHIFT_CHECK(frame_mean_abs_diff(nullptr, b.data(), 8, 8) == 0.0f);
        SHIFT_CHECK(frame_mean_abs_diff(a.data(), b.data(), 0, 8) == 0.0f);
    }

    if (shift_failures) {
        std::printf("interp shift: %d failure(s)\n", shift_failures);
    }
    return shift_failures;
#endif
}
