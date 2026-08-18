# AFK run report: NCS 3.4.0 migration (2026-08-17)

Executes `docs/plans/2026-08-17-afk-ncs340-migration-plan.md`. Scope change
mid-run per Vincent: nRFTracker-demo dropped as build vehicle, nRFTrackerFW
used directly.

## Entry gate verdict: Track A

Upstream ncs-serial-modem main (`324f651`) builds against the NCS v3.4.0
RELEASE for `nrf9151dk/nrf9151/ns` with one config adaptation:
`CONFIG_MEMFAULT=n`. Root cause: 3.4.0's nrf_cloud calls
`memfault_zephyr_port_periodic_upload_enabled()` whenever `CONFIG_MEMFAULT`
is on, but that function only compiles with `MEMFAULT_PERIODIC_UPLOAD`,
which upstream deliberately disables (their AT command does uploads). None
of the three v3.2.1 blockers (SB_CONFIG_MERGED_HEX_FILES, nRF Cloud client
ID source, memfault CoAP symbols) reappeared. Evidence:
`c:/ncs/nrfmodule_v3x/build_upstream_dk_memfault_off.log` (full merged.hex
produced).

## Phase 1: v2.x freeze — DONE (pushed)

The `v2.x` branches already existed on all three repos, stale. Frozen at
today's post-#66 / post-#44 mains:

- **nrfmodule-core `v2.x`**: fast-forwarded `5496382..6107bb0` (clean, main
  was strictly ahead).
- **nrfmodule-sdk `v2.x`**: merged main (branch had old merge commits plus a
  board_root change already on main); after the merge the v2.x tree is
  byte-identical to main. Pushed as `474410a`.
- **manifest `v2.x`**: merged main (brings the CI cost-diet workflows).
  west.yml conflict resolved: core/sdk pinned to their `v2.x` branches.
  **Deviation from plan**: the plan said the branch "already pins v2.2.0
  tags" — in reality main tracked `main` and v2.x pinned the flawed v2.3.0
  tags (tagged pre-fix-wave). Pinning the frozen `v2.x` branches is the
  closest correct expression until a v2.4.0 tag exists (tags are HITL).
  README + CONTRIBUTING now document the maintenance line and the
  land-on-main-first / cherry-pick / tag-v2.x.y rule (`e1c6c54`).

## Phase 2: core + sdk on NCS 3.4.0 — DONE

Branches `ncs340`, worked in `c:/ncs/nrfmodule_v3x`. PRs:

- **nrfmodule-core PR #68** — https://github.com/nrfmodule/nrfmodule-core/pull/68
- **nrfmodule-sdk PR #45** — https://github.com/nrfmodule/nrfmodule-sdk/pull/45

Error classes hit and fixes:

| Error | Fix |
|---|---|
| Zephyr 4.4 board schema requires `full_name`; every build in the workspace failed board discovery | one line per board.yml (sdk) |
| `select POSIX_TIMERS` in date_time_client.Kconfig now has unmet deps; 3.4.0 date_time uses `sys_clock_*`, not POSIX clocks | select dropped (core) |
| 3.4.0 `modem_info.c` registers its log module with an explicit `CONFIG_MODEM_INFO_LOG_LEVEL` our bypass-cmake never defined | log Kconfig template + mapped define, date_time pattern (core) |
| `nrf9151ns_laca.dtsi` renamed to `arm/nordic/nrf9151_ns_laca.dtsi` in Zephyr 4.4 | includes updated in both 9151 ns board DTS files (sdk) |
| `BOARD_QUALIFIERS` string conditions in board.cmake silently registered no runners on 4.4 → no runners.yaml → Partition Manager post-build fails | runner registration keyed on `CONFIG_SOC_*` like in-tree 4.4 boards; nrfutil runner added; 9151 J-Link device now `nRF9151_xxCA` (sdk) |
| sdk shim headers (`nrf_modem.h`, ...) shadow the real modem headers on nrf91 targets (the documented sdk#34 follow-up) | module CMake returns early on `CONFIG_SOC_SERIES_NRF91`; module Kconfig wrapped in `if !SOC_SERIES_NRF91` (sdk) |
| run_test.py hardcoded the v3.2.1 workspace | walks up to the enclosing `.west` (core) |

Gates:

- **Core unit suites: 8/8 GREEN** under the v3.4.0 toolchain
  (`sm_monitor`, `sm_at_client`, `sm_modem_power_mgmt`, `gnss_nrf91_urc`,
  `http_client`, `mqtt_e2e`, `mqtt_guard`, `mqtt_parse`), re-verified after
  the review fixes. Logs: `c:/ncs/nrfmodule_v3x/test_*_340.log`.
- **No public header changes.** The sdk diff touches boards, CMake, Kconfig
  only; the core diff touches scripts, client Kconfig/cmake only.
- **sdk auto-detect, source path**: proven by every tracker build (core
  loaded via the sdk module, compiled from source).
- **sdk auto-detect, binary path (`libmodem_core.a`): NOT RUN — UNVERIFIED.**
  The checked-in `.a` is a v3.2.1 artifact and there is no in-repo recipe to
  regenerate it; producing a 3.4.0 binary belongs to the v3.0.0 release
  flow. On the HITL list.
- **check.sh**: no C/H files were touched in core or sdk, so the gate had
  nothing to check. The one C change of the run (serial-modem
  `sm_at_gnss.c`/`sm_log.c`) follows upstream Nordic style, not house style.
- **Review agent**: ran on both diffs. 0 critical, 3 warnings, 4 style; all
  three warnings fixed (Kconfig-level nrf91 gate, configurable modem_info
  log level, positive `elseif` in board.cmake) plus the nrfutil-runner and
  docstring style items. Not taken: narrowing the nrf91 gate to only the
  five shim headers (blunt gate kept, noted as defensible when paired with
  the Kconfig gate); a "single SoC" comment in beescales board.cmake.

Useful negative results: `at_monitor.h` is byte-identical between 3.2.1 and
3.4.0 (the `sm_monitor_*` renamed-symbol dispatch needs no rework), and the
`lte_link_control` file list is unchanged (lte_lc_client.cmake needed no
re-derivation; content drift is config-compatible).

## Phase 3: nRFTrackerFW on NCS 3.4.0 — DONE

Branch `ncs340`, **PR #259** — https://github.com/nrfmodule/nRFTrackerFW/pull/259

Error classes and fixes (all config-level, zero C changes):

- `HW_ID_LIBRARY_SOURCE_BLE_MAC` renamed upstream to
  `HW_ID_LIBRARY_SOURCE_BT_DEVICE_ADDRESS` (configs/system.conf).
- The v3.4.0 Zephyr SDK **dropped newlib**; switched to picolibc with
  `PICOLIBC_IO_FLOAT=y` for float printf (configs/system.conf).
- NCS 3.4.0 **disables Partition Manager by default**; without it the build
  fell back to DTS partitions and overflowed FLASH by 10 290 bytes against
  the deployed layout. Fix: `SB_CONFIG_PARTITION_MANAGER=y` in
  sysbuild.conf, so `pm_static.yml` keeps defining the exact deployed
  layout. PM is supported for the whole 3.4 LTS; migration to DTS
  partitions is a tracked follow-up (Nordic migration guide + `pm_to_dts.py`
  exist). This keeps OTA slot compatibility untouched.
- run_test.py: `TRACKER_WEST_WORKSPACE` env override, default unchanged.

Builds, all GREEN under v3.4.0 (merged.hex each):

- livetracker release (`build_live`, pristine re-verify after all review fixes)
- pigeontracker release (`build_pt52`)
- gnss-sim bench flavor (`build_sim`)
- gnss-nrf91 bench flavor (`build_nrf91`)

**Tracker unit suites: 35/35 GREEN** under the v3.4.0 toolchain. Logs:
`c:/ncs/nrfmodule_v3x/ttest_*.log`.

**check_flavors**: livetracker release image **PASS**. Pigeontracker release
fails only `CONFIG_TRACKER_PWR_SHELL=y` — pre-existing (the current v2 build
`build_integ_pt` has the same flag; known gnss_modem.conf release-checklist
item, not a 3.4.0 regression). The two bench flavors fail the release
policy by design (they are bench flavors; the script has no bench profile).

Config drift worth knowing: `LTE_LC_MODEM_EVENTS_MODULE` lost its `default y`
in 3.4.0, but our lte_lc_client.Kconfig mirror still defaults it on —
verified `=y` in the built images, MDMEV wedge handling unaffected.

## Phase 4: serial-modem upstream-340 — BUILDS DONE, BENCH BLOCKED

Track A executed. Branch **`upstream-340`** pushed to
nrfmodule/ncs-serial-modem at upstream main `324f651` plus five commits
(no PR — the branch is the new base line, master stays the deployed fleet
base):

1. `gnss: make #XGNSS=0 idempotent` — upstream still has the
   `if (gnss_running)` gate; patch re-applied at the new path
   `app/src/sm_at_gnss.c`.
2. `app: add nrfmodule.conf` — `CONFIG_MEMFAULT=n` (the Track A link fix)
   + `CONFIG_SM_UART_TX_BUF_SIZE=1024` (256 B default drops URC bursts
   queued while the host holds the modem asleep). Build recipe in the file
   header.
3. mcuboot board overlays for pigeontracker/livetracker 9151 (DK partition
   layout, no console).
4. app-side partition overlays (provision_hex needs the s0/s1 labels in the
   app image DT; UART/DTR wiring stays in the sdk board defs).
5. b0 board overlays (same layout for the immutable bootloader image) +
   `log: keep sm_log_flush defined on console-less boards` — upstream
   latent bug: the whole `sm_log.c` body is guarded on a `zephyr,console`
   chosen node while its callers are not; console-less boards fail to link.

Builds GREEN (BOARD_ROOT = sdk ncs340, EXTRA_CONF_FILE = nrfmodule.conf):

- `pigeontracker/nrf9151/ns` → `c:/ncs/nrfmodule_v3x/build_sm_pt/merged.hex`
- `livetracker/nrf9151/ns` → `c:/ncs/nrfmodule_v3x/build_sm_lt/merged.hex`
- `nrf9151dk/nrf9151/ns` (stock, compat signal) → `build_upstream_dk`

**Bench: partially done after a J-Link restart; stopped again on a wedged
J-Link stack.** First wave: every target operation hung (readback ×2, 16-byte
memrd) — stopped after three strikes. Vincent restarted the J-Links; the
retry wave then got real work done before the stack wedged again:

- **DONE: full flash backup** of the pre-run 9151 image →
  `nRFTrackerFW/logs/bench_340/bench9151_backup_pre340.hex` (2.9 MB, the
  byte-exact restore image).
- **DONE: the upstream-340 livetracker image is ON the bench 9151** —
  erase + program + **verify** all passed, clean system reset applied
  (`build_sm_lt/merged.hex`, no-RTT variant).
- **FOUND + FIXED: the image was log-silent** — the upstream app has no RTT
  backend and our boards have no console UART, so there is nothing to
  capture. `nrfmodule.conf` on `upstream-340` now enables
  `CONFIG_LOG_BACKEND_RTT` (pushed, `c1751ea`); the RTT-enabled rebuild is
  ready at `c:/ncs/nrfmodule_v3x/build_sm_lt/merged.hex` but is NOT yet
  flashed (the re-flash hung at probe connect; killed before it touched
  anything — no progress output ever appeared).
- **The bench tracker 52840 was never written.** `smat` is missing from its
  release image, so the plan's bench-flavor flash was attempted; the v2.x
  gnss-nrf91 image built fine (`nRFTrackerFW/build_nrf91/merged.hex`) but
  both flash attempts failed up-front: probe **823001117 is absent from
  Windows USB** (only the EDU probe enumerates as a USB device;
  `nrfjprog --ids` listing both is stale cache). Nothing was programmed.
- Concurrent flashes on the two probes wedge the J-Link GUI server —
  everything after that hangs until processes are killed. By the end even
  the EDU probe refused connections ("Unable to connect to a debugger",
  JLinkARM DLL open errors). This host's J-Link stack needs a
  replug/reboot. Matches the old "bench USB degraded" note.

**Bench wave 3 (Vincent flashed the 9151 RTT image manually and disabled
the EDU probe; 52840 work continued over its own probe + COM58):**

The new modem base is PROVEN on the bench, against the v2.x tracker:

- Boot + registration: CEREG 5 (roaming), PSM granted (TAU 3600 s,
  active 0 s), ICCID 89882280000055861997 read, mfw_nrf91x1_2.0.4.
- GNSS: #XGNSS sessions start/stop cleanly through the tracker's
  gnss_nrf91_slm driver (RRC-blocked handling working).
- Upload cycle: config GET → 200 and data POST → 200 (368 B body),
  7 records drained (captured log).
- Wake path: modem wakes from IDLE on attempt 1 (RI processed), smat AT
  round-trips OK, AT+CGMR answers over the bridge.
- **E4c wedge test: PASS.** `AT#XSOCKET=1,1,0` → `AT#XCONNECT=1,
  "ta.avirings.com",80` (upstream syntax: handle first) → `AT#XRECV=1,0,0,60`
  blocks the AT channel the full 60 s; after expiry `smat AT` → OK and
  `modem status` shows registered=yes, PSM intact. No wedge. The deployed
  fleet FW wedges permanently on this sequence. Test sockets closed
  (#XCLOSE) afterwards.

**3.4.0 tracker boot bug: FOUND, ROOT-CAUSED, FIXED (`bda1a2e`).** The
first flash of the 3.4.0 tracker did not boot: no USB, no RTT, no shell.
Diagnosis chain: JLink halt put the PC at MCUboot `main.c:944` = the
`FIH_PANIC` after a failed `boot_go`; a stack walk confirmed the
single-threaded init path; rebuilding the MCUboot image with RTT logging
booted the device — and the only functional delta in that build was
`CONFIG_MAIN_STACK_SIZE=4096`. A/B confirmed: the stack bump alone (no
logging) takes the image from dead to fully booted. **Root cause: ECDSA
P-256 verification via the NCS 3.4.0 PSA / Mbed TLS 4.1 crypto backend
overflows MCUboot's old 2048-byte main stack** (the 3.2.1-era comment
"2048 is sufficient for ECDSA-P256" no longer holds; `BOOT_ECDSA_CC310`
is deprecated in 3.4.0). The overflow corrupts boot state and MCUboot
dies in FIH_PANIC with zero output — a silent brick. Fix committed on the
tracker ncs340 branch (sysbuild/mcuboot.conf, stack 4096) and noted on PR
#259: **any 3.4.0 product build keeping an old MCUboot stack size will
hit the same failure.**

**3.4.0 end-to-end on hardware: VERIFIED.** With the fix, the 3.4.0
gnss-nrf91 tracker image (rebuilt from the committed default config)
boots on the bench: Zephyr 4.4.0 banner, CDC shell on COM58, dock
override applied, LTE registered (roaming) with PSM granted (TAU 3600 s),
ICCID read, `smat AT` round-trip OK — all against the 9151 running the
serial-modem upstream-340 base. All four tracker images were rebuilt
green from the fixed branch.

Bench end state: 52840 runs the **3.4.0 gnss-nrf91 bench image** (the
committed config), 9151 runs upstream-340 with RTT. Byte-exact pre-run
9151 backup at `nRFTrackerFW/logs/bench_340/bench9151_backup_pre340.hex`;
tonight's v2.x bench-flavor hex remains at
`nRFTrackerFW/build_nrf91/merged.hex` if a rollback is wanted.

Still UNVERIFIED: 9151 RTT boot-log capture (image runs, capture not
taken); the supervised battery items (RI/flush, wake-rate).

## Late desk findings (evening, pre-bench for 08-18)

- **core#30 closed on the PR**: `pdn_client.cmake` referenced `nrf/lib/pdn`,
  removed in 3.4.0. The deprecated NRFMODULE_PDN path now fails the build
  with a pointer to `LTE_LC_PDN_MODULE` (`62ef902`).
- **Fix URC rename caught at the desk (`2cf6882`)**: the upstream
  serial-modem base emits fixes as `#XGNSSPOS: <payload>` instead of the
  fork's `#XGNSS: <payload>`. Status URCs were unchanged, so bench sessions
  looked healthy while no fix could ever have been delivered — tomorrow's
  outdoor test would have failed mysteriously. Parser accepts both
  prefixes, monitor filter widened to the `#XGNSS` stem; URC unit suite
  21/21 green under v3.4.0; the bench 52840 now runs the updated image.
- **tracker#244 (sats/hdop always 0)**: the upstream fix URC also carries
  no satellite count or DOP; noted on the issue — the fix is dropping the
  dead fields from the tracker log line, not populating them.

## Bench checklist for 2026-08-18

Board state on arrival: 52840 = 3.4.0 gnss-nrf91 bench image incl. the
#XGNSSPOS parser (shell on COM58, `dock override on` needed after boot);
9151 = upstream-340 RTT variant.

1. **Outdoor/window-sill GPS fix on 3.4.0 + upstream-340** — first real
   fix through the renamed URC; confirm `gnss_producer` publishes and a
   record uploads. This also feeds tracker#254/#257 evaluation.
2. **RTT boot-log capture from the 9151** (`modem9151.py rtt`) — last
   unticked AFK smoke item.
3. **Supervised sleep/delivery test** (fork#6/#7 acceptance on the new
   base): mid-window auto-sleep, count spontaneous RI assertions and
   malformed #XGNSS lines. Race A/B criteria: spontaneous RI > 0,
   malformed = 0.
4. **Wake-failure rate run** (~50 sleep/wake cycles, probe DETACHED;
   baselines 0/63 old FW, 16/736 fork rework) — tracker#255 evidence.
5. **CTS-stall-across-XSLEEP torture** — flagged as the most important
   upstream-evaluation item in the base-decision report.
6. **Pigeontracker PCB**: flash `build_sm_pt/merged.hex` (9151) and
   `build_pt52/merged.hex` (52840) if a board is available — both are
   compile-only so far.
7. If GNSS windows still truncate at 30 s (tracker#254): the auto-sleep
   interplay is unchanged on the new base; gather one RTT trace.

## Not done / explicitly out

- Phase 5 (tags, manifest main pin, Docker image, release notes) — HITL by
  design. The manifest branch `feature/ncs-3.4.0-migration` already exists
  (pins sdk-nrf v3.4.0) and will need its core/sdk/serial-modem pins set at
  ship time.
- tracker#248, fork#6/#7 on the v2.x base, Damir watchdog values, DevZone
  post, serial-modem#3 — out of scope per plan.

## HITL list (needs Vincent)

1. **Manual bench flash** (Vincent took this over; J-Link stack on the host
   needs a replug/reboot first, probe 823001117 is off the USB bus):
   - 9151 (probe 801008373): `c:/ncs/nrfmodule_v3x/build_sm_lt/merged.hex`
     (RTT-enabled upstream-340; the 9151 currently runs the same build
     without RTT, already verified on-target).
   - 52840 (probe 823001117):
     `d:/Root/nrfmodule_workspace/nRFTrackerFW/build_nrf91/merged.hex`
     (v2.x gnss-nrf91 bench flavor, has `smat`).
   - Restore image (byte-exact pre-run 9151 readback):
     `d:/Root/nrfmodule_workspace/nRFTrackerFW/logs/bench_340/bench9151_backup_pre340.hex`.
   - Then the smoke: `modem9151.py rtt --seconds 35` boot capture → `smat
     AT` round-trip → one upload POST 200 → E4c wedge test
     (`smat AT#XRECV` 60 s block).
2. **Review + merge** core#68, sdk#45, tracker#259 (all suites/builds green;
   diffs small and config-heavy).
3. **v2.4.0 tags** on core/sdk `v2.x` (frozen at post-#66/#44) so the
   manifest v2.x can pin tags instead of branches; then re-check the
   manifest v2.x pin comment.
4. **Supervised bench battery** (unchanged from the plan): sleep/delivery
   RI+flush test, wake-failure rate run (debugger-detach discipline), plus
   the remaining upstream-comparison bench items.
5. **DTS-partition migration** for the tracker (before the post-LTS NCS
   line; PM keeps working through 3.4 LTS).
6. Damir's watchdog values (unchanged, parked).

Dropped per Vincent: libmodem_core.a regeneration (future thing, revisit at
v3.0.0 release if the binary distribution path is needed).

## Build environment notes (for whoever repeats this)

- Workspace `c:/ncs/nrfmodule_v3x`, toolchain v3.4.0 via
  `nrfutil toolchain-manager launch --ncs-version v3.4.0 --`.
- west crashes on cross-drive app paths (app on d:, workspace on C:) — copy
  the app under `c:/ncs/nrfmodule_v3x/apps/`.
- Quote whole `-D` defines with drive-letter paths
  (`"-DBOARD_ROOT=c:/..."`) or the launcher splits them at the colon.
- Tracker clone for this line: `c:/ncs/nrfmodule_v3x/apps/nRFTrackerFW`
  (branch ncs340); serial-modem work clone in the session scratchpad,
  branch pushed.
