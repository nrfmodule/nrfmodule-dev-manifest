# AFK run 2026-08-14: modem connection stability

Goal: make the modem link as stable as possible and remove the weird drops.
Scope agreed with Vincent 2026-08-14. Tracker PR #222 is now a draft, kept as
reference only. A slim redesign replaces it (track C).

## Failure classes (from field + bench evidence)

1. **UART transport wedge** (AT-dark bursts, wake-state desync). Root cause:
   SLM ran blocking connect/DNS/recv on the queue that drains UART RX.
   Fixed at the source: ncs-serial-modem PR #1, merged, bench-verified,
   6 h soak clean. Client half still open: core#65.
2. **Registration wedge** (forbidden-TA, field test 08-13). Modem answers AT
   but sits deregistered forever (54 min observed). The #222 trigger
   (5 AT timeouts) never fires here. Needs a deregistration watchdog.
3. **Dead modem** (SLM lockup, bench-only so far). Survives host reboot and
   host reflash. Livetracker has no 9151 reset line. Only real recovery is
   a watchdog inside the 9151 SLM firmware.

## Tracks

### A. tracker#241 — positive-errno discard fix (tiny, first)

- `lte_transport.c:170` forwards positive AT error (65536) to the uploader;
  `uploader.c:119` only treats rc<0 as failure, so the batch is acked and lost.
  Race-proven: 4 of 48 records lost.
- Fix: normalize in lte_transport (`err > 0 ? -EIO : err`). Unit test that a
  positive rc is NOT acked. One PR.

### B. core#65 — per-command AT timeouts + busy-vs-dead (main item)

Repo: nrfmodule-core (+ sdk header if the API surface moves).

- Per-command timeout budgets in the AT client. #XCONNECT / DNS / #XRECV-class
  commands get budgets matching the SLM-side op bound; #XRECV derives its
  budget from its own timeout argument; everything else keeps 10 s.
- Expose busy-vs-dead. `at_quarantine_link()` already sees whether late bytes
  drain after a timeout. Surface that to the link-dark consumer:
  bytes drained = busy (do not count toward dark), N silent quarantines = dead.
- Socket reconcile: after a failed #XCLOSE (-11), query `#XSOCKET?` before
  opening a new socket so flap storms cannot exhaust SLM's socket table
  (leak observed in the #64 field capture).
- Gates: core unit tests; livetracker + pigeontracker builds; bench HIL
  (scripts/hil_cycle.py) forcing a long #XRECV to prove no false dark.

### C. tracker — slim recovery (replaces #222; depends on B)

New PR. Salvage from draft #222: the abort gate (poweroff/dock ownership),
the pure-policy-file structure, the Kconfig shape, the unit tests that still
apply. Drop rung 3 entirely (reboot budget, settings persistence, wall-clock
windows) — a host reboot cannot fix a dead 9151 and the busy case is now
handled upstream.

- **Deregistration watchdog** (covers class 2): registered=0 or reject-wedged
  for N minutes while the device wants uplink → `CFUN=4` then `CFUN=1`,
  rate-limited (Nordic reset-loop restriction, nwp_042). Stationary devices
  wedge; moving ones escape — the timer must be long enough not to fire
  during normal reject storms (41 min silent window seen in the race, all
  self-recovered). Default: fire only after the storm-scale window, Kconfig.
- **Link-dark consumer, rung 1 only** (covers class 1 residue): on the SDK
  link-dark event, consult busy-vs-dead from track B. Busy → back off, never
  reset. Dead → `nrf_modem_lib_reset()` + re-attach. Pigeontracker only:
  escalate to the n91_rst line (compile-gated on the DT node) if rung 1 fails.
- Values are Kconfig with conservative defaults. Flag for Damir: dereg
  minutes, rate limit, storm-window floor. (The old #222 values are obsolete.)
- Gates: unit tests (policy file), both boards build, review agent, bench HIL
  where reachable. Live forbidden-TA repro is not bench-able; the dereg
  watchdog gets a unit-level clock test plus a bench CFUN=4 dry run.

### D. ncs-serial-modem fork — 9151 watchdog (+ owed upstream issue)

- Task watchdog on sm_work_q plus hardware WDT backstop. Design constraint:
  XSLEEP/PSM sleep must not starve the feed — feed on the suspend/resume
  hooks, or stop/rearm around sleep. A WDT reset looks like a modem reboot
  to the host; the client already handles the SLM Ready line, verify that
  path on the bench.
- File the owed upstream robustness issue (lockup forensics from the 5 ms
  DTR torture: HardFault LOCKUP, PC=0xEFFFFFFE, CFSR=0x1001).
- After merge: bump the pin in ncs-serial-modem-livetracker west.yml.
- Build recipe and bench rules: memory `project_wedge_hunt_core64` /
  `reference_serial_modem_build_recipe` (plain NCS c:\ncs\v3.2.1, env-var
  form; attach-first on the 9151).

### E. Adjacent criticals folded in (small)

- **tracker#238**: kick-vs-quiesce TOCTOU lets a drain POST race modem
  teardown during poweroff. Squarely modem stability, small fix in the
  quiesce ordering.
- **tracker#233** (BLOCKER, security): raw modem AT shell (smat/smsh) ships
  in every image over unpaired NUS. Fix: gate it to bench/HIL flavors,
  release images drop it. Product decision flagged below.
- Stretch: **tracker#235** (shutdown flush lost its fs_sync guarantee) if
  time remains.

## Sequencing

A first (tiny, independent). D in parallel (different repo, own bench).
B before C (C consumes B's busy-vs-dead API). E anytime.

## Decisions owed (HITL)

- Damir: dereg-watchdog minutes, rate limit, storm-window floor (replaces
  the old #222 value set).
- Vincent: #233 — confirm release images may drop smat/smsh (bench/HIL
  flavors keep them).
- Noted, not in this run: tracker#192 (default MCUboot signing key) is
  critical but needs a key-management decision and a fielded-device OTA
  compatibility plan; tracker#201 (spontaneous field reset) has no
  diagnosis yet.
