# Engineering playbook — TDD, HIL, and the quality gate

How to get fast, trustworthy feedback on an embedded firmware project, and how
to recreate this setup on a new project (Zephyr or otherwise). Three loops,
fastest first:

| Loop | Catches | Speed | Hardware? |
|------|---------|-------|-----------|
| **Quality gate** (lint) | style + house rules, AI attribution | instant | no |
| **Unit tests** (TDD) | logic / state-machine correctness | seconds | no |
| **HIL** (serial) | real-hardware behaviour, timing, integration | minutes | yes |

The discipline: push each class of bug to the fastest loop that can catch it.
Whitespace → lint. Logic → a unit test. "Does the modem actually wake?" → HIL.

---

## 1. Quality gate (lint + house rules)

Built once in the manifest, reused everywhere. Full details in
[`tooling/README.md`](../tooling/README.md). In short:

- **Enforced** (fails the gate): `#ifdef CONFIG_` → `#if defined()`, parenthesised
  numeric `#define`s, no AI attribution in commits.
- **Advisory** (reports, never reformats): clang-format drift vs. the canonical
  Zephyr style — we hand-align tables/cases deliberately, so it informs, it
  doesn't enforce.
- **Triggers, shift-left:** a global `~/.claude` PostToolUse hook (in-session
  feedback to agents) → pre-commit hook → CI `reusable-lint.yml` (the
  un-bypassable backstop).

Run it: `bash tooling/check.sh --range origin/main..HEAD` (or `--all`, or staged).

---

## 2. TDD — unit tests

### The pattern that makes firmware testable

Separate **policy (pure logic)** from **mechanism (hardware/OS)**. The pure core
takes its dependencies through a struct of function pointers; production wires
them to real drivers, tests wire them to fakes. Examples in this ecosystem:
`sync_policy`/`sync_engine` (clock + transport injected), `sampler` (gps/clock
injected). A pure core with injected deps is unit-testable with a fake clock and
needs no board.

### Zephyr (ztest)

- One suite per dir: `tests/unit/<name>/` with `CMakeLists.txt`, `prj.conf`,
  `testcase.yaml`, `src/main.c` (the `ZTEST`s).
- Run a suite:
  ```bash
  nrfutil toolchain-manager launch --ncs-version v3.2.1 -- \
      python scripts/run_test.py tests/unit/<name>
  ```
  (`run_test.py` is a thin wrapper around `west build -b qemu_cortex_m0 … && west build -t run`.)
- **Gotchas:** `native_sim` is Linux-only on NCS → target `qemu_cortex_m0` (with a
  small overlay); avoid threads/workqueues *in the code under test* (test the pure
  core, not the thread); wipe `build_test/` (or `--pristine`) when switching suites.

### Test-first habit

Write the failing test from the spec, watch it fail, write the minimal code to
pass, refactor. The payoff compounds: every state-machine/cadence/edge-case bug
becomes a 2-second test instead of a 5-minute HIL cycle.

---

## 3. HIL — the serial feedback loop

The core idea: **expose state and commands over a serial console, then drive and
observe the board from a script.** With a Zephyr shell this is nearly free.

### Build the firmware to be drivable

Add shell commands that *drive* and *observe* state, e.g. `sm event begin <t>`,
`params set send_int 10`, `data_queue status`, `modem status`, `transport test`.
Output `key=value` lines so scripts can parse them. Keep these behind a HIL
config fragment so they drop from production.

### The script primitives (reference: `nRFTrackerFW/scripts/`)

- **`hil_shell.py`** — open the port, send command(s), read the response.
  A `ShellHelper` does `wake()` → `cmd()` → parse `key=value`. `--monitor N`
  passively dumps UART for N seconds (watch async logs after triggering an event).
- **`hil_flash.py`** — `west build` + `west flash` (sets `ZEPHYR_BASE` so it works
  from outside the workspace).
- **`hil_cycle.py`** — the reliable autonomous primitive:
  build → flash → **force `kernel reboot cold`** → confirm a fresh boot (uptime
  reset). Why force the reboot: `west flash`'s post-program reset is intermittent
  on many boards, so without it you can verify *stale* firmware.

### The loop in practice

1. `hil_cycle.py --port COMx` — flash + guaranteed fresh boot.
2. Drive a scenario via shell commands; `--monitor` to capture the async result.
3. Assert on the `key=value` / queue counts / log lines.

This is how the modem-wake bug was found: drive a drain, watch the wake fail in
the log, form a hypothesis, fix, re-cycle, confirm the queue drains.

---

## 4. Recreating this on another project

### Generic Zephyr project (no nrfmodule manifest)

Almost everything transfers:

- **Quality gate:** copy `tooling/`, or set `NRFMODULE_TOOLING` to point at it.
  The checks are plain bash; `.clang-format` is portable. For CI, copy the
  `reusable-lint.yml` pattern (or call it cross-repo). For the agent hook, add the
  repo path to `~/.claude/nrfmodule-roots.txt`.
- **TDD:** ztest/twister is upstream Zephyr — identical. Copy `run_test.py`.
- **HIL:** the `hil_*.py` scripts are project-agnostic except `DEFAULT_BOARD` and
  the port — copy and set those.

The only manifest dependency is *where the tooling lives*; nothing about the
checks, tests, or HIL needs the manifest.

### PlatformIO / Arduino (or any non-Zephyr C/C++)

Reusable as a **pattern**, with concrete swaps:

| Layer | Swap |
|-------|------|
| clang-format + `paren-numeric-defines` + `no-ai-attribution` | **transfer as-is** (it's C/C++) |
| `no-ifdef-config`, checkpatch | **drop** — Zephyr/Kconfig-specific |
| Unit tests | **Unity / `pio test`** instead of ztest — same "pure core + injected deps" pattern, native + on-target |
| HIL serial loop | **keep the script pattern** (`hil_shell.py` parses any serial protocol); expose an Arduino **command parser** over `Serial` instead of the Zephyr shell |
| Flash | `pio run -t upload` instead of `west flash` |
| CI | the PlatformIO GitHub Action instead of the Docker/west image |

The two ideas that carry across every platform: **pure-core-with-injected-deps**
(makes logic unit-testable anywhere) and **drive-the-board-over-serial** (makes
hardware behaviour scriptable anywhere there's a serial console). The harnesses
differ; the discipline doesn't.

---

## TL;DR for a new project

1. Drop in `.clang-format` + the rule checks; wire the pre-commit hook and a CI
   lint job. Prune Zephyr-specific rules if not Zephyr.
2. Structure new modules as pure core + injected deps; write the test first.
3. Give the firmware a serial command/observe surface; copy the `hil_*.py`
   primitives and set the board/port.
