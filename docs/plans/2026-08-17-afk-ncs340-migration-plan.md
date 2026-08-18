# AFK run plan: NCS 3.4.0 migration (nRFModule v3.0.0)

Goal: move the platform to NCS 3.4.0 without breaking any customer or the
deployed fleet. Backward compatibility comes from branching, not from
compatibility code: v2.x freezes what works today, main moves forward.

Workspace for all of it: `c:/ncs/nrfmodule_v3x` (exists, sdk-nrf v3.4.0
fetched, toolchain v3.4.0 installed, upstream ncs-serial-modem inside).

## Phase 0: entry gate RESOLVED 2026-08-17 -> Track A (with two footnotes)

Check ran 2026-08-17 (logs: `c:/ncs/nrfmodule_v3x/build_upstream_dk_log.txt`
and `build_upstream_dk2_log.txt`; workspace's ncs-serial-modem updated to
upstream 324f651; sdk-nrf confirmed on the v3.4.0 tag).

Verdict: upstream master against the v3.4.0 RELEASE compiles the ENTIRE app
(TF-M, mcuboot, nrf_cloud CoAP, memfault, 163 steps) and fails only at the
final link. All three v3.2.1 blockers are resolved in 3.4.0.

Footnote 1 - the one remaining failure is an sdk-nrf v3.4.0 bug, not a
serial-modem problem: `nrf_cloud_codec_internal.c:3085` calls
`memfault_zephyr_port_periodic_upload_enabled()` guarded by CONFIG_MEMFAULT,
but the function only compiles under CONFIG_MEMFAULT_PERIODIC_UPLOAD, which
the app deliberately sets =n. No clean app-side fix (forcing =y trips the
app's own BUILD_ASSERT). For OUR product images this is moot: our config
fragments set CONFIG_MEMFAULT=n (we do not use memfault or nRF Cloud
observability), which never reaches the broken guard. Phase 4 must verify
that. Also: check whether an sdk-nrf 3.4.x patch release already fixes the
guard; reporting it to Nordic is a HITL option for the report.

Footnote 2 - a hard precondition found: nrfmodule-sdk's board.yml files
(beescales_bt, livetracker) fail 3.4.0's stricter board schema (missing
`full_name`), which breaks EVERY build in the workspace at configure time
(the sdk registers board_root, so Zephyr validates all its boards for any
target). One line per file; this is the FIRST item of Phase 2. Note the
workspace's sdk checkout was 2026-07-01-stale during the check; re-verify
against current main after west update (pigeontracker board defs, added to
the sdk after that date, were absent entirely).

## Ground rules for the AFK session

- No pushes to main anywhere. No tags. All work on branches + PRs.
- The v2.x freeze branches are created FIRST and never receive 3.4.0 work.
- The public SDK API stays source-compatible: v3.0.0 is a major bump because
  the NCS line changes, not because headers change. A product that built
  against v2.2.0 must compile against v3.0.0 unmodified.
- Three failed attempts at the same error = stop, write up, move to the next
  independent slice. Do not thrash.
- Anything needing hardware, tags, merges, or Damir/Vincent input goes on the
  HITL list at the end of the run report, not into improvisation.

## Phase 1: freeze v2.x (AFK, small)

1. nrfmodule-core: branch `v2.x` from current main (post-#66). Push branch.
2. nrfmodule-sdk: branch `v2.x` from current main (post-#44). Push branch.
3. manifest: branch `v2.x` from main; its west.yml already pins NCS v3.2.1 +
   sdk/core v2.2.0 tags, so it needs no edits beyond a README/CLAUDE.md note
   that this is the NCS 3.2.x maintenance line.
4. Rule recorded in CONTRIBUTING or branch note: fixes needed by both lines
   land on main first, cherry-pick to v2.x, tag v2.2.x there.

Customers on tagged pins never notice any of this.

## Phase 2: port core + sdk to NCS 3.4.0 (AFK, the meat)

Branches: `ncs340` on both core and sdk, worked inside the v3x workspace.
Follow `nrfmodule-core/docs/NCS_PORTING_GUIDE.md`.

Known risk areas, in expected order of pain:

- FIRST, from Phase 0: add `full_name:` to every board.yml under the sdk's
  board_root (3.4.0 schema requires it; without it nothing in the workspace
  configures). Run `west update` for the nrfmodule repos first - the
  workspace checkouts are 2026-07-01/16 stale.
- `lte_lc_client.cmake` compiles Nordic's lte_link_control sources directly
  with custom defines; those sources move between NCS versions. Re-derive the
  file list and defines against 3.4.0's tree.
- `sm_monitor_*` renamed-symbol URC dispatch: verify the at_monitor macro
  internals it mirrors did not change shape in 3.4.0.
- Board definitions in the sdk (livetracker, pigeontracker, 9151 boards):
  hardware-model/Kconfig drift between Zephyr versions.
- Kconfig renames and Zephyr API drift in core (PM, UART async, settings).

Gates to pass before the phase counts as done:

- All core unit suites green under the v3.4.0 toolchain (same run_test.py
  mechanism; fix the harness if the qemu platform names moved).
- sdk builds standalone (auto-detect both ways: with core present and with a
  freshly rebuilt `libmodem_core.a`).
- Quality gate (check.sh) on every touched file.
- No public header changes. If a 3.4.0 change forces one, STOP that slice and
  put it on the HITL list with the options; do not pick an API break alone.

## Phase 3: prove nRFTrackerFW compiles (AFK)

Branch `ncs340` on nRFTrackerFW. Build in the v3x workspace against the
Phase 2 core/sdk:

- livetracker release + both bench flavors, pigeontracker release.
- Tracker unit suites under the 3.4.0 toolchain.
- Fix tracker-side breakage on the branch; PR it, no main merge.
- Flavor check: `python scripts/check_flavors.py` over all built images.

Compiling and passing unit suites is the gate. Flashing is not part of the
AFK run (bench stays on the proven v2.x images).

## Phase 4: serial-modem build for the bench (AFK build, HITL verify)

Track chosen by the entry gate:

Track A applies (Phase 0 verdict). Additional Track A requirement from
footnote 1: our image configs must set `CONFIG_MEMFAULT=n` (verify the
whole nRF Cloud/memfault stack stays out of our builds; that sidesteps the
sdk-nrf link bug entirely). If a config needs memfault for some reason,
that build is blocked until the sdk-nrf guard bug is patched or fixed in a
3.4.x release.

- Track A (upstream builds on 3.4.0): branch `upstream-340` in the EXISTING
  nrfmodule/ncs-serial-modem repo (decision 2026-08-17: no new repo; push
  upstream master's history as a branch, unrelated-history is fine, master
  stays the deployed v3.2.1 fleet base). On top of it ONLY: the #XGNSS=0
  idempotent-stop patch (their code still has the bug), board overlays,
  build recipes, and a `CONFIG_SM_UART_TX_BUF_SIZE` bump (their 256 B
  default drops URC bursts while asleep). Build pigeontracker/nrf9151/ns +
  the livetracker target.
- Track B (upstream needs newer-than-3.4.0 NCS): skip the base swap. Port our
  fork as-is to 3.4.0 only if it is cheap (one session slice); otherwise the
  9151 keeps building against v3.2.1 via its own thin manifest — the modem's
  NCS pin is independent of the host SDK, nothing couples them.

Bench flashing IS in scope for the AFK run (both probes connected since
2026-08-17, EDU 801008373 on the 9151, tooling in tracker PR #258):

- Flash the built image: `python scripts/modem9151.py flash <hex>`.
- AFK smoke: RTT boot log capture (`modem9151.py rtt`), AT round-trip via
  the tracker shell, one upload cycle POST 200.
- AFK-allowed test: the E4c wedge test (smat AT#XRECV 60 s block) - it is a
  shell sequence, no sleep-state sensitivity. Requires the bench tracker
  image to be a bench flavor (smat present); flash one if needed and note it.
- NOT AFK: the sleep/delivery RI+flush test and the wake-failure rate run -
  they need the debugger-detach discipline and stay supervised, along with
  the remaining bench items from the upstream comparison report.

If a flash leaves the bench 9151 in a bad state, restore the deployed image
(fork master build) before ending the run and say so in the report.

## Phase 5: tag and ship v3.0.0 (HITL only, not this run)

Only after Vincent reviews the PRs and the bench battery passes:
core + sdk tagged v3.0.0 together, manifest main pins NCS v3.4.0 + the new
tags, Docker image rebuilt for 3.4.0, release notes. Explicitly outside the
AFK run.

## Not in this run

- tracker#248 (own track, awaiting review), fork#6/#7 on the v2.x base
  (fleet stability, separate decision), Damir's watchdog values, DevZone
  post, serial-modem#3 watchdog.

## Run report

The session ends by writing `docs/plans/2026-08-XX-afk-ncs340-report.md`:
per-phase results, every PR opened, every error class hit with its fix, the
HITL list, and honest UNVERIFIED markers on anything not proven by a passing
build or test.
