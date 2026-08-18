# AFK run 2026-08-14: modem connection stability — run report

Plan: `2026-08-14-afk-modem-stability.md`. All five tracks plus the stretch
item completed. Seven PRs opened, zero merged (no self-merge), one item
blocked on a physical bench action.

## Per track

| Track | Status | PR(s) | Notes |
|---|---|---|---|
| A tracker#241 | OPEN, all gates green | nRFTrackerFW#245 | Normalize in avirings_request (single choke point, both callers). Unit 3/3, both boards, HIL POST 200. |
| B core#65 | OPEN, all gates green | nrfmodule-core#66 + nrfmodule-sdk#44 | Budgets internal to the AT engine (answers Vincent's no-set-calls comment). 56 unit tests. HIL: 60 s #XRECV rode a 69.2 s device-clock budget, zero quarantine, zero link-dark. Also fixes the nrfmodule_http positive-error contract leak (#241's root class). |
| C slim recovery | OPEN, all gates green | nRFTrackerFW#248 | Replaces draft #222 (comment posted, safe to close). Dereg watchdog 60 min + link-dark consumer + abort gate. 14 policy tests. HIL: CFUN=4 dry run detach→re-register, recovery thread live, POST 200. Values pending Damir (dereg 60 / rate 30 / escalate 45 min; CFUN=4 dwell question). |
| D 9151 watchdog | OPEN; bench fire-test BLOCKED | ncs-serial-modem#3 | task_wdt on sm_work_q + HW WDT backstop, 10 s feed cadence (PSM-safe), XRECV timeouts clamped to half budget, bench-only AT#XWDTTEST. BLOCKED: bench J-Link is cabled to the 52840; the 9151 has no remote flash path. Fire-test procedure in the PR body; build_wdt_shorttimeout ready. Upstream robustness report filed as fork issue #2 (DevZone paste-ready; posting needs Vincent's forum account). Pin bump in ncs-serial-modem-livetracker west.yml owed after merge. |
| E #238 + #233 | OPEN, all gates green | nRFTrackerFW#246, #247 | #246: kick TOCTOU closed at the consume point, red-green proven. #247: AT shell out of release images; pigeontracker loses its only smat bench flavor (flagged), check_flavors still fails pigeontracker on pre-existing TRACKER_PWR_SHELL (separate ruling). Vincent sign-off flagged in the PR. |
| Stretch #235 | OPEN | nRFTrackerFW#249 | Second LOG_INF restored so the FS backend's DONE handler runs fs_sync. Not bench-verified (poweroff path unsafe remotely). |

## Issue updates posted

core#64 (what shipped + upstream report), core#65 (design answer to the
bump-the-default comment), tracker#210 (recovery stack map closed), PR #222
(superseded by #248).

## HITL items owed (do not block the PRs)

- Damir: dereg minutes / rate limit / escalation window; CFUN=4 dwell vs
  bounce; escalation window vs SDK spacing trade.
- Vincent: #247 flavor sign-off (incl. pigeontracker bench-flavor gap and
  TRACKER_PWR_SHELL), DevZone post of fork issue #2, bench cable move to the
  9151 for the D fire test, merges.

## Bench state at end of run

Livetracker bench (COM58, J-Link 823001117 on the nRF52840) is flashed with
the track C branch build (feature/210-slim-recovery + core feature/65),
registered, upload path proven (POST 200). The 9151 runs rev 2 serial modem
(pre-watchdog). Socket table left clean.

## Known residuals

- Link-dark cannot fire on a modem spewing continuous garbage (busy by
  definition); the dereg watchdog covers that mode indirectly. Noted in
  core#66.
- The 30-min spacing suppression gap from #210 is narrowed, not removed.
- D's boot-race analysis assumes task_wdt re-arms within ~10 s of a soft
  reset; measured only by inspection, bench measurement listed in the PR.
