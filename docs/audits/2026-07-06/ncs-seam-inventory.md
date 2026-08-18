# NCS Seam Inventory — nrfmodule-core / nrfmodule-sdk / manifest

Audit date: 2026-07-06. Workspace: NCS v3.2.1 (`c:/ncs/nrfmodule_v3.2.1`), core/sdk on `main` (past v2.2.0, untagged — pending v2.3.0).

A **seam** is any point where our code touches NCS *internals* (source files, Kconfig trees, linker sections, wire protocols, path layouts) rather than stable public APIs. Each entry states: what it touches upstream, how an NCS bump breaks it, and the verification that proves it survived.

Severity legend: **[S]** silent breakage possible, **[V]** breaks visibly (compile/link/configure error), **[R]** runtime-only breakage (needs HIL).

---

## S1. Vendored `sm_at_client` copy — [S][R]

**Where:** `nrfmodule-core/src/serial_modem_client/{sm_at_client.c, sm_at_client_monitor.c, sm_at_client_monitor.ld, CMakeLists.txt, Kconfig}`; public header fork in `nrfmodule-sdk/include/sm_at_client.h`.

**Touches upstream:** `ncs-serial-modem/lib/sm_at_client/sm_at_client.c` + `include/sm_at_client.h` — copied, then diverged: Kconfig namespace renamed (`SM_AT_CLIENT_*` → `NRFMODULE_SM_AT_CLIENT_*`), monitor symbols renamed (`at_monitor_{heap,fifo,work}` → `sm_monitor_*`), monitor rewritten with newline URC-splitting + AT_MONITOR bridge, DTR/RI GPIO handling extended (sense config, uninit, polarity).

**How a bump breaks it:** upstream fixes silently don't flow. Already behind as of upstream HEAD (2ee3a42):
- `d915d10` clamp copy length to remaining buffer (bounds-safety in `response_handler`) — our copy still has the unclamped `memcpy` + `assert`.
- `f34c54a` clear `RX_ENABLED` bit in `UART_RX_DISABLED` event + `-EBUSY` tolerance in `rx_enable()` — our copy lacks both (RX recovery can wedge).
- Upstream now defers `sm_monitor_dispatch()` until the buffer ends in `\r\n` (complete line); our copy dispatches partial buffers — this is exactly our URC-contamination bug class.
- Upstream API rename: `sm_at_client_configure_dtr_uart(bool, timeout)` → `sm_at_client_automatic_dtr_uart(timeout)`; a naive re-vendor breaks `nrf_modem_at.c` and the SDK header.
A re-vendor is a **three-way merge** (upstream-old → upstream-new applied onto our diverged copy), never a copy — the porting guide's "copy updated files" instruction understates this.

**Verification:** `west build -b livetracker/nrf52840 <app>` links clean (no duplicate `at_monitor_heap`); HIL: AT round-trip, multi-URC burst dispatch (`+CEREG` and `%XTIME` in one RX buffer reach separate handlers), XSLEEP=2 sleep→RI/DTR wake cycle, `smsh uart auto` path.

---

## S2. `lte_lc_client.cmake` — manual compilation of `lte_link_control` — [V][S]

**Where:** `nrfmodule-core/src/client/lte_lc_client.cmake`.

**Touches upstream:** `${ZEPHYR_BASE}/../nrf/lib/lte_link_control/` — enumerates 20+ `.c` files by name (core, `common/`, `modules/`), adds `include/` dirs, injects **global** `zephyr_compile_definitions(CONFIG_LTE_LINK_CONTROL=1)`. Bypasses Nordic's `LTE_LINK_CONTROL` Kconfig (which we can't select — pulls NRF_MODEM_LIB).

**How a bump breaks it:**
- File renamed/removed → CMake configure error (visible).
- File **added** → silent: we never compile it. Already latent at v3.2.1: upstream has `modules/cellular_profile.c` (behind `LTE_LC_CELLULAR_PROFILE_MODULE`, default n) — absent from our cmake. If a product enables it, silent no-op or link error.
- Condition drift: upstream conditions `cereg/cfun/cscon/mdmev/xsystemmode` on `LTE_LC_*_MODULE` Kconfigs; ours compiles them unconditionally ("Always enabled"). v3.4.0 removes `default y` from `LTE_LC_MODEM_EVENTS_MODULE`, and `mdmev_enable()`/`mdmev_disable()` became `mdmev_notifications_enable()` internally (public `lte_lc_modem_events_enable/disable()` **removed in NCS 3.3**) — consumers calling the removed public API break visibly; our unconditional compile of `mdmev.c` diverges from upstream's config model.
- v3.2.1→v3.4.0 measured drift (verified by tree/content diff): `modules/CMakeLists.txt` identical; changed sources: `lte_lc.c`, `lte_lc_modem_hooks.c`, `cfun.c`, `mdmev.c`, `helpers.c`, `xsystemmode.c`, `dns.c`, `pdn.c`; `struct in_addr` → `struct net_in_addr` in `lte_lc.h` (Zephyr 4.4 net API rename) ripples into app code.

**Verification:** diff upstream `lte_link_control/{CMakeLists.txt, modules/CMakeLists.txt, common/CMakeLists.txt}` old-pin vs new-pin and mirror every add/remove/condition change; clean configure+build with each product's enabled module set; HIL: `lte_lc_connect_async()` fires `LTE_LC_EVT_NW_REG_STATUS`.

---

## S3. `lte_lc_client.Kconfig` — mirrored Kconfig tree — [V][S]

**Where:** `nrfmodule-core/src/client/lte_lc_client.Kconfig` (~577 lines mirroring Nordic's `lte_link_control/Kconfig` under `if NRFMODULE_LTE_LINK_CONTROL`).

**Touches upstream:** Nordic's entire `lte_link_control/Kconfig` option tree. Duplication is tolerated because Nordic's copy sits inside inactive `if LTE_LINK_CONTROL`. Choice symbols (`LTE_LC_PDN_DEFAULT_FAM_*` etc.) deliberately not mirrored.

**How a bump breaks it:**
- Upstream adds an option that compiled sources reference: **v3.4.0 adds `LTE_LOCK_BAND_LIST`**, and `lte_lc_modem_hooks.c` gains `BUILD_ASSERT(sizeof(CONFIG_LTE_LOCK_BAND_MASK) > 1 || sizeof(CONFIG_LTE_LOCK_BAND_LIST) > 1)` plus direct macro use — without mirroring the option, any build with `LTE_LOCK_BANDS=y` fails on an undefined macro (visible), and the mask's removed upstream default changes behavior (silent).
- Default drift: v3.4.0 drops `default y` from `LTE_LC_MODEM_EVENTS_MODULE`; our mirror still says `default y` → we'd silently enable what upstream now considers opt-in.
- Removed options linger in our mirror as dead config (harmless but misleading).

**Verification:** `diff <old-nrf>/lib/lte_link_control/Kconfig <new-nrf>/lib/lte_link_control/Kconfig` and apply the same delta to the mirror; clean Kconfig pass (no "undefined symbol" / choice warnings) on all product prj.confs.

---

## S4. `nrf_modem_at` emulation + forked Nordic headers — [V][S]

**Where:** `nrfmodule-core/src/client/{nrf_modem_at.c, nrf_modem_lib.c}`; forked headers in `nrfmodule-sdk/include/{nrf_modem_at.h, nrf_modem.h, nrf_modem_lib.h, nrf_socket.h, nrf_errno.h}`; linker sections in `nrfmodule-sdk/zephyr/linker_data.ld`; `zephyr_library_compile_definitions(CONFIG_NRF_MODEM_LIB=1)` trick in core `CMakeLists.txt`.

**Touches upstream:** the `nrf_modem_at_*` / `nrf_modem_lib_*` API contract owned by nrfxlib + `nrf/lib/nrf_modem_lib`. The SDK headers are **diverged forks** (verified: `nrf_modem_at.h` fork lacks upstream's `nrf_modem_at_cfun_handler_set()` and `__nrf_modem_printf_like` annotations, adds `nrf_modem_at_cmd_raw()`, `nrf_modem_at_datamode_send()`, `nrf_modem_at_client_init()`; `nrf_socket.h` diverges massively; `nrf_errno.h` identical). They shadow nrfxlib because nrfxlib's include dir is never added on nRF52840 builds. `linker_data.ld` re-creates `nrf_modem_lib_{init,shutdown,dfu,at_cfun}_cb` iterable sections so `NRF_MODEM_LIB_ON_INIT/ON_CFUN` macros in upstream-compiled sources resolve.

**How a bump breaks it:**
- Newly-compiled NCS sources call an API absent from the fork → compile error (visible, e.g. if lte_lc adopts `nrf_modem_at_cfun_handler_set`).
- Upstream renames/extends the callback section names or macro internals in `nrf_modem_lib.h` → handlers silently never fire (sections empty) — **silent**.
- Error-encoding contract (`(NRF_MODEM_AT_CME_ERROR << 16) | code`) or CFUN-hook ordering drifts upstream → subtle runtime misbehavior.
- nrfxlib `nrf_modem_at.h` itself: **no change v3.2.1→v3.4.0** (verified) — low churn seam, but check every bump.
- `CONFIG_NRF_MODEM_LIB=1` as a library-scope compile definition: upstream code newly gated on *other* `NRF_MODEM_LIB_*` sub-options quietly compiles out.

**Verification:** full link of a modem product; boot: `nrf_modem_lib_init()` returns 0 and lte_lc's `NRF_MODEM_LIB_ON_CFUN` hook observably runs (CEREG subscription happens after `AT+CFUN=1`); `modem_key_mgmt` cert write/read; diff fork vs nrfxlib header each bump and reconcile deliberately.

---

## S5. `sm_monitor` rename + AT_MONITOR bridge — [V][R]

**Where:** `sm_at_client_monitor.c` (dispatch), `sm_at_client_monitor.ld` (`._sm_monitor_entry.*` RWDATA section), SDK `sm_at_client.h` (`SM_MONITOR()` macro, `struct sm_monitor_entry`), bridge chain documented in `nrf_modem_at.c` header comment.

**Touches upstream:** Nordic `at_monitor` internals: `struct at_monitor_entry` field layout (`filter`, `handler`), its iterable section (bridge does `STRUCT_SECTION_FOREACH(at_monitor_entry, e)`), and at_monitor's SYS_INIT that registers `at_monitor_dispatch` via `nrf_modem_at_notif_handler_set()` (which we implement). Rename exists to avoid duplicate `at_monitor_heap/fifo/work` when Nordic's `at_monitor.c` is also linked (`select AT_MONITOR` in `lte_lc_client.Kconfig`).

**How a bump breaks it:** upstream changes `at_monitor_entry` fields → bridge compile error (visible); upstream adds new file-scope symbols to `at_monitor.c` that collide with our monitor's → link error (visible); upstream changes dispatch filtering semantics (e.g. paused handling) → behavioral drift (silent). Measured: `at_monitor.c` **byte-identical** v3.2.1→v3.4.0; only Kconfig `module-dep=LOG` line dropped. Stable seam, verify anyway.

**Verification:** link succeeds with both monitors present; HIL: a `%XTIME` URC reaches `date_time` (AT_MONITOR path) and a MON_ANY SM_MONITOR handler simultaneously; multi-URC single-buffer split test.

---

## S6. Other manually-compiled NCS client libs — [V]

**Where:** `nrfmodule-core/src/client/{date_time_client.cmake, modem_info_client.cmake, modem_key_mgmt_client.cmake, pdn_client.cmake}` (+ their mirrored `.Kconfig`s).

**Touches upstream:** `nrf/lib/{date_time, modem_info, modem_key_mgmt, pdn}` sources compiled by path with `CONFIG_*=1` compile-definitions mapped from `NRFMODULE_*` options.

**How a bump breaks it:**
- **`nrf/lib/pdn` is removed in NCS v3.4.0** (verified: tree 404; release notes confirm "Removed the deprecated PDN library"). `pdn_client.cmake` still references `${NRF_DIR}/lib/pdn/pdn.c` — any consumer setting `NRFMODULE_PDN=y` fails at configure on 3.4. Must be deleted/tombstoned during the bump.
- date_time/modem_info/modem_key_mgmt: file lists stable v3.2.1→v3.4.0 (verified); content drift only (modem_info buffer-overflow fix lands in 3.4 — we inherit it for free by compiling from source). New Kconfig-derived macros used by the sources must be added to the compile-definition mapping (silent-default risk).
- Log-template drift: upstream Kconfigs dropped `module-dep=LOG`; our mirrors that source `Kconfig.template.log_config` should be re-checked for template argument changes.

**Verification:** build each with its `NRFMODULE_*` option enabled; grep new-pin sources for `CONFIG_[A-Z_]*` macros not covered by the mapping; HIL date/time sync via `%XTIME`/`AT+CCLK`.

---

## S7. SLM proprietary AT wire protocol — [R]

**Where:** `sm_modem_power_mgmt.c` (`#XSLEEP=2`, `#XRESET`), `nrf_modem_lib.c` (`#XRESET`, "Ready" boot URC, probe loop), `mqtt/nrfmodule_mqtt.c` (`#XMQTTCFG/CON/PUB/SUB/UNSUB/EVT/MSG`), `http/nrfmodule_http.c` (`#XSOCKET/#XSSOCKET/#XSSOCKETOPT/#XCONNECT/#XSEND/#XRECV/#XHTTPCCON`), plus DTR/RI GPIO semantics in `sm_at_client.c`.

**Touches upstream:** the serial-modem **application firmware's** AT command surface — versioned by ncs-serial-modem release, not by the NCS pin of the host build. This seam moves when the deployed nRF9151 FW moves.

**How a bump breaks it (serial-modem v2.0.0, from upstream migration notes + changelog):** RI changes **pulse → level** (stays asserted until host asserts DTR — our edge-triggered `GPIO_INT_EDGE_TO_ACTIVE` RI handling and the DTR re-cycle wake logic must be revalidated); `#XGNSS` position syntax renamed `#XGNSSPOS`; `AT#XNRFCLOUDPOS` syntax/semantics changed; HTTPC/CoAP auto-receive now appends CRLF after data; URCs are now buffered and flushed *before* responses (`0ffd620`, `cf583ef`, `27032e9`) — changes interleaving assumptions in `response_handler`/parsers, mostly in our favor (this is the upstream fix for our URC-contamination class); CTS pull-down → pull-up; app log moved RTT → UART1.

**Verification:** HIL matrix against the exact deployed modem FW build: wake-from-XSLEEP (RI level semantics), MQTT connect/pub/sub round-trip, HTTP GET via `#XRECV` framing, boot "Ready" detection, `#XRESET` recovery. There is no build-time check for this seam — only HIL.

---

## S8. SDK auto-detect + Kconfig `orsource` path coupling — [S]

**Where:** `nrfmodule-sdk/CMakeLists.txt` (3-way: `TARGET private_modem_lib` / `EXISTS ${WEST_TOP}/modules/lib/nrfmodule-core` → `add_subdirectory` / fallback `zephyr_link_libraries(lib/libmodem_core.a)`); `nrfmodule-sdk/zephyr/Kconfig` (`orsource "../../nrfmodule-core/src/..."` ×5); core `CMakeLists.txt` reciprocal `zephyr_include_directories(../nrfmodule-sdk/include)`.

**Touches upstream:** west workspace layout (`west.yml` `path:` values) and Zephyr module machinery (`zephyr/module.yml` `board_root/dts_root`).

**How a bump breaks it:** `orsource` is *optional-source* — if the relative path breaks (core moved/renamed, workspace relayout), all modem Kconfig options **silently vanish** and the SDK builds as BLE-only with a plausible-looking log line. The binary fallback links a **stale** `libmodem_core.a` compiled against an older NCS — ABI drift (struct layouts, inlines, Kconfig-dependent sizes like `CONFIG_NRFMODULE_SM_AT_CLIENT_UART_RX_BUF_SIZE`) is checked by nothing. NCS bumps don't move this seam directly, but every bump requires regenerating `libmodem_core.a` from the matching core tag — there is currently no documented regeneration procedure or CI for binary-mode builds (open gap).

**Verification:** two builds per bump: (a) full workspace (expect `[nrfmodule] Loading module manually` or auto-loaded), (b) workspace with core removed and `NRF_MODEM_CLIENT=y` (expect `Linking PUBLIC BINARY`, then link + boot). Grep build log for the `[nrfmodule]` status line — treat "BLE-only build" in a modem product as a failure.

---

## S9. `west.yml` ordering and pins (manifest) — [S]

**Where:** `nrfmodule-dev-manifest/west.yml`; `nrfmodule-sdk/west.yml` (customer-facing default).

**Touches upstream:** west import precedence: `sdk-nrf` listed first so its pin beats `nrfmodule-sdk`'s own `west.yml` (which still says **v3.1.1** — stale for any customer who inits directly from the SDK repo). `self.path: config/manifest`.

**How a bump breaks it:**
- Reordering projects or removing `import: true` silently changes which NCS gets fetched.
- **`ncs-serial-modem` is pinned `revision: main` — floating.** Verified: local checkout sits at `448cf99`, upstream `main` is 177 commits ahead and now **targets NCS v3.4.0**. Any fresh `west update` today drags a 3.4-targeting module (its `drivers/`, `Kconfig`, `zephyr/module.yml` get processed by every workspace build) into a 3.2.1 workspace. The nRF52840 host DTS additionally depends on this module's `nordic,dte-dtr` binding (see S11) — upstream already renamed the binding *file* once (`9ac2dd5`; compatible string unchanged, so it survived by luck).
- Changing any `path:` breaks S8's hard-wired relative paths + existing developer workspaces.
- SDK `west.yml` v3.1.1 self-pin: customers initing from the SDK get a different NCS than the ecosystem tests.

**Verification:** after every west.yml edit: fresh `west init && west update` in a clean dir; `west list` shows expected revisions; host board build resolves `nordic,dte-dtr`; core twister runs.

---

## S10. Docker CI image + reusable workflows — [S]

**Where:** `infra/docker/Dockerfile`, `.github/workflows/{reusable-ci.yml, reusable-build.yml, reusable-lint.yml, publish-docker.yml}` (manifest); `nrfmodule-core/.github/workflows/ci.yml` (caller).

**Touches upstream:** NCS Python requirements (installed from a `west init --mr v3.2.1` snapshot at image build), Zephyr SDK toolchain (0.17.4 ARM-only), qemu-system-arm.

**Current state (verified — corrects the handoff/CLAUDE.md claim):** the Dockerfile **already installs NCS v3.2.1 deps** (fixed in `e59b9fa` + `2be851c`); the "v3.1.1 Python deps" note in CLAUDE.md is stale. The real skew is worse and lives in **`reusable-ci.yml`**: it runs `west init -m https://github.com/V1incentC/test-premium-manifest` — a personal prototype manifest that pins **sdk-nrf v3.1.1** and pulls `test-company-sdk` / `test-modem-source` from the personal account — then swaps PR code into `modules/lib/test-modem-source`. So nrfmodule-core's green "Library CI" (verified passing 2026-06-24) actually tests PR code against **NCS v3.1.1 + a stale SDK snapshot**, not the v3.2.1 workspace the ecosystem ships on. nrfmodule-sdk has **no CI at all**. Core's twister surface is one qemu_cortex_m3 smoke test (`tests/modem_say_hello`).

**How a bump breaks it:** any NCS bump that keeps this workflow untouched produces green CI that verified nothing about the new pin. Additionally, **NCS v3.4.0 requires Zephyr SDK 1.0.1** (verified via `SDK_VERSION` at `ncs-v3.4.0`; 3.2.1 needs 0.17.4) — the image must be rebuilt with the new toolchain and the new pip requirements, and `publish-docker.yml`'s `ncs-v3.2.1` tag scheme must gain a new tag.

**Verification:** `docker build` succeeds; inside the image `west init -m <real manifest> && west update && west twister -T modules/lib/nrfmodule-core/tests --integration` passes; CI logs show the intended NCS revision (`west list` step — worth adding).

---

## S11. SDK board definitions + cross-module DTS binding — [S][R]

**Where:** `nrfmodule-sdk/boards/arm/livetracker/*` (nrf52840 host + nrf9151/ns modem targets), `boards/arm/beescales_bt/*`; `module.yml` `board_root: .`; binding dependency: `livetracker_nrf52840.dts` node `dte_dtr` (`compatible = "nordic,dte-dtr"`) and `livetracker_nrf9151_ns.dts` node `dtr_uart2` (`compatible = "nordic,dtr-uart"`) — **both bindings live in the ncs-serial-modem module** (`dts/bindings/dte_dtr/`, `dts/bindings/dtr_uart/`), not in the SDK.

**How a bump breaks it:**
- A Zephyr minor bump (3.2.1→3.4.0 spans Zephyr **4.2.99 → 4.4.0**) can change board-file expectations (HWMv2 schema details, `nordic/nrf91xx_partition.dtsi` layout, TF-M pad sizes, default `pinctrl` includes). Breaks visibly at DTS compile, usually.
- The binding dependency breaks **silently structurally**: if ncs-serial-modem (floating at `main`, see S9) moves/renames the binding directory or compatible, host DTS stops resolving `dtr-gpios`/`ri-gpios` phandles → build error at best, changed GPIO flags semantics at worst.
- **Known out-of-sync (confirmed by reading the DTS):** `livetracker/nrf9151/ns` defines uart2 at **115200, `hw-flow-control` commented out**, and its header comment documents RTS=P0.12/CTS=P0.09 — while the deployed modem FW is built from `d:/Root/serial_modem` with an *untracked* `boards/livetracker.overlay` at **921600 + HWFC, RTS=P0.09/CTS=P0.12 (deliberately swapped)**. The 52840 side (`livetracker_nrf52840.dts` uart0) is already 921600 + HWFC. Building the modem FW with the SDK board today yields firmware that cannot talk to the tracker. Interop truth lives outside version control.

**Verification:** build both board targets against the new NCS; byte-compare the effective uart2 config (`build/zephyr/zephyr.dts`) between SDK-board build and the deployed-overlay build; HIL 52840↔9151 AT traffic at 921600+HWFC.

---

## S12. Version/tag/binary coupling — [S]

**Where:** tags on core+sdk (+ manifest `v2.x` branch pins); `nrfmodule-sdk/lib/libmodem_core.a`; CLAUDE.md version pins.

**How a bump breaks it:** version strategy says v2.x tracks NCS 3.2.x — an NCS 3.4 jump is by convention a **major/minor line decision** (v3.x or v2.x+1 tracking 3.4), and all three repos must tag together with `west.yml` pins updated on the `v2.x` (or new `v3.x`) branch, `main` staying on `revision: main`. `libmodem_core.a` must be rebuilt from the same core tag against the same NCS pin — currently no documented rebuild procedure and no CI that ever links the binary path (S8). Pending state: core+sdk have unreleased API since v2.2.0 → **next tag is v2.3.0 and must precede any NCS bump** so a known-good pre-bump line exists.

**Verification:** after tagging: fresh `west init` from `v2.x` branch resolves all three tags; binary-mode build links against the regenerated `.a`.

---

## S13. Zephyr-version seams (secondary, driven by the same bump) — [V][R]

- **`ble_log` backend** (`src/lib/ble_log/`): Zephyr log-backend API has churned across minor versions; 4.2→4.4 needs an API check.
- **GNSS drivers** (`src/drivers/gnss/`): custom Quectel L76 driver + assist framework use device/driver-model APIs and `DEVICE_DT_INST_DEFINE`; also documented duplicate-instance hazard with vendored copies (`NRFMODULE_CORE_SKIP_GNSS`).
- **BMP390 vendored driver** (SDK `drivers/sensor/bmp390/`, "stock bmp388 + TURN_ON re-init"): upstream Zephyr bmp388 driver drift must be re-checked per Zephyr bump.
- **Networking types**: Zephyr 4.4 renames (`struct in_addr`→`net_in_addr` in NCS structs, `nrf_`→`zsock_` in upstream code) ripple into `nrfmodule_http/mqtt` and app code.
- **PM device / UART async**: `sm_at_client.c` leans on `pm_device_action_run` semantics and nrfx UARTE async event ordering; both have had behavioral fixes between Zephyr minors. HIL sleep/wake is the only real check.

**Verification:** compile all optional features (`NRFMODULE_BLE_LOG_BACKEND`, GNSS, BMP390, RGB LED) in one build; run SDK unit tests (`tests/led_*` on qemu); HIL sensor + GNSS smoke.

---

## Cross-cutting observations

1. **The riskiest seams are the silent ones:** S8 (orsource swallows missing core), S9 (floating serial-modem pin), S10 (CI green against the wrong NCS). None of them are exercised by any current automated check.
2. **The porting guide covers S1–S6 reasonably but S7–S12 not at all** — the manifest-side, board, binary, and CI seams are where an "everything compiled, ship it" bump would actually die.
3. **Two seams are already broken today** independent of any bump: the nrf9151/ns board defs (S11) and reusable-ci.yml (S10). Fixing them *before* the NCS bump converts them from unknowns into regression detectors.
