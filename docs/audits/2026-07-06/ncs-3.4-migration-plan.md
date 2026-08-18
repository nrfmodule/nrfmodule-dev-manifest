# NCS 3.4 / serial-modem Migration Plan

Audit date: 2026-07-06. For execution by Opus + Vincent over the coming weeks. Companion docs: `ncs-seam-inventory.md` (seams S1–S13), `NCS_UPGRADE_PLAYBOOK.md` (mechanical procedure — Phase D below executes it).

## 1. Re-verified upstream state (supersedes the 94-day-old memory)

Source: fresh clone of `nrfconnect/ncs-serial-modem` (HEAD `2ee3a42`, 2026-07-02). Our pin: `448cf99` (workspace module checkout confirmed at that SHA; both `d:/Root/serial_modem` checkouts are squashed single-commit snapshots with no upstream history — useless for changelog work).

- **177 commits** since our pin (memory said ~45; 94 days of drift). Upstream `main` now pins **NCS v3.4.0** and released **v2.0.0-preview2** (2026-06-16); final v2.0.0 not yet tagged. A formal migration-notes doc exists upstream (`doc/releases/migration_notes_v2.0.0.rst`) — read it before Phase E.
- **The "AT host refactor to pipe-based architecture" (`02ae916`) is modem-app-side, not host-side.** `lib/sm_at_client` (what we vendor) survived the refactor and received only small fixes: bounds clamp (`d915d10`), RX-recovery fixes (`f34c54a`, plus `-EBUSY` tolerance), a line-complete gate before URC dispatch, flow-control-aware enable/disable delays, and one API rename (`sm_at_client_configure_dtr_uart(bool,t)` → `sm_at_client_automatic_dtr_uart(t)`). **The feared sm_at_client breakage is much smaller than the memory implied.** The real migration surface is the *wire protocol* (seam S7).
- Host-relevant wire/behavior changes in v2.0.0 (from migration notes + commits): **RI pulse → level** (stays asserted until host asserts DTR); URCs now buffered and flushed *before* command responses (`cf583ef`, `0ffd620`, `27032e9` — the URC-contamination fix class we wanted); `#XGNSS` position syntax → `#XGNSSPOS`; `AT#XNRFCLOUDPOS` reworked; HTTPC/CoAP auto-receive appends CRLF; CTS pull-down → pull-up; app logging moved RTT → UART1 (enable at runtime via `AT#XLOG=1`); partitions moved Partition Manager → DTS; MCUboot downgrade prevention on FW updates; nRF Cloud MQTT → CoAP; standard `AT+CMUX` + `AT+CGDATA`/PPP; new `AT#XLISTEN/#XACCEPT`.
- **Maintenance line exists:** `v1-branch`, pinned **NCS v3.2.4**, tagged **v1.0.1** (2026-03-25); branch tip adds two April RX-recovery fixes. Content-wise it is a superset of our pin (verified with `git log --cherry-pick`): + RI pulse→level (`1897d18`), LOG_PANIC fix, NCS v3.2.4. It does **not** contain the URC-ordering fixes, CTS pull-up, CMUX/PPP, or the AT-host refactor — those are v2.0.0/main only.
- The binding our host DTS depends on (`nordic,dte-dtr`, seam S11) had its *file* renamed upstream (`9ac2dd5`) but the compatible string is unchanged — survived by luck; reinforces pinning (S9).
- New upstream host-side option: `drivers/nrf91-sm` — a native **Zephyr modem driver for "Serial Modem 2.0"** (`nordic,nrf91-sm-v2` binding, CMUX/PPP-based). A potential long-term replacement for parts of our sm_at_client+emulation stack. Out of scope for this migration; tracked as an open question.
- NCS side (verified by tree/content diffs, see seam inventory): 3.2.1→3.4.0 moves Zephyr 4.2.99→4.4.0, requires **Zephyr SDK 1.0.1** (Docker rebuild), **removes `nrf/lib/pdn`**, removes `lte_lc_modem_events_enable/disable()` (in 3.3), adds `LTE_LOCK_BAND_LIST` + BUILD_ASSERT in `lte_lc_modem_hooks.c`, renames `struct in_addr`→`net_in_addr` in `lte_lc.h`, drops `default y` on `LTE_LC_MODEM_EVENTS_MODULE`. `lte_link_control` file list, `at_monitor.c`, and nrfxlib `nrf_modem_at.h` are otherwise stable.

## 2. Key architectural fact for phasing

**Host NCS pin and modem FW version are decoupled.** The modem FW builds from the serial_modem repo against its *own* NCS (plain `c:/ncs/<ver>` via toolchain-manager + `ZEPHYR_BASE` override); the host workspace never compiles it. The only coupling is the UART wire protocol (S7) and the DTS binding files (S11). This lets us move the modem FW and the host NCS in separate, individually-verified steps.

## 3. Patch hop vs direct jump

| Option | Gets | Cost | Risk |
|---|---|---|---|
| Host 3.2.1 → 3.2.4 patch hop | NCS patch fixes only; **no seam movement** (lte_lc, at_monitor, nrf_modem_at.h verified identical or trivially changed across 3.2.x) | Full verification cycle (build matrix + HIL) | Low, but low information gain too |
| Host 3.2.1 → 3.4.0 direct | Everything; single verification cycle | Playbook Phases 1–7 once | Medium — but every known breaking change is already enumerated (seam inventory) |
| Modem FW → v1-branch tip (NCS 3.2.4 build) | RX-recovery fixes, RI level change, in a *small* delta | One modem FW build + bench session | Low; ideal bench rehearsal of the RI-level semantics before v2.0.0 |
| Modem FW → v2.0.0 (NCS 3.4 build) | URC-ordering fixes (the high-value item), CTS fix, CMUX/PPP/HTTP options | SLM migration notes work + full HIL | Medium-high if done blind; medium after v1-branch rehearsal |

**Recommendation:** skip the host 3.2.4 hop (two full verification cycles buy almost nothing given measured seam stability); do the host as one 3.2.1→3.4.0 move. On the modem side, use `v1-branch` tip as a **bench-only rehearsal** of the RI pulse→level semantics (it isolates that one behavioral change from the v2.0.0 avalanche), then go to v2.0.0(-preview2 or final) for deployment. If v2.0.0 final slips upstream, v1-branch tip is independently deployable (it is a strict fix-superset of what's in the field).

## 4. Phases

### Phase A — Stabilize the ground (this week; no NCS movement; low risk)
1. **Tag v2.3.0** on core+sdk, pin on manifest `v2.x` (release convention). Everything after this has a bisectable, hotfixable baseline. **Tagging fits here — before any migration work, not after.**
2. **Fix `reusable-ci.yml`** (points at a personal prototype manifest on NCS v3.1.1 — see issue draft #1). Until fixed, all CI green during the migration is meaningless.
3. **Pin `ncs-serial-modem`** in west.yml to `448cf99` (issue draft #2) so `west update` stops being a time bomb while we work.
4. **Sync `livetracker/nrf9151/ns` board defs** to deployed truth (921600+HWFC, swapped RTS/CTS, issue draft #3) and commit the currently-untracked `livetracker.overlay` knowledge into version control.
5. **Cherry-pick the two upstream sm_at_client bug fixes** into our vendored copy (bounds clamp `d915d10`, RX-recovery `f34c54a` family) — they fix real bugs at our current pin and shrink the Phase D merge. TDD where reachable; HIL the RX-recovery path.
   - *HIL for A:* regression only — boot, AT round-trip, sleep/wake cycle, URC dispatch (existing hil_cycle.py suite).

### Phase B — Modem FW rehearsal on v1-branch (bench only; ~1 session)
1. Install plain NCS v3.2.4 via toolchain-manager; build serial_modem from `v1-branch` tip (`8988555`) with the (now-fixed) SDK nrf9151/ns board or the livetracker overlay.
2. Bench-flash the 9151; run the wake-semantics HIL: RI is now **level** (asserted until host raises DTR) — validate our edge-triggered RI interrupt still fires, the DTR re-cycle wake logic (core #17) behaves, and no wake storms occur with `sm_modem_power_mgmt` auto-sleep.
3. Outcome: either "our host handles level-RI unchanged" (likely — edge-to-active still triggers on assert) or a small core fix, done against a small delta. **Do not field-deploy**; revert bench to the 448cf99 build after.
   - *HIL for B:* XSLEEP=2 → RI/DTR wake ×20 soak; RI-during-sleep (incoming URC) wake; boot Ready detection.

### Phase C — Host NCS 3.4.0 port (1–2 weeks; the playbook)
Execute `NCS_UPGRADE_PLAYBOOK.md` Phases 1–6 with OLD=v3.2.1, NEW=v3.4.0. Known work items (pre-enumerated so Opus can start immediately):
- Kconfig mirror: add `LTE_LOCK_BAND_LIST`, drop `LTE_LC_MODEM_EVENTS_MODULE` `default y`, drop `LTE_LOCK_BAND_MASK` default (S3).
- CMake mirror: adopt upstream's conditional model for cereg/cfun/cscon/mdmev/xsystemmode; add `cellular_profile.c` (S2).
- Tombstone `pdn_client.cmake` — `nrf/lib/pdn` removed upstream (S6).
- Grep-check: no product calls `lte_lc_modem_events_enable/disable()` (removed in 3.3); fix to Kconfig if found.
- `net_in_addr`/`zsock_*` sweep in core http/mqtt + products (S13).
- Docker: Zephyr SDK **1.0.1**, `--mr v3.4.0` requirements, new image tag (S10).
- Repo update order: **core → sdk → manifest** (manifest PR pins last).
- Products (nRFTrackerFW first) build in the NEW scratch workspace before anything merges.
  - *HIL for C:* full playbook Phase 6 matrix against the **unchanged deployed modem FW (448cf99)** — proves the host port alone.

### Phase D — Modem FW v2.0.0 (after C merges; ~1 week incl. soak)
1. Build serial_modem `v2.0.0`(-final if tagged, else preview2 + cherry-picks) against plain NCS v3.4.0; apply its migration notes: partition layout now DTS (check B0/MCUboot compatibility with the in-field layout — upstream documents `sm_build_disable_b0` for v1.x-compatible updates), set `app/VERSION` (downgrade prevention!), logging via `AT#XLOG=1`.
2. Host-side audit before flashing: grep all repos for `#X` commands and URC prefixes vs the v2.0.0 AT command docs. Known checks: `#XGNSS` position syntax renamed `#XGNSSPOS` (core doesn't use modem GNSS — tracker uses L76 — but verify products); `#XMQTT*` unchanged; `#XSOCKET/#XRECV` framing (CRLF note); `AT#XSLEEP`/`#XRESET` unchanged; "Ready" boot URC unchanged.
3. Deploy to bench; run the full S7 HIL matrix + 24h duty-cycle soak (URC ordering under long AT commands is the headline fix — verify no response contamination during CEREG storms).
4. Update the manifest `ncs-serial-modem` pin to the v2.0.0 tag (it's also the DTS-binding provider for host builds).
   - *HIL for D:* everything in C's matrix, plus: URC-during-long-AT-command stress, level-RI wake soak, MQTT pub under PSM wake, power-floor re-measurement.

### Phase E — Release (days)
Playbook Phase 7: tag core+sdk (version line per playbook 1.5 — an NCS-minor jump argues for **v3.0.0**, or v2.4.0 if the public API is judged unchanged; decide at the gate), manifest release branch pins tags + NCS v3.4.0 + serial-modem v2.0.0, CLAUDE.md updated, product repos migrate one by one (tracker → Waggi → BeeScales → template).

## 5. Risk register (ranked)

1. **CI is currently vacuous** (S10) — any phase "verified by CI" before A.2 is unverified. Mitigation: A.2 first.
2. **RI/DTR wake semantics change** (S7) — our power path (XSLEEP wake, DTR re-cycle) is the historically buggiest area. Mitigation: Phase B rehearsal isolates it.
3. **Modem FW rollback prevention** (v2.0.0 MCUboot downgrade prevention + PM→DTS partition change) — a bad field update could be un-downgradeable or un-bootable. Mitigation: bench DFU test of v1.x→v2.0.0 update path (and explicit no-rollback acceptance) before any field flash.
4. **Silent BLE-only builds** (S8) — during workspace churn, a missing core makes modem products build "successfully" without a modem. Mitigation: playbook's `[nrfmodule]` log-line predicate in every build gate.
5. **Header-fork drift** (S4) — 3.4's lte_lc still compiles against our forked `nrf_modem_at.h`; missed symbol reconciliation shows up as late link errors. Mitigation: playbook 1.4 grep gate.
6. **Zephyr 4.4 net/PM churn in rarely-built options** (S13) — BLE log backend, GNSS assist, BMP390. Mitigation: all-features-on build in playbook 3.7.

## 6. Open questions (for Vincent)

1. **v2.0.0 final timing** — deploy preview2 or wait for the final tag? (Affects Phase D start; preview2 is 3 weeks old and main has moved.)
2. **Version line for the release** (v2.4.0 vs v3.0.0) — convention says v2.x tracks NCS 3.2.x; a 3.4-tracking line suggests a major bump. Decide at Phase E gate.
3. **Modem firmware (mfw) version** on the deployed nRF9151 — does SLM v2.0.0 / NCS 3.4 raise the minimum mfw_nrf91x1 version? Not verified in this audit; check SLM v2.0.0 release notes + `AT+CGMR` on the bench unit before Phase D.
4. **`drivers/nrf91-sm` (Serial Modem 2.0 Zephyr driver)** — strategic evaluation: could replace sm_at_client + parts of the emulation with an upstream-maintained CMUX/PPP driver. Recommend a separate grill session after this migration lands.
5. **`libmodem_core.a` regeneration** — no documented procedure or CI today (S8/S12). Decide whether binary distribution is still a real product requirement; if yes, add a build+link CI job for binary mode.
6. **CMUX/PPP adoption** — v2.0.0 offers standard `AT+CMUX`+`AT+CGDATA`; not needed for current products but changes the data-path options (e.g. native Zephyr sockets over PPP instead of `#XSOCKET`). Park until after migration.
