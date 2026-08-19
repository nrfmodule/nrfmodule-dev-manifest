# AFK run 2026-08-19: D: as main tracker repo + UART wake bugs

Goal: (1) make `d:\Root\nrfmodule_workspace\nRFTrackerFW` the single tracker
checkout, building against the NCS 3.4.0 workspace `c:\ncs\nrfmodule_v3x`.
(2) Reproduce the two modem-UART wake bugs from the 08-18/19 field run on the
bench, then fix them. Scope agreed with Vincent 2026-08-19.

## Evidence (field run 2026-08-18/19, logs in nRFTrackerFW logs/340_test)

- core#70: one full wake wedge. Two back-to-back 5-attempt wake ladders
  failed (10 DTR edge re-cycles ignored), GNSS session start/stop got -116,
  modem woke itself via RI 40 s later. One GNSS cycle lost. The edge
  re-cycle fix is already in `ensure_modem_awake()`, so the known
  edge-trigger trap is not the cause.
- core#71: first-attempt wake miss roughly once per 1-2 h. Shape is always
  `UART_TX_ABORTED, dropped: N bytes` + `sm_at_client: timeout`, then RI
  arrives and attempt 2 succeeds. Matches the race the `wake_from_ri()`
  comment documents as "narrows, but cannot close". Zero data lost in 18 h.

## Bench facts

- Board: livetracker PCB on J-Link probe 823001117. USB CDC currently COM58,
  but CDC COM numbers drift; detect the port, do not hardcode. Force
  `kernel reboot cold` per the HIL loop convention (scripts/hil_cycle.py).
- Firmware flavor: livetracker/nrf52840 with GNSS_NRF91=y and
  TRACKER_DEBUG=y (needs tracker PR #262 merged; debug.conf adds the smat
  raw-AT shell and RTT shell). Build dir build_nrf91 via hil_flash.py
  --gnss-nrf91.
- The livetracker PCB has no antenna path for nRF91 GNSS, so no fix will
  ever arrive. That is fine: AT#XGNSS start/stop still exercises the exact
  UART wake path that wedged in the field. LTE is real on this bench.
- Board is USB-powered on the bench; the field logs were on battery. Accept
  USB for repro work. The final fix gets a battery soak before it is called
  field-proven (listed as a follow-up, not an AFK gate).
- Do NOT attach the second probe (801008373) to the 9151: J-Link attach
  keeps the modem awake and suppresses the sleep-entry bugs being hunted.
  9151-side instrumentation is an escalation step for a later session.

## Track A: D: becomes the main tracker checkout

1. Preconditions: tracker PRs #262 (feature/debug-config) and #263
   (ble product-id fix) merged by Vincent. If not merged when the run
   starts, base test builds on a local merge of those branches and say so
   in the report; do not merge PRs.
2. Pull merged main into the D: clone.
3. Point the build scripts at the 3.4.0 workspace: WEST_WORKSPACE in
   scripts/hil_flash.py and scripts/run_test.py becomes
   `c:\ncs\nrfmodule_v3x`; toolchain launch becomes --ncs-version v3.4.0.
   One tracker PR.
4. Verify from the D: repo root: build_live (livetracker, TRACKER_DEBUG)
   and build_nrf91 (livetracker, GNSS_NRF91 + TRACKER_DEBUG) both green
   via hil_flash.py --build-only. This validates the cwd-on-D: route
   (west relpath crashes only when cwd and app are on different drives;
   the junction route C:\ncs\nrfmodule_v3x\apps\nRFTrackerFW_d is already
   build-verified 2026-08-19 as fallback).
5. Retire the C: clone `C:\ncs\nrfmodule_v3x\apps\nRFTrackerFW` only after
   a safety check: `git status` clean, no unpushed commits on any branch
   (`git log --branches --not --remotes`), no untracked files worth
   keeping. Anything unpushed: stop, report, do not delete. Replace with
   nothing; the junction nRFTrackerFW_d stays for ad-hoc in-workspace
   builds.

## Track B: reproduce the wake bugs (52840 probe only)

6. New HIL stress script under tests/hil (pytest + RTT shell harness,
   python-test conventions). Loop: let the modem reach sleep, then fire an
   AT command at a swept offset around sleep entry (before, at, after the
   XSLEEP confirm) to widen the core#71 race window. Hundreds of cycles.
   Count per offset: first-attempt misses, full 5-attempt wedges, recovery
   path taken. Log everything with timestamps for correlation.
7. Correlate any core#70-class wedge with modem activity visible in URCs
   (CEREG, RRC, PSM/TAU timing). The hypothesis to test: the modem ignores
   DTR edges while busy with its own LTE activity.
8. If stock logs cannot discriminate, add host-side instrumentation behind
   TRACKER_DEBUG (DTR level readback after set, RI line state and timing).
   Keep it in the debug flavor only.

## Track C: fixes (driven by Track B data)

9. core#71: if the data shows a cheap close (re-check modem state under
   the AT lock before TX, or retry the TX after wake instead of failing
   the transaction), fix it in nrfmodule-core with a unit test. If closing
   is invasive, downgrade the first-attempt miss logging so field logs do
   not carry `<err>` for a self-healing path. Either way the decision is
   justified by the measured miss rate.
10. core#70: host-side mitigation regardless of root cause: when the full
    wake ladder fails, arm a bounded RI-wait fallback instead of failing
    the GNSS cycle outright (the field wedge self-recovered via RI in
    40 s). Plus whatever the correlation data supports. nrfmodule-core PR
    with unit tests; the stress script from Track B becomes the regression
    test.
11. Gates per PR: core unit tests green, both tracker flavors build from
    D:, review agent on the diff, stress script shows the fixed path (miss
    rate drop for #71, wedge handled without a lost cycle for #70). PRs
    opened for Vincent; no self-merge.

## Out of scope

- 9151/SLM-side changes and 9151-side debugging (escalation for a later
  session if Track B is inconclusive).
- Battery-powered soak (follow-up after merge).
- tracker#264 (bench banner) and tracker#265 (battery model): separate
  small tasks, not this run.
