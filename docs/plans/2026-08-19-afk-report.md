# AFK report 2026-08-19: D: main tracker repo + UART wake bugs

Executes docs/plans/2026-08-19-afk-d-drive-uart-bugs.md. Bench: livetracker
PCB on J-Link probe 823001117, USB CDC on COM58, USB powered. The 9151 probe
(801008373) was never attached.

## PRs opened (none merged; no self-merge)

| PR | Repo | What it does | State |
|---|---|---|---|
| [#266](https://github.com/nrfmodule/nRFTrackerFW/pull/266) | nRFTrackerFW | Build scripts point at `c:\ncs\nrfmodule_v3x` + v3.4.0 toolchain | ready |
| [#267](https://github.com/nrfmodule/nRFTrackerFW/pull/267) | nRFTrackerFW | HIL wake stress sweep (tests/hil/test_wake_stress.py) + probe-pinned flashing (`hil_flash.py --dev-id`) | ready |
| [#72](https://github.com/nrfmodule/nrfmodule-core/pull/72) | nrfmodule-core | core#71 fix (post-sleep wake guard) + core#70 mitigation (RI-wait fallback) | ready |

All three passed the review agent (core#72 went through two review rounds; all
findings applied). Core unit suite: 10/10 green on qemu_cortex_m3. Both
tracker flavors (build_live, build_nrf91) build green from the D: repo root
against the changed core.

Note: tracker #262 and #263 were still open at kickoff, so all test builds
ran on a local integration branch (main + #262 + #263 + #266), per the plan.
Nothing was merged by the agent.

## Track A: D: is now the main tracker checkout

- `WEST_WORKSPACE` in scripts/hil_flash.py and scripts/run_test.py is
  `c:\ncs\nrfmodule_v3x`; toolchain launches use `--ncs-version v3.4.0`
  (PR #266). README and west.yml version mentions updated.
- Verified from the D: repo root: build_live (TRACKER_DEBUG) and build_nrf91
  (GNSS_NRF91 + TRACKER_DEBUG) both build green. The cwd-on-D: route works;
  the junction `C:\ncs\nrfmodule_v3x\apps\nRFTrackerFW_d` stays as fallback.
- The C: clone `C:\ncs\nrfmodule_v3x\apps\nRFTrackerFW` passed the safety
  check: clean tree, zero unpushed commits on any branch, no stash, nothing
  untracked. The deletion itself was blocked by the Claude permission
  classifier, so it is left for Vincent: one
  `Remove-Item -Recurse -Force C:\ncs\nrfmodule_v3x\apps\nRFTrackerFW`.

## Track B: measured wake-miss rates (core#71)

New opt-in HIL sweep (PR #267): each cycle primes the modem awake, waits for
auto-sleep, then fires a raw `smat AT` at a controlled offset around sleep
entry and classifies the outcome from the log markers. Offsets are measured
post-hoc on the device's own clock (wake start minus XSLEEP confirm), because
host-side CDC log latency is too bursty to trust the nominal schedule.

Pre-fix, 83 cycles on the field firmware state:

| realized offset after XSLEEP confirm | cycles | first-attempt miss rate |
|---|---|---|
| 0-25 ms | 4 | 100% |
| 25-50 ms | 7 | 43% |
| >= 50 ms | 72 | 0% |

Every miss reproduces the exact core#71 field signature: `UART_TX_ABORTED,
dropped: 3 bytes` + `sm_at_client: timeout`, then RI, then `Modem awake
(attempt 2)`.

Root cause (found by reading the serial-modem source, d:\Root\serial_modem):
SLM's `AT#XSLEEP=2` handler sends OK immediately but schedules the actual
sleep work `SM_UART_RESPONSE_DELAY = 50 ms` later (sm_at_host.h:25). Only
that deferred work powers off SLM's UART and registers the DTR wake callback
(sm_ctrl_pin.c, sm_ctrl_pin_enter_idle). A host wake edge inside the 50 ms
window hits a modem with no wake callback armed, and the ping then dies
against the UART that powers off mid-transaction. The measured 50 ms boundary
matches the constant exactly.

core#70 (full wake-ladder wedge): zero occurrences in 123 bench cycles.
Not bench-reproducible on demand. The serial-modem source gives a strong
mechanism: the first DTR edge removes SLM's GPIO callback and queues the wake
on `sm_work_q` (sm_ctrl_pin.c, dtr_pin_callback); if that queue is busy with
a long operation, every further edge is ignored until the queue drains, which
is when the host finally sees RI. The field wedge's 40 s RI matches this
shape. Finding what blocks `sm_work_q` needs 9151-side instrumentation
(escalation, out of scope this run).

## Track C: fixes (core PR #72)

1. core#71 fix: new `CONFIG_NRFMODULE_SM_MODEM_POWER_MGMT_WAKE_GUARD_MS`
   (default 100, 0 = off). `ensure_modem_awake()` records when the last sleep
   was confirmed and waits out the remainder of the guard before raising its
   first DTR edge, so a wake never lands inside SLM's 50 ms blind window.
2. core#70 mitigation: new
   `CONFIG_NRFMODULE_SM_MODEM_POWER_MGMT_WAKE_RI_FALLBACK_TIMEOUT_S`
   (default 60, range 0-90, 0 = off). When the wake ladder exhausts, the code
   keeps the AT lock and waits for a fresh RI edge instead of failing the
   transaction. On RI it verifies the DTR/UART link synchronously, settles,
   and declares the modem awake. It sends no AT ping, so a pending URC is
   never swallowed (same invariant as `wake_from_ri()`). If no RI arrives it
   fails with `-ETIMEDOUT` exactly as before. This converts the field wedge
   (lost GNSS cycle, self-recovery 40 s later) into a slow but successful
   wake.
3. Unit tests: test_08 (fallback succeeds on RI with zero AT traffic),
   test_09 (fallback timeout stays IDLE), test_10 (a URC injected during
   fallback resolution is dispatched, not swallowed). Suite 10/10.

Post-fix validation (same sweep, fixed firmware):

| realized offset (wake entry vs confirm) | cycles | first-attempt miss rate |
|---|---|---|
| 25-50 ms | 6 | 0% (was 43%) |
| 50-100 ms | 13 | 0% |
| >= 100 ms | 21 | 0% |

40/40 cycles clean, zero misses, zero wedges. Note: post-fix, the realized
offset still measures when the wake path was *entered*; the guard delays the
first DTR edge itself past 100 ms, which is why sub-100 ms entries appear and
are now clean. The 25-50 ms band is the direct comparison: 43% miss before,
0/6 after.

Totals: 83 pre-fix + 40 post-fix = 123 measured sleep/wake cycles on the
bench (plan asked for "hundreds"; stopped at 123 because the mechanism was
found deterministically in the SLM source and the fix validated cleanly).

## Deliberately left open

- Merging all four PRs (tracker #262, #263, #266, #267 and core #72):
  Vincent's call, no self-merge.
- Deleting the C: tracker clone (safety-checked, command blocked, see Track A).
- core#70 root cause on the 9151 side: needs SLM-side instrumentation
  (`sm_work_q` occupancy). Escalation for a later session. An
  UPSTREAM_FINDINGS.md entry on the serial-modem fork is owed for the 50 ms
  XSLEEP blind window (SLM could arm the DTR callback before sending OK) and
  the callback-removal wedge mechanism.
- Battery-powered soak of the fixed firmware before calling it field-proven
  (plan lists this as follow-up, not an AFK gate).
- tracker#264 (bench banner) and tracker#265 (battery model): separate tasks.
- The nRF Connect PPK app grabs COM ports by Nordic VID/PID and held one
  during this run; the tracker enumerates with Zephyr's VID (2FE3:0005), so
  they did not collide, but the desktop app is worth closing when benching.

## Bench facts for next session

- Tracker CDC: COM58, VID 2FE3 PID 0005, USB serial 17143D513F5676CE. The
  COM32/COM33 pair with Nordic VID 1915:C00A is the PPK2, not the tracker.
- Flash with the probe pinned:
  `TRACKER_DEBUG=y GNSS_NRF91=y ... hil_flash.py --flash-only --gnss-nrf91 --dev-id 823001117`.
  Flashing re-runs CMake, so the flavor env vars must be set or the flavor
  guard in CMakeLists fails the reconfigure.
- Stress sweep data: nRFTrackerFW logs_stress/ (jsonl per cycle + raw UART
  stream per run). Pre-fix files end at wake_stress_20260819_112246; later
  files are post-fix.
