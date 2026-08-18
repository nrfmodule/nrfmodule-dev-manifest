# Execution plan: AT/GNSS fix wave (v2.3.0) + NCS v3.4.0 migration (v3.0.0)

**Goal:** land core #20–#40 remediations and migrate the platform to NCS v3.4.0, fully
revalidated on the nRFTracker bench, **before flashing the new nRFTracker PCBs**.

**Strategy:** two releases, not one. v2.3.0 ships the fix wave on NCS v3.2.1 (small,
bisectable risk). v3.0.0 is the NCS v3.4.0 bump on top of an already-proven codebase.
Never mix concurrency surgery and toolchain migration in one release.

**Versioning:** txn_begin/end never shipped in a tag (added post-v2.2.0), so their removal
in v2.3.0 is not an API break. NCS 3.4.x track ⇒ new major, v3.0.0 (convention: v1.x↔3.1.x,
v2.x↔3.2.x). `v2.x` branch stays for maintenance patches.

---

## Phase 0 — Safety net first (AFK, ~2 days)

The ADR-0002 rework is concurrency surgery on the AT pipeline. Build the harness before
operating.

- **P0.1** Stand up an AT-layer unit harness in core `tests/` (qemu_cortex_m0/m3 overlay
  pattern; native_sim in CI only). Fake transport injecting RX bytes/URCs; no workqueues
  in code under test where avoidable.
- **P0.2** First suites: sm_monitor line-splitting/dispatch (multi-line URC assembly,
  CRLF gating, paused, prefix scan) and sm_at_client state machine (PENDING/ERROR paths,
  sem reset, timeout). These lock in CURRENT behavior before any fix lands.
- **P0.3** Wire into CI (`west twister -T nrfmodule-core/tests` already runs in
  reusable-ci.yml — confirm new suites are picked up).

Exit gate: harness green in CI on unmodified code.

## Phase 1 — v2.3.0 fix wave on NCS v3.2.1 (PR-sized slices)

Two parallel tracks. Each PR: code agent implements → review agent on diff → quality gate
→ unit tests → HIL smoke where hardware-touching. Reference implementations exist
downstream; logic is re-derived in platform idiom — **no downstream brand may appear in
any commit, PR, comment, or code** (hard business constraint; add to review checklist).

### Track 1 — AT pipeline (serial, order matters)

- **PR-A — sm_at_client point fixes** (small, AFK): #29 set (MIN-clamp the release-build
  unbounded memcpy — memory corruption, do first; -EBUSY tolerance on rx_enable;
  RX_DISABLED bit; CRLF/full-buffer dispatch gating) + #25 buf_unref block-vs-data pointer
  + #22 partial (k_sem_reset before PENDING, AT_CMD_ERROR on tx-fail). All unit-testable.
- **PR-B — URC dispatch consolidation** (small-medium, AFK): #23 (delete MON_ANY bridge,
  no-op notif_handler_set stub) + #26 (multi-line #XMQTTMSG collector, static bounds-checked
  buffers, negative-length rejection) + #28-F11 (sm_monitor_heap sized from
  AT_CMD_RESP_MAX_SIZE). Heaviest unit-test coverage — the P0 monitor suite is built for
  exactly this.
- **PR-C — ADR-0002 concurrency baseline** (large, HITL review): single public AT mutex
  (`nrf_modem_at_lock/unlock/lock_is_held_by_current`), redirectable response accumulator
  replacing the sysworkq barrier, dedicated `sm_at_client_work_q`, atomic
  `nrf_modem_at_cmd_datamode()`, txn API removal (core .c + sdk header), post-timeout
  quarantine **with URC-prefix scanning kept alive across the drain** (#40 gate 5),
  `nrf_modem_lib_reset()` lock bracket (#28-F13), and the #22 atomic-CAS on `sm_at_state`
  (#40 gate 4 — chosen over waiting for #27; shell bypass remains tracked separately).
  Resolves #20/#21/#24. Mandatory /embedded-quality-review (threading + >200 lines).
  Document the `BUILD_ASSERT(SYSTEM_WORKQUEUE_PRIORITY < 0)` contract (#40 gate 2).
- **PR-D — power-mgmt rider** (small, AFK + HIL): #37 RI-wake drops the AT ping, re-asserts
  DTR + settle + inactivity-timer reset (distinct from XSLEEP edge-cycle — unaffected);
  bounded auto-sleep waits (trylock→500 ms, explicit sleep→30 s + -EAGAIN). Rides after
  PR-C since sm_modem_power_mgmt.c is rewritten there. HIL: inbound MQTT while asleep must
  arrive end-to-end.
- **PR-G — AT-dark watchdog** (medium, AFK): #36 — consecutive-timeout detector emitting an
  app event, default-n auto-reset Kconfig, reset-loop spacing floor. Include in v2.3.0:
  tracker's 9h-silent-modem incident wants it. Depends on PR-C (counter hooks the new
  transaction core).

### Track 2 — independent of the AT rework (parallel, AFK)

- **PR-H — GNSS fixes**: #32 (GST k_spinlock, get_accuracy off the command lock),
  #33 (pipe-open -EBUSY bounded retry, checked close; **do not add the redundant
  modem_pipe_release**), #34 (`l76_switch_and_verify()` used by cold-boot and hunt paths,
  park at target, named constants; port the default-n bench-shell HIL hook),
  #35 (Kconfig selects + library-scoped includes). Can be one PR or two (#32 alone if
  review prefers).
- **PR-E — HTTP fixes**: #38 (do_receive init, strstr-anchored socket parse, delete dead
  send_data_text) + #31 (hex-XRECV BUILD_ASSERT on the right symbol) + #20's open
  sub-point (HTTP timeout_handler socket-close off the sysworkq).
- **PR-F — MQTT injection guard**: #39 — `at_string_is_safe()` gate on client_id/broker/
  creds/topics, -EINVAL on reject, contract documented in the sdk header; %.*s for creds.
- **PR-I — USB VBUS gate log blackout** (sdk #23, repo: nrfmodule-sdk): on VBUS removal,
  `log_backend_deactivate()` the shell log backend alongside `usbd_disable()`; reactivate
  on replug; `#if defined(CONFIG_SHELL_LOG_BACKEND)` guard. Applies to livetracker AND
  beescales_bt board_power.c (duplicates — shared helper is an optional rider). HIL:
  unplug-window FS-log continuity on the LOG_FS flavor. Field-reliability: deployed
  trackers currently black out their flash logs whenever unplugged. Rider check while
  here: the downstream fixing commit also shrank log rotation (6×1 MB → 6×500 KB) for
  littlefs headroom — verify the tracker's LOG_FS rotation vs data-queue headroom.

Explicitly deferred (not v2.3.0 blockers): #27 (shell bypass — mitigated by PR-C's CAS),
#28-F9 remainder (dtr_config.active atomicity) and F12 (buffer/stack defaults), the
downstream TLS-default flip (rejected) and default-on auto-reset (rejected).

## Phase 2 — v2.3.0 release (HITL, ~3 days + soak)

1. Cumulative diff: /embedded-quality-review + review agent; qa agent spec audit
   (fresh context, no implementation reading).
2. HIL battery on the tracker bench (hil_cycle.py, COM57): concurrent-AT soak
   (sleep/wake + app AT + shell), RI-wake e2e, GNSS baud-recovery via bench shell,
   MQTT/HTTP flows, GNSS start/stop with accuracy reads in callback (#32 repro).
3. Power gate: PPK2 floor check — the dedicated workqueue adds a thread; assert no
   busy-wake regression vs the ~89 µA baseline.
4. Release notes / SDK migration section: new lock API, new Kconfigs, sysworkq-priority
   BUILD_ASSERT contract, txn API gone (never tagged).
5. Tag v2.3.0 on core + sdk together; update manifest pins (v2.x branch per tag strategy).
   /release flow: tests → smoke → power. No self-merge; PRs await user merge.

Exit gate: 48 h tracker soak on v2.3.0 clean (watch for #69-class silence with the #36
event wired to a log line).

## Phase 3 — NCS v3.4.0 migration ⇒ v3.0.0 (~1 week)

Precondition: v2.3.0 tagged (fallback line for all products).

- **P3.1** Toolchain + workspace: nrfutil toolchain v3.4.0; fresh workspace at
  **`c:/ncs/nrfmodule_v3x`** — named by platform *series*, not exact version: v3.1.0/v3.2.0
  will reuse this workspace (NCS 3.4.x stays constant across them), and `nrfmodule_v3.0.0`
  sitting next to the NCS-named `nrfmodule_v3.2.1` would read as an *older* NCS. The old
  v3.2.1 workspace is NOT deleted — it becomes the `v2.x` maintenance-branch workspace.
- **P3.1b** Cutover checklist (executes at Phase 4 exit): update CLAUDE.md path tables
  (global + per-repo), unit-test launch commands (`--ncs-version v3.4.0`), HIL script env,
  and doc references from `nrfmodule_v3.2.1` to `nrfmodule_v3x`.
- **P3.2** Manifest: `west.yml` sdk-nrf → v3.4.0 (sdk-nrf stays FIRST). Follow + update
  core's NCS_PORTING_GUIDE.md as executed.
- **P3.3** Known port items (mapped from the downstream migration + audit):
  - #30 pdn_client — `nrf/lib/pdn` removed in v3.4.0; re-point per porting investigation.
  - `CONFIG_MODEM_INFO_LOG_LEVEL` define in modem_info_client.cmake (comment on #30).
  - date_time POSIX_TIMERS Kconfig fallout.
  - Re-diff vendored lte_lc sources vs v3.4.0 originals; adjust lte_lc_client.cmake defines.
  - sm_at_client: diff Nordic serial_modem changes since fork (448cf99+ — URC fix, AT host
    refactor). **Cherry-pick Nordic fixes into our reworked stack; do not re-vendor
    wholesale** (would destroy the ADR-0002 rework).
- **P3.4** CI/Docker: rebuild infra/docker image (Zephyr SDK version per v3.4.0 needs,
  v3.4.0 Python deps — image still carries v3.1.1 deps today), publish, CI green.
- **P3.5** SDK repo riders while boards are open: sdk #21 (west.yml pin → tested NCS),
  sdk #20 (livetracker/nrf9151/ns UART config sync: 921600+HWFC, RTS/CTS swap).
- **P3.6** Unit suites + twister green on v3.4.0; product-template build green.
- **P3.7** Tag v3.0.0 (core+sdk+manifest main); cut `v2.x` maintenance branch.

## Workstream S — serial-modem (nRF9151) hosting + release (parallel; S1 is URGENT)

The nRF9151 SLM-based modem FW lives only in `d:/Root/serial_modem`: a local git repo,
one squashed commit, **no remote**, and the deployed build recipe is UNCOMMITTED
(`prj.conf` modified, `boards/livetracker.overlay` untracked). Independent of all phases
except S6; do S1 immediately and S2–S5 any time — recommended early, so the modem baseline
is frozen and boss-flashable before host-side surgery begins.

Distribution model (verified against Nordic docs 2026-07-16): SLM was removed from
sdk-nrf in NCS v3.2.0 and is now the **"Serial Modem" NCS add-on**, released separately
from `nrfconnect/ncs-serial-modem` (releases: v1.0.0, v1.0.1, v2.0.0-preview1/2).
**S2 audit correction (2026-07-16): the local copy is a byte-identical snapshot of the
add-on's `app/` tree at `dd85d55` (2025-12-22, v0.3.0+8 — an ancestor of v1.0.0, 177
commits BEHIND the previously assumed 448cf99).** Delta vs dd85d55 is config-only:
prj.conf debug-logging toggle + livetracker.overlay + two dev-rig overlays + .gitignore.
The workspace module at `c:/ncs/nrfmodule_v3.2.1/ncs-serial-modem` is @448cf99 — that is
NOT the deployed modem baseline. Deployed FW builds against plain NCS v3.2.1 (proven
recipe), not the add-on's own sdk-nrf pin. Consume it the add-on way — a west manifest pinning the add-on, which itself
pins its compatible sdk-nrf. Key decoupling: **the modem FW's NCS version is independent
of the host platform's NCS** (separate SoC, separate workspace); the only coupling is the
AT/URC wire surface against our sm_at_client.

- **S1 (today):** commit the dirty state in `d:/Root/serial_modem` — the modified
  `prj.conf` + `livetracker.overlay` ARE the deployed config (921600 + HWFC, RTS/CTS
  swapped vs docs). This snapshot of deployed truth is needed regardless of S2's outcome.
- **S2 — redownload + delta audit:** clone `nrfconnect/ncs-serial-modem`, diff the local
  copy against 448cf99. Expected delta: config only (prj.conf + overlay). The result
  decides D7.
- **S3 — repo:** create `nrfmodule/serial-modem` as a **thin build repo**: `west.yml`
  pinning `ncs-serial-modem` at **dd85d55** (deployed baseline; NOT v1.0.0 — that is 176
  commits newer) +
  our overlay/Kconfig fragments + CI + release tooling. Build =
  `west build <add-on app> -- -DEXTRA_CONF_FILE=... -DEXTRA_DTC_OVERLAY_FILE=...`.
  Only if S2 finds src/ modifications: fork `ncs-serial-modem` on GitHub, carry patches
  on a branch, and pin the fork from the same thin repo. README: purpose, build recipe,
  UART truth table, pointer to sdk #20 (SDK board defs out of sync with this FW).
- **S4 — CI:** west-init from the thin repo's manifest in CI; artifact = `merged.hex`.
  Toolchain per the add-on's sdk-nrf pin — independent of the platform Docker image.
- **S5 — release sm-v1.0.0:** assets = the deployed hex (from `build_flash_20260706`,
  HIL-verified against the tracker host bench before publishing) + CI-rebuilt hex +
  step-by-step flashing instructions (nRF Connect Programmer or `nrfutil device program`,
  J-Link) so the boss can flash an nRF91 with zero build environment. Asset naming:
  `serial-modem-<board>-sm-v1.0.0.hex`.
- **S6 — compatibility matrix** in the release notes: sm-v1.x ↔ platform v2.x/v3.0.0 host
  (URC set, XSLEEP=2 edge-triggered DTR wake, 921600+HWFC). Own semver (`sm-vX.Y.Z`) —
  NOT part of the 3-repo tag-together set; the matrix is the link.
- **S7 (after Phase 4, never during):** upgrade = **advance the add-on pin** (v1.0.1, then
  v2.0.0 when it leaves preview) → sm-v2.0.0. Nordic's URC fix + AT host refactor since
  448cf99 arrive this way — coordinate with the host-side sm_at_client cherry-picks
  (P3.3), since both are ends of the same wire protocol. Hard rule: freeze the modem side
  while the host side migrates; one moving variable at a time.

## Phase 4 — nRFTracker on v3.0.0 + PCB gate (~1 week incl. soak)

1. Tracker workspace onto the v3.0.0 manifest; fix app-level v3.4.0 fallout.
2. Full HIL suite; enable #36 watchdog event → tracker log/telemetry.
3. 48 h soak (silent-modem watch, upload success rate, RI-wake message delivery).
4. PPK2 power gate vs baseline.
5. BLE OTA sanity (upgrade from current field build → new build).
6. /release: demo-YYYY-MM-DD prerelease per convention → **PCB flashing unblocked**.

## Operating notes (confirmed 2026-07-16)

- **Ordering confirmed:** ALL fixes (Phases 0–2, v2.3.0) before the NCS migration (Phase 3).
- **Bench:** board on J-Link, shell currently **COM58** — but the CDC port re-enumerates on
  a different COM after flashes; always discover via `hil_shell.py --list`, never hardcode.
- **nRF91 modem-side flashing is the user's** (S5 HIL-verify, S7, and any modem re-baseline
  during Phase 3/4). nRF52840 host-side flashing is agent-driven via hil_cycle.py.
- **Agent delegation policy:** the orchestrator delegates and reviews, it does not grind.
  Sonnet subagents for mechanical work (diffs, drafts, test boilerplate, log parsing);
  Opus subagents for implementation, review, and analysis tasks. Ultracode only at the
  three agreed checkpoints: PR-C review, pre-v2.3.0-tag audit, Phase-3 NCS delta sweep.

## Decision points (user)

| # | Decision | Recommendation |
|---|----------|----------------|
| D1 | v2.3.0 includes #36 watchdog? | Yes (tracker field history) |
| D2 | #40 gate 4: CAS vs close #27 first | CAS in PR-C; #27 stays open, separate |
| D3 | NCS 3.4 release number | v3.0.0 (track convention) |
| D4 | PR-H as one PR or split #32 out | Split if review runs long; #32 is the deadlock fix |
| D5 | Tracker PCBs wait for full Phase 4 or flash on v2.3.0 | Full Phase 4 (user stated: fixes + migration first) |
| D6 | New workspace folder name | `c:\ncs\nrfmodule_v3x` (platform series; exact-version name goes stale at v3.1.0, and a platform-numbered name next to the NCS-numbered old folder invites confusion) |
| D7 | serial-modem repo shape | Thin build repo pinning the `ncs-serial-modem` add-on + our overlays (Nordic's intended consumption model); GitHub fork only if the S2 delta audit finds src/ modifications |
| D8 | Modem FW NCS bump timing | sm-v2.0.0 after Phase 4; never while the host migrates |

## Risks

- **Deployed modem recipe uncommitted** (until S1 lands) — the fleet's nRF9151 config
  exists only as a dirty working tree in `d:/Root/serial_modem`.

- **PR-C regressions** — mitigated by Phase 0 harness, HIL soak, and behavioral reference
  downstream (privately consulted, never cited).
- **NCS 3.4 unknown unknowns** beyond mapped items — timebox P3.3; the downstream migration
  is the map, not a guarantee.
- **Brand isolation slip** — checklist item on every PR/commit review in both directions.
- **Calendar**: soaks are wall-clock (2×48 h). Rough total: ~3–4 weeks elapsed.
