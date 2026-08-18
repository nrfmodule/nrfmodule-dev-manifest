# AFK run 2026-08-13 — core#64 wedge hunt (forced reproduction)

Single track. Force, reproduce, and root-cause the AT wake-state desync from
core#64 on the BENCH LIVETRACKER. Do not touch the pigeontracker boards.

Experimental code IS allowed, with a fence: instrumentation and fault
injection only (new diag shell commands, extra logging, forced-wedge paths),
on throwaway `diag/wedge-hunt` branches (tracker and/or core as needed),
flashed only to the bench livetracker. The board is USB-powered with J-Link
attached; a bad build is recovered with `python scripts/hil_cycle.py`, so
flashing experiments is cheap. Fix code: only after the root cause is named,
and only as a DRAFT PR referencing core#64 for Vincent to review. Nothing
merges in this run.

## Background

Full context: nrfmodule-core issue #64 (both comments) and the capture
`d:\Root\nrfmodule_workspace\logs_ble\2026-08-13-pt-wake-wedge-rtt.txt`.
One occurrence so far, on the first boot after the 52840 was J-Link-reflashed
while the 9151 kept running (likely asleep). Signature: failure bursts have NO
"waking up..." lines + `UART_TX_ABORTED` (9151 UART actually off); flapping,
not permanent; socket leak on failed `#XCLOSE`; `AT interface dark after 5
consecutive timeouts` fired with no consumer; only a reboot recovered.

Three hypotheses, in current likelihood order:
- **A. post-flash artifact**: fresh 52840 link state vs 9151 in unknown
  DTR/sleep state; something survives the boot XRESET sync and bites minutes
  later.
- **B. wake-latch state-machine bug** (closed core#55 family, new path): a
  path that leaves the client latch AWAKE/UART-enabled without the modem
  agreeing.
- **C. DTR enable-delay race**: 50 ms `UART_ENABLE_DELAY_MS` lost under LTE
  load; TX starts before the 9151's UART is up.

## Rig

- Bench livetracker: J-Link attached, USB CDC shell on COM58 (drifts after
  reflash: `python scripts/hil_shell.py --list`). It has its own SIM and
  registers; PSM cycles and uploads run like the pigeon board.
- Before every experiment: `log enable dbg sm_modem_power_mgmt` and
  `log enable dbg sm_at_client` on the shell (runtime, no rebuild).
- Capture every session's RTT/CDC output to a file under
  `d:\Root\nrfmodule_workspace\logs_ble\` (name: date + experiment id).
  A watcher that flags `UART_TX_ABORTED`, `AT interface dark`, and the absence
  of "waking up..." before traffic is worth 20 lines of Python; write it once,
  reuse per experiment.

## Experiments, in order

- **E0 — flash replay (tests A, cheapest, do first).** Confirm the modem is
  in confirmed XSLEEP (log line), reflash the 52840 via
  `python scripts/hil_flash.py --flash-only`, then watch 10 min of normal
  cycling. Repeat 5x. Any wedge = A reproduced; zero wedges in 5 runs =
  A weakened substantially.
- **E2 — forced race (tests C, then B).** `smsh uart auto <ms>` at runtime
  shrinks the 9151's UART auto-disable inactivity window; step down
  100 -> 20 -> 5 ms while running uploads. If TX_ABORTED bursts appear but
  wake lines are PRESENT and recovery works: that is C's shape, latch fine.
  If the no-wake-lines wedge appears: B reproduced on demand. Restore with
  `smsh uart auto 100` and a reboot when done.
- **E4 — synthetic wedge (tests B's mechanism, leaves the regression
  trigger).** On the diag branch, add a shell command that forces the
  failure state directly: leave the client wake latch AWAKE / UART enabled
  while the 9151 actually sleeps (for example, suppress the DTR toggle on
  the next wake). Flash the bench board, trigger it, and compare the trace
  against the field capture. A signature match (no "waking up..." lines,
  `UART_TX_ABORTED`, AT-dark after 5 timeouts) proves the mechanism and
  leaves a one-command reproducer for regression-testing the eventual fix.
  Document the command and branch in the issue comment.
- **E1 — natural soak (tests B/C base rate; LAST, background).** Run only
  after E0/E2/E4, as the overnight tail, on a clean build from unmodified
  main (never the diag build; keep base-rate evidence clean): no injection,
  normal cycling with uploads (kick occasional `sync now` if the queue is
  empty), watcher on. The field units have run stable for days, so the
  natural rate is low; do not block on this. If an earlier experiment
  already reproduced the wedge, E1 is optional confirmation, not a gate.
- **E3 — discriminate.** From whichever trace fired: does the client skip the
  DTR toggle (latch believes enabled) or toggle-and-lose-the-delay? Name the
  code path in sm_modem_power_mgmt / sm_at_client (read the core sources,
  cite file:line). Also record the socket table (`#XSOCKET?` via `smat`)
  after any failed close.

## Deliverable

One comment on nrfmodule-core#64: per-experiment results (counts, not
adjectives), the discriminating trace excerpt, the named code path or the
surviving hypotheses, the synthetic-reproducer command and its branch, and
the recommended fix direction (plus the draft-PR link if one was opened).
Log files listed by path. Update the tracker PR #222 thread only if the
findings change the ladder's design.

## Rules

- Code is for instrumentation and fault injection only: diag shell
  commands, logging, counters, all on throwaway `diag/wedge-hunt` branches.
  No changes on main, no Kconfig changes in shipping configs, nothing
  merged. A fix, once the root cause is named, goes up as a DRAFT PR only.
- Livetracker only. If the bench board wedges permanently, `reboot` recovers
  it; if the shell is gone too, `python scripts/hil_cycle.py` reflash is the
  recovery — never a J-Link recover.
- End the run with a clean build from unmodified main reflashed on the
  bench board, rebooted, and `smsh uart auto 100` semantics restored. The
  diag branches stay pushed for reuse; the board does not keep running
  injection firmware unattended.
