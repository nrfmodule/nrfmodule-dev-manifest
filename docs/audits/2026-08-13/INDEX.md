# 2026-08-13 desk review wave (post-v0.4.0)

Contract: docs/plans/2026-08-13-afk-review-wave.md. Desk only; the bench
belonged to the wedge-hunt run. Reviewed `main` at fixed SHAs:

- nRFTrackerFW `7150f1353cc1345cb8bc801988ae3a6aab936b43` (v0.4.0)
- nrfmodule-sdk `d6302443fd6ce426f9255685cf116b0bd3663a6b`
- nrfmodule-core `449049287f73cc53257eda2c58440ba36503b8dc`

## Files in this directory

| File | Task | Content |
|---|---|---|
| t1-modem-wedge-210-comment.md | T1 | Modem-wedge posture map, posted verbatim as the [#210 comment](https://github.com/nrfmodule/nRFTrackerFW/issues/210#issuecomment-5281100238). Confirms the no-consumer claim, maps detection and the missing recovery paths, blast-radius table per product, PR #222 gap assessment, cross-referenced with nrfmodule-core#64. |
| trackerfw-findings.md | T2 | 13 confirmed findings (10 distinct defects) on tracker main since the 07-29 audit. 1 blocker, 5 should-fix, 4 nit. Method: 8 parallel reviewers, one adversarial verifier per candidate; 14 of 18 candidates survived. |
| sdk-findings.md | T2 | 1 confirmed sdk finding (board_power triplication). |
| issues-to-file.md | T2 | The dedupe decisions and full issue body drafts. |
| filed-issues.md | T2/T4 | Issue numbers actually filed, with links. |
| qa-coverage.md | T4 | Spec-vs-tests coverage table (13/19 covered), missing negative/boundary cases in risk order, materiality verdict, method note on the uncommitted spec. |

## PRs opened by this wave (open, not self-merged)

- [nRFTrackerFW #232](https://github.com/nrfmodule/nRFTrackerFW/pull/232): docs truth sweep, closes #172. Docs-only paths; no CI triggered.
- [nRFTrackerFW #230](https://github.com/nrfmodule/nRFTrackerFW/pull/230): scripts/check_flavors.py release-image flavor check plus the proposed release-skill line in the PR body. Hosted CI failed in seconds on the org billing wall; noted in the PR body, not retried; local self-test green.

## Headline results

1. T1: the firmware has zero modem-wedge handling on main. The core emits
   the link-dark event; nothing consumes it, nothing resets the modem, no
   watchdog exists on either MCU. PR #222 (unmerged) covers the observed
   shapes; four core-side gaps remain (AWAKE-latch bug, flapping never trips
   the threshold, #XCLOSE socket leak, spacing residue).
2. T2 blocker: the raw modem AT shell ships in every image including the
   v0.4.0 release, reachable over unpaired BLE NUS ([#233](https://github.com/nrfmodule/nRFTrackerFW/issues/233)).
3. T4: unit coverage is strong (34 suites, 659 tests); the material gaps are
   hardware proof of the loss-critical paths ([#231](https://github.com/nrfmodule/nRFTrackerFW/issues/231)).
