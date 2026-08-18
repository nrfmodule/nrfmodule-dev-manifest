# NCS Upgrade Playbook

Intended home: `nrfmodule-core/docs/NCS_UPGRADE_PLAYBOOK.md`.

**Relationship to `NCS_PORTING_GUIDE.md`:** this playbook **supersedes** it. The porting guide was audited 2026-07-06: its core-repo steps (sm_at_client re-vendor, symbol renames, lte_lc Kconfig/cmake sync, AT_MONITOR bridge) are accurate but incomplete — it says "copy updated files" where reality requires a three-way merge (our copy has diverged), and it covers none of the manifest, Docker/CI, SDK-board, binary-artifact, or tagging work where upgrades actually fail. Its per-library detail is absorbed below (Phase 3). After this file lands in nrfmodule-core, reduce `NCS_PORTING_GUIDE.md` to a pointer at this document (keep the "Version-Specific Notes" section, appended per release).

Companion: `ncs-seam-inventory.md` (same audit) — seam IDs (S1–S13) referenced throughout. Read it once before the first execution; after that this playbook is self-contained.

Conventions: `OLD` = current NCS pin (e.g. v3.2.1), `NEW` = target pin (e.g. v3.4.0). Every step ends in a checkable predicate. Never push to `main` in any repo; every repo change is a feature branch + PR. No step is optional unless marked.

---

## Phase 0 — Preconditions (do these BEFORE touching any pin)

- [ ] **0.1 Tag the pre-bump line.** If core/sdk carry unreleased changes (they do as of 2026-07: everything since v2.2.0), tag **v2.3.0** on core+sdk first, per the release convention (tag both together; manifest `v2.x` branch gets pinned revisions; manifest `main` keeps `revision: main`; update CLAUDE.md pins). *Predicate:* `git tag --contains` shows a tag on both repos' current main; a fresh `west init` from manifest `v2.x` builds the tracker app. Rationale: the bump needs a known-good line to bisect against and to hotfix customers from.
- [ ] **0.2 Fix the CI harness so green means something.** `manifest/.github/workflows/reusable-ci.yml` must `west init` from `nrfmodule/nrfmodule-dev-manifest` (not `V1incentC/test-premium-manifest`) and swap PR code into `modules/lib/nrfmodule-core` (not `test-modem-source`). Add a `west list` echo step. *Predicate:* a no-op core PR runs twister against the manifest's real NCS pin, visible in the log.
- [ ] **0.3 Pin `ncs-serial-modem` in `west.yml`.** Change `revision: main` to the exact commit/tag matching the deployed modem FW line (currently `448cf99`; after the SLM migration, the chosen release tag). *Predicate:* `west update` is reproducible; `west list` shows the SHA.
- [ ] **0.4 Reconcile the livetracker nrf9151 board defs** (S11): fold the deployed `livetracker.overlay` truth (921600, `hw-flow-control`, RTS=P0.09/CTS=P0.12, DTR P0.31 PULL_DOWN|ACTIVE_HIGH, RI P0.30 ACTIVE_LOW, `ncs,sm-uart = &dtr_uart2`) into `livetracker_nrf9151_ns.dts` + pinctrl. Otherwise Phase 6 HIL cannot use SDK boards. *Predicate:* modem FW built with the SDK board talks to the tracker on the bench.
- [ ] **0.5 Snapshot baselines.** Record: `west list` output, all product `.config`s of interest, HIL pass results on OLD, current `libmodem_core.a` provenance (core SHA + NCS pin it was built from). *Predicate:* a `docs/audits/<date>/baseline.md` exists.

Steps 0.2–0.4 are one-time repairs; on later executions just verify them.

## Phase 1 — Intelligence pass (no code changes)

- [ ] **1.1 Read Nordic's migration guides for every version crossed** (e.g. OLD=3.2.1 → NEW=3.4.0 means the 3.3.0 *and* 3.4.0 guides), plus release notes "Modem libraries" and "Libraries for networking" sections, plus the nrf_modem CHANGELOG. Extract items touching: lte_link_control, at_monitor/at_parser, date_time, modem_info, modem_key_mgmt, pdn, nrf_modem_lib, Zephyr networking types, Partition Manager, TF-M, MCUboot.
- [ ] **1.2 Note the Zephyr delta** (`zephyr/VERSION` at both pins) and the **Zephyr SDK requirement** (`zephyr/SDK_VERSION` at both pins). 3.2.1→3.4.0: Zephyr 4.2.99→4.4.0, Zephyr SDK 0.17.4→**1.0.1** (Docker rebuild mandatory).
- [ ] **1.3 Build the diff pack.** In a scratch dir, sparse-clone NEW (`git clone --depth 1 --filter=blob:none --sparse -b <NEW> https://github.com/nrfconnect/sdk-nrf && git sparse-checkout set lib include/modem`) and produce diffs vs the OLD workspace copy for: `lib/lte_link_control` (all files), `lib/{date_time,modem_info,modem_key_mgmt,at_monitor,at_parser}`, `include/modem/*.h` that our code or products include, and `nrfxlib/nrf_modem/include/nrf_modem_at.h` (+ any other forked header's upstream twin). *Predicate:* diff pack saved; every file-level add/remove/rename in `lte_link_control` is listed.
- [ ] **1.4 Grep the NEW sources for API calls our emulation must provide:** `grep -rhoE 'nrf_modem_at_[a-z_]+|nrf_modem_lib_[a-z_]+' <NEW>/lib/{lte_link_control,date_time,modem_info,modem_key_mgmt} | sort -u`, compare against symbols defined in `nrf_modem_at.c`/`nrf_modem_lib.c` and declared in the SDK header forks. *Predicate:* zero unimplemented symbols, or a work list.
- [ ] **1.5 Decide version line** (S12): patch-level NCS bump → next minor on current line; NCS minor jump (3.2→3.4) → decide v2.x+1 minor vs new v3.x line and record it in the bump PR description.

## Phase 2 — Scratch workspace on NEW

- [ ] **2.1** Create a *separate* workspace (do not touch `c:/ncs/nrfmodule_<OLD>`): `west init -m <manifest fork/branch with sdk-nrf revision: NEW>`, `west update`. Keep `sdk-nrf` **first** in `west.yml` with `import: true`; nrfmodule-sdk keeps `import: true`; core does not (S9). *Predicate:* `west list` shows NEW for nrf/zephyr/nrfxlib; `modules/lib/nrfmodule-{core,sdk}` present at expected paths.
- [ ] **2.2** Baseline-configure the primary product (nRFTrackerFW livetracker/nrf52840) with **no source changes** and record the failure list — this is the work queue for Phase 3/4. *Predicate:* failure list captured (a clean build here is suspicious — check S8's `[nrfmodule]` CMake status line to confirm source-mode, not silent BLE-only).

## Phase 3 — nrfmodule-core changes (branch: `chore/ncs-<NEW>`)

Order matters: Kconfig before cmake before vendored code, so each build failure is attributable.

- [ ] **3.1 Kconfig mirror sync (S3).** Apply the upstream `lte_link_control/Kconfig` OLD→NEW delta to `src/client/lte_lc_client.Kconfig`: add new options (3.4: `LTE_LOCK_BAND_LIST`), mirror default changes (3.4: `LTE_LC_MODEM_EVENTS_MODULE` loses `default y`; `LTE_LOCK_BAND_MASK` loses its default), drop removed options. Never mirror choice symbols defined in Nordic's file (`LTE_LC_PDN_DEFAULT_FAM_*`, `LTE_LC_PDN_DEFAULT_AUTH_*`). Repeat for `date_time_client.Kconfig`, `modem_info_client.Kconfig`, `modem_key_mgmt_client.Kconfig` against their upstream Kconfigs. *Predicate:* Kconfig phase of a build emits no undefined-symbol or choice warnings.
- [ ] **3.2 CMake mirror sync (S2, S6).** Apply upstream `lte_link_control/{CMakeLists.txt,modules/CMakeLists.txt,common/CMakeLists.txt}` deltas to `lte_lc_client.cmake`: every added source appears (with the same `_ifdef` condition), every removed source is dropped, and unconditional entries match upstream's condition model (fix the current drift: `cereg/cfun/cscon/mdmev/xsystemmode` should follow upstream's `LTE_LC_*_MODULE` conditions; add `cellular_profile.c` under `LTE_LC_CELLULAR_PROFILE_MODULE`). Same pass over `date_time_client.cmake`, `modem_info_client.cmake`, `modem_key_mgmt_client.cmake`: verify file lists and that every `CONFIG_*` macro the NEW sources consume is covered by a compile-definition mapping (`grep -rhoE 'CONFIG_[A-Z0-9_]+' <NEW>/lib/<lib>/*.c | sort -u` vs the cmake). *Predicate:* configure completes; link has no undefined references from these libs.
- [ ] **3.3 PDN tombstone (3.4-specific; general rule: removed upstream libs).** `nrf/lib/pdn` is gone in 3.4. Replace `pdn_client.cmake`'s body with a hard `message(FATAL_ERROR "NRFMODULE_PDN was removed with NCS 3.4; use LTE_LC_PDN_MODULE")` under `if(CONFIG_NRFMODULE_PDN)`, and mark the Kconfig option accordingly. *Predicate:* enabling `NRFMODULE_PDN` fails loudly with guidance; default builds unaffected.
- [ ] **3.4 Vendored sm_at_client merge (S1) — three-way merge, not copy.** Compute `git diff <old-sm-pin>..<new-sm-pin> -- lib/sm_at_client include/sm_at_client.h` in an ncs-serial-modem clone and apply it onto `src/serial_modem_client/sm_at_client.c` + `nrfmodule-sdk/include/sm_at_client.h`, preserving our local divergence (renamed Kconfig symbols, `sm_monitor_dispatch` hook, DTR polarity/sense handling, shell additions). Known pending upstream fixes to take regardless of NCS bump: bounds clamp in `response_handler`, `RX_ENABLED` clear on `UART_RX_DISABLED`, `-EBUSY` tolerance in `rx_enable()`, line-complete gate before URC dispatch. If upstream renamed APIs (`configure_dtr_uart` → `automatic_dtr_uart`), decide adopt-vs-keep and update `nrf_modem_at.c` + SDK header consistently. Preserve: multi-URC newline splitting, AT_MONITOR bridge, `sm_monitor_*` symbol names. *Predicate:* link clean (no `at_monitor_heap` duplicate); unit/HIL URC tests pass (Phase 6).
- [ ] **3.5 Monitor bridge check (S5).** Diff upstream `lib/at_monitor/at_monitor.c` + `include/modem/at_monitor.h` OLD→NEW. If `struct at_monitor_entry` or its section changed, adapt the bridge loops in `sm_at_client_monitor.c`. *Predicate:* bridge compiles; `STRUCT_SECTION_FOREACH(at_monitor_entry, ...)` still iterates real entries (checked at runtime in Phase 6).
- [ ] **3.6 Emulation surface (S4).** From the 1.4 grep: implement/stub any newly-required `nrf_modem_at_*`/`nrf_modem_lib_*` symbols in `src/client/nrf_modem_at.c`/`nrf_modem_lib.c` and reconcile the SDK header forks (`nrfmodule-sdk/include/nrf_modem_at.h`, `nrf_modem_lib.h`, `nrf_modem.h`, `nrf_socket.h`) against their upstream twins — take doc/annotation changes, evaluate semantic ones (e.g. `nrf_modem_at_cfun_handler_set`). Check `nrfmodule-sdk/zephyr/linker_data.ld` section names still match the macros in the (possibly updated) `nrf_modem_lib.h` fork. *Predicate:* link clean; CFUN hook fires at runtime.
- [ ] **3.7 Zephyr-API sweep (S13).** Build with all optional features on (`NRFMODULE_BLE_LOG_BACKEND`, GNSS drivers, MQTT, HTTP, power mgmt) and fix Zephyr 4.x API drift (`net_in_addr`, `zsock_*`, log-backend API, PM device semantics). *Predicate:* full-feature build clean, no deprecation warnings we don't understand.

## Phase 4 — nrfmodule-sdk changes (branch: `chore/ncs-<NEW>`)

- [ ] **4.1 Boards (S11).** Build every board target (`livetracker/nrf52840`, `livetracker/nrf9151/ns`, `beescales_bt/nrf52840`) against NEW; fix DTS/partition/TF-M fallout (3.3+: Partition Manager deprecation warnings — plan the PM→DTS move for nRF91 targets; TF-M default profile change). *Predicate:* all board targets configure + compile a minimal app.
- [ ] **4.2 Vendored BMP390** vs upstream Zephyr bmp388 drift: re-diff, re-apply the TURN_ON re-init delta if upstream moved. *Predicate:* sensor build + SDK unit tests pass.
- [ ] **4.3 SDK default manifest.** Update `nrfmodule-sdk/west.yml` `sdk-nrf` revision (currently stale at v3.1.1) to NEW so customers initing from the SDK get the tested NCS. *Predicate:* fresh `west init -m <sdk repo>` resolves NEW.
- [ ] **4.4 Regenerate `lib/libmodem_core.a` (S8/S12)** from the core branch built against NEW, and record provenance (core SHA + NCS pin) in the commit message. Then run the **binary-mode build**: temporarily remove core from a scratch workspace, build a modem product, confirm `[nrfmodule] Source missing. Linking PUBLIC BINARY` and a clean link + boot. *Predicate:* binary-mode build boots and passes an AT smoke test.

## Phase 5 — Manifest changes (branch: `feature/ncs-<NEW>`)

- [ ] **5.1 west.yml:** `sdk-nrf` revision → NEW (stays first, `import: true`); `ncs-serial-modem` pin → the release matching the modem FW being deployed alongside (see migration plan); comments updated. *Predicate:* fresh init/update reproduces the scratch workspace of Phase 2.
- [ ] **5.2 Docker (S10):** update `infra/docker/Dockerfile` — `ZSDK_VERSION` per 1.2 (3.4: **1.0.1**; note the sdk-ng release URL/naming may change for 1.x), `west init --mr <NEW>` for Python requirements, bump nrf-command-line-tools if release notes require. Update `publish-docker.yml` tag (`ncs-v<NEW>`). *Predicate:* `docker build` succeeds; inside the container: `west init -m <manifest> && west update && west twister -T modules/lib/nrfmodule-core/tests --integration` passes.
- [ ] **5.3 CI:** confirm 0.2's fixed `reusable-ci.yml` points at the bumped manifest branch during the PR (temporary `west init -m … --mr feature/ncs-<NEW>` or equivalent), and restore to `main` after merge. *Predicate:* core CI on the bump PR runs against NEW and passes.
- [ ] **5.4 CLAUDE.md / README:** update pins, versions, and the "Current pins" line. *Predicate:* grep for the OLD version string finds only changelog/history references.

## Phase 6 — Verification matrix (gates the merge)

Build gates (all in the NEW workspace):
- [ ] nRFTrackerFW `livetracker/nrf52840` full-feature build, plus its unit suite (`scripts/run_test.py tests/unit/*` under the NEW toolchain).
- [ ] Product-template build via `reusable-build.yml` path (`west init -l application`).
- [ ] SDK unit tests (`tests/led_effect`, `tests/led_arbiter` on qemu) + core twister (`tests/modem_say_hello`, qemu_cortex_m3).
- [ ] Binary-mode build (4.4).
- [ ] Modem FW build from the serial-modem pin with the SDK nrf9151/ns board (0.4).

HIL gates (bench, deployed-config UART 921600+HWFC) — each maps to a seam:
- [ ] Boot: "Ready" URC detected, `nrf_modem_lib_init()`==0 (S4/S7).
- [ ] AT round-trip + response parsing, CME/CMS error encoding spot-check (S4).
- [ ] URC dispatch: `+CEREG` → lte_lc callback; `%XTIME` → date_time; multi-URC single buffer split; both SM_MONITOR and AT_MONITOR paths (S1/S5).
- [ ] LTE attach: `lte_lc_connect_async()` → `LTE_LC_EVT_NW_REG_STATUS` registered; PSM/eDRX request paths used by the product (S2/S3).
- [ ] Sleep/wake: XSLEEP=2 → RI/DTR wake (attempt count logged), no -EAGAIN storm (S1/S7 — semantics change with SLM v2: RI is level-triggered).
- [ ] Data path: MQTT connect/pub/sub or HTTP GET per product usage — `#XRECV` framing check (S7).
- [ ] Cert write/read via modem_key_mgmt (S6).
- [ ] Power floor: sleep-current within the product's budget (regression vs baseline 0.5).

## Phase 7 — Merge, tag, release (S12)

- [ ] **7.1** Merge order: core → sdk → manifest (manifest PR last so its pins reference merged SHAs; CI on each uses the temporarily-pointed harness from 5.3).
- [ ] **7.2** Tag core+sdk with the version decided in 1.5; regenerate/verify `libmodem_core.a` provenance matches the tag.
- [ ] **7.3** Manifest: on the release branch (`v2.x` or new line), set `west.yml` to the tags, commit, tag, push branch+tag; `main` keeps `revision: main` with updated comments.
- [ ] **7.4** Update `NCS_PORTING_GUIDE.md` "Version-Specific Notes" with what actually bit during this bump; file issues for anything deferred.
- [ ] **7.5** Notify/upgrade dependent repos (nRFTrackerFW, Waggi, BeeScales, product-template) — each re-inits its workspace; their CI must go green before the old workspace is deleted.

Rollback: at any phase before 7.2, abandon branches; workspaces are separate so the OLD environment is untouched. After 7.3, rollback = repoint `v2.x` pins at the previous tags (the reason 0.1 exists).
