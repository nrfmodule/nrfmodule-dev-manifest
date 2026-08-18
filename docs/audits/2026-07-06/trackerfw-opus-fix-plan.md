# nRFTrackerFW — Fix Plan for Opus (2026-07-06)

Companion to `trackerfw-architecture-findings.md` (same dir). One slice per session, riskiest first.
Each slice is independently buildable/testable and lands as its own PR (Flow 3/4; branch first —
never commit to main; review agent before commit; no AI attribution).

**Environment invariants (read once):**
- Repo `d:\Root\nrfmodule_workspace\nRFTrackerFW`. Full build: `west build -b livetracker/nrf52840 .`
  from the workspace, **GNSS_SIM env unset** (a stale `GNSS_SIM=1` builds the fake driver — CMake now
  warns).
- Unit tests (agent-runnable):
  `nrfutil toolchain-manager launch --ncs-version v3.2.1 -- python scripts/run_test.py tests/unit/<dir>`
  (qemu_cortex_m0; add `--pristine` after Kconfig/CMake edits).
- HIL (bench, agent-runnable when connected): `scripts/hil_cycle.py` builds+flashes+opens serial
  (COM57, J-Link; `west flash` reset is flaky — force `kernel reboot cold` after flash);
  `pytest tests/hil --hil-port COM57`. BLE HIL tests need `bleak>=3` / `smpclient`.
- House rules: `#if defined(CONFIG_X)` not `#ifdef`; parenthesized `#define` values; `const` by
  default; terse comments; the manifest quality gate runs on changed C files (`/check`).
- DR-xx = findings in `D:\Root\nrfmodule_workspace\demo_readiness_plan.md`. A/Bx = findings doc here.

---

## Slice 1 — Persist begin/halt across reset (A2 / DR-10) — **do first**

**Why first:** top product defect. Server `reboot` is now a routine event (#42/#43); any reset while
halted un-halts the tracker and burns the battery before the race. The WAIT_BEGIN boot fork is dead
code in production.

**Design (settled — implement as written):**
1. Centralize the four `has_begin/begin_unix` mutation sites in `tracker_sm.c` (parent `on_run`
   EV_SET_BEGIN/EV_CLEAR_BEGIN, `wait_begin_run` EV_SET_BEGIN, `active_run` EV_SET_BEGIN) into two
   helpers `sm_store_begin(o, unix)` / `sm_clear_begin(o)`.
2. Add one effect to `struct tracker_sm_effects` (`tracker_sm.h:61`):
   `void (*begin_persist)(bool has, int64_t begin_unix);` called from the two helpers. Runs on the SM
   thread — no locking needed. Update the prod log-stub vtable in `tracker_sm.c` and every test fake.
3. Production impl in `tracker_effects.c`: `settings_save_one("tracker/begin", ...)` with a fixed
   `struct { uint8_t has; int64_t unix; } __packed` record (match the `cmd/last` pattern in
   `command_service.c:47-104`). Loader: extend the existing `tracker` settings handler in
   `tracker_params.c` **or** a small standalone handler in tracker_effects.c — prefer the latter
   (params stays scalar-int-only). Debounce: skip the save when value unchanged (server re-sends
   config every upload).
4. Boot wiring: `tracker_sm_start(const struct tracker_sm_effects *fx)` gains no signature change —
   instead add `tracker_sm_preset_begin(bool has, int64_t unix)` called from `main()` (or an
   `effects_init` return-struct) **before** `tracker_sm_start`, which stores into
   `tracker_sm_prod_ctx` after the zeroing memset. Simplest correct order: move the ctx zeroing +
   preset into `tracker_sm_start` via optional params-struct — pick whichever keeps
   `tracker_sm_init_ctx`'s "caller pre-sets" contract honest; do NOT persist inside tracker_sm.c
   itself (keep the spine pure).
5. Semantics: persist raw `{has, begin_unix}` — the boot fork already handles a *past* begin
   correctly (→ ACTIVE). An unsynced clock at boot: `begin_pending` with `now_unix()==-1` returns
   true for any future begin — matches the documented "unsynced clock never starts ACTIVE
   prematurely".

**Files:** `src/state/tracker_sm.{c,h}`, `src/state/tracker_effects.c`, `src/main.c`,
`tests/unit/test_tracker_sm/src/main.c`.

**Blast radius (grep, verified 2026-07-06):**
- `has_begin|begin_unix` → 39 hits, 7 files (clock.{c,h}, tracker_effects.c, tracker_sm.{c,h},
  tracker_sm_shell.c, test_tracker_sm).
- `EV_SET_BEGIN|EV_CLEAR_BEGIN|EV_BEGIN_REACHED` → 16 hits, 7 files.
- `settings_save_one|settings_load_subtree` → 4 hits, 2 files (pattern to copy).

**Tests (named):**
- Unit `tests/unit/test_tracker_sm`: new cases `test_begin_persist_effect_on_set`,
  `test_begin_persist_effect_on_clear`, `test_boot_with_preset_future_begin_halts`,
  `test_boot_with_preset_past_begin_active`; all existing 24+ cases must stay green.
- HIL: `sm event begin <now+3600>` → `sm state`=WAIT_BEGIN → `kernel reboot cold` → `sm state` must be
  WAIT_BEGIN; then `sm event clearbegin` → reboot → ACTIVE. Add as
  `tests/hil/test_tracker_sm_persist.py` (serial-only, template `test_modem_lte.py`).

**Done when:** unit suite green; HIL persist test green on bench; `sm event begin` +
server-`reboot` command sequence stays halted.
**Size:** M.

---

## Slice 2 — Resettable sampler cancellation: SLEEP/WAIT_BEGIN abort an in-flight acquisition (A1 / DR-04a)

**Why second:** power correctness of a primary product state (hub pause); the seam exists, it's just
one-shot.

**Design:**
1. `gnss_producer.c`: add `atomic_t cancel_latch` beside the permanent `shutdown_latch`.
   `gnss_producer_cancel()`: set + `k_sem_give(&fix_sem)`. `gnss_producer_wait_fix()`: check it after
   the sem take (same pattern as shutdown, return `-ECANCELED`); **cleared in
   `gnss_producer_start()`** so it scopes to the current acquisition only. Keep `shutdown_latch`
   permanent and checked first — poweroff semantics unchanged.
2. `sampler.c` `sampler_set_active(false)` path: after `atomic_set(&sampler_active, 0)`, call
   `gnss_producer_cancel()` (guard with `#if defined(CONFIG_GNSS_PRODUCER)` — sampler already
   includes it). `sampler_set_active(true)` needs no change (start clears the latch).
3. Pure core `sampler_run_cycle` unchanged — `-ECANCELED` already exits without a record. Verify the
   race: cancel landing between cycles is absorbed at the loop-top `sampler_active` check; cancel
   landing after `gps_on` but before `wait_fix` is caught by the post-take re-check. Add the
   loop-top check comment.
4. **Rider (A8, decide-and-do):** cadence semantics. Recommended: keep interval-gap behavior, but
   document it in `docs/adr/0003` + `sampler.h` ("period = acquisition + interval"). If Vincent wants
   fixed-period instead: anchor `next_deadline = cycle_start + interval` and
   `k_sem_take(&sampler_wake, K_TIMEOUT_ABS_MS(next_deadline))`. Ask once; don't invent.

**Files:** `src/gnss/gnss_producer.{c,h}`, `src/tracking/sampler.c`, `docs/adr/0003` (rider),
`tests/unit/test_gnss_producer`, `tests/unit/test_sampler`.

**Blast radius:**
- `gnss_producer_start|gnss_producer_stop|gnss_producer_wait_fix` → 14 hits in src, 9 files incl.
  tests (agnss_shell.c and gnss_shell.c also call start/stop — cancel must not break bench flows).
- `sampler_set_active|sampler_stop_sync|sampler_trigger_now` → 11 hits in src, 4 files.

**Tests:**
- Unit `tests/unit/test_gnss_producer`: `test_cancel_wakes_wait_fix`,
  `test_cancel_cleared_by_next_start`, `test_shutdown_still_permanent_after_cancel`.
- Unit `tests/unit/test_sampler`: existing cancel-path cases stay green (core untouched).
- HIL: from ACTIVE mid-acquisition (`sampler status` shows in-cycle) send `sm event sleep 60`; assert
  in logs GPS powers off within ~1 s (not `gps_acq_timeout_s`) and **no record enqueues after SLEEP
  entry** (`data_queue count` stable). PPK2 spot-check if bench rigged.

**Done when:** unit suites green; HIL shows prompt GPS-off on SLEEP; poweroff HIL long-press cycle
(existing) still reaches ~23 µA.
**Size:** S/M.

---

## Slice 3 — Drain robustness: poison records, ack rc, partial-drain semantics (B1/DR-01, B9/DR-41+DR-42)

**Design:**
1. **Error taxonomy first** (`lte_transport.c` `do_upload`): map HTTP status → distinct returns:
   2xx→0; 4xx (except 408/429)→`-EBADMSG` (permanent, server rejected the payload); everything else
   (transport err, 5xx, 408/429, incomplete accum)→`-EIO` (transient). `imei_valid` fail stays
   `-EAGAIN`, busy stays `-EBUSY`.
2. **uploader_drain** (`uploader.c`): on `-EBADMSG` from `attempt`: LOG_ERR with batch size, **ack the
   batch anyway** (drop poison), increment a `dropped_batches` counter (expose via
   `uploader_service.h` getter for shell/HIL), continue the loop. On `-EIO`: break (today's behavior).
   On `-EAGAIN`/`-EBUSY`: break WITHOUT feeding failure to policy (DR-43 rider — see step 4).
3. **DR-41:** `if (io->ack(n) != 0) { LOG_ERR(...); break; }` — ack failure = drain failure.
4. **DR-42 + DR-43:** make `uploader_drain` return a tri-state
   (`DRAIN_IDLE/DRAIN_PROGRESS/DRAIN_BLOCKED`) or simplest honest form:
   `ok = any_acked && io->pending() == 0`. Update `sync_engine.c` result feed; keep `-EAGAIN/-EBUSY`
   out of `sync_policy_on_result(false)` (skip, retry next tick). Preserve the engine's documented
   contract asserts.
5. **Rider (A10 doc):** either bench-verify the server accepts `{i,t,b,c,p}`-only records (preferred,
   see unknowns U1) or drop no-fix records at the collector; and update `docs/architecture.md` to
   describe encode-at-capture timestamps (back-dating never built).

**Files:** `src/transport/lte_transport.c`, `src/upload/uploader.{c,h}`,
`src/upload/uploader_service.c`, `src/sync/sync_engine.{c,h}`, `docs/architecture.md`.

**Blast radius:**
- `uploader_drain|uploader_assemble` → 6 hits in src; files: uploader.{c,h}, uploader_service.{c,h} +
  test_uploader, test_batch_envelope.
- `attempt(` via `transport_if` → 3 impl/caller sites (uploader.c, lte_transport.c,
  lte_transport_shell.c); grep `->attempt\(|\.attempt =` to confirm before changing the contract.
- `sync_policy_on_result` → grep, ~4 hits (sync_engine.c + tests).

**Tests:**
- Unit `tests/unit/test_uploader`: `test_4xx_batch_is_dropped_and_acked`,
  `test_ack_failure_stops_drain`, `test_eagain_does_not_count_as_failure`.
- Unit `tests/unit/test_sync_engine`: `test_partial_drain_engages_backoff` (batch1 ok, batch2 -EIO →
  policy failure), existing cadence tests updated to the tri-state/`pending==0` semantics.
- Unit `tests/unit/test_sync_policy`: unchanged (policy API untouched).
- HIL: `tests/hil/test_transport.py` extended — force acq-timeout records (GNSS_SIM scenario "none" or
  indoor), full drain returns HTTP 200 (U1); if server rejects, assert the drop path clears the queue.

**Done when:** all three unit suites green; HIL drain of a no-fix queue either succeeds or
demonstrably drops-and-proceeds; backoff engages on partial failure in unit test.
**Size:** M.

---

## Slice 4 — Queue lifecycle: compaction + overflow policy + peek contract (B2/DR-14+DR-15, B8/DR-47)

**Design:**
1. **Compaction (DR-14):** in `data_queue_ack`, after meta update, if `ack_count == total_records`
   (fully drained): `fs_unlink(DATA_FILE)` + zero meta + `save_meta()` under the already-held
   `queue_lock`. Cheap, keeps append-only model. (`data_queue_init` already reconciles a missing file.)
2. **Overflow (DR-15) — decision required (U2):** either implement delete-oldest (advance
   `ack_file_offset` past the oldest unacked record — same `zcbor_any_skip` walk as ack — before
   append), or keep reject-newest and fix `docs/architecture.md:291`. Recommend delete-oldest: the
   newest fixes are the product-valuable ones. Note interaction: dropping unacked records shrinks
   `pending` while the uploader holds peeked aliases — see 3.
3. **Peek contract (DR-47):** document in `data_queue.h`: "entries alias an internal buffer, valid
   until the next `data_queue_*` call, single consumer". Make `data_queue_shell` peek/decode refuse
   while uploader mode == SEND (query `uploader_service` getter, weak-linked or Kconfig-guarded), or
   copy into a shell-local buffer.

**Files:** `src/data/data_queue.{c,h}`, `src/data/data_queue_shell.c`, `docs/architecture.md`.

**Blast radius:** `data_queue_ack|data_queue_peek|data_queue_pending_count|data_queue_enqueue|data_queue_clear`
→ 18 hits in src, 9 files (collector, uploader_service, shells, tests).

**Tests:**
- Unit `tests/unit/test_data_queue`: `test_full_drain_compacts_file` (fs_stat size returns ~0 after
  N enqueue/drain cycles), `test_overflow_<chosen-policy>` (fill to MAX_RECORDS, enqueue one more:
  assert oldest gone + newest peekable, or -ENOMEM per decision), `test_meta_survives_compaction`.
- HIL: soak-lite — loop `collector sample` + `transport test`/drain 30×, `fs_stat` the data file via
  `fs_list`, assert bounded.

**Done when:** unit suite green incl. new cases; file size bounded across drain cycles on bench.
**Size:** M.

---

## Slice 5 — Command channel hardening (B3/DR-30+DR-31, A5, DR-66)

**Design:**
1. **DR-30 (decision U3, recommend ADR semantics):** `id < last_id` → re-ack
   `{id, COMMAND_STATUS_SUCCESS?}`… careful: ADR 0005 says "id ≤ last_id → keep acking". Implement:
   `if (id < last_id) { set_ack(id, last_status); LOG_WRN(...); return; }` so a server DB reset
   doesn't brick the channel; update `test_older_id_ignored` to the new contract and rename it.
   Alternative (if Vincent prefers): keep ignore + add a `cmd reset` shell maintenance hook. Ask once.
2. **DR-31:** make `save_last` return int (`command_service.c` already gets rc from
   `settings_save_one`); in `command_submit`, on persist failure: do NOT execute, `set_ack(id,
   COMMAND_STATUS_FAILED)`, do NOT advance `last_id` (server retries later — no reboot loop).
3. **A5 allowlist:** narrow `"led"` → `"led blink"` in `cmd_allow[]` (`command_service.c:37`). Add a
   startup sanity pass (behind `CONFIG_ASSERT` or a HIL shell cmd `command allowcheck`) that each
   allowlist verb's first word resolves via `shell_cmd_get`/root lookup — catches the
   "shell module dropped, command silently Fail-acks" trap. Mark `led_shell.c` header + Kconfig help
   as production-required-by-server-blink (or register a minimal `led blink` under TRACKER_COMMAND).
4. **DR-66 (U4):** confirm `lc` wire width with the boss; if int64 allowed, widen
   `batch_envelope_ack.lc` and `cbor_put_int` to 64-bit; else keep truncation + comment the contract.

**Files:** `src/command/command.c`, `src/command/command_service.c`,
`tests/unit/test_command/src/main.c`, (`src/transport/batch_envelope.{c,h}` if U4 says widen).

**Blast radius:**
- `command_pending_ack|command_on_no_command|command_submit` → 10 hits in src, 7 files.
- `cmd_allow|line_allowed` → 8 hits, 1 file (self-contained).

**Tests:**
- Unit `tests/unit/test_command`: `test_older_id_reacks` (replaces test_older_id_ignored),
  `test_persist_failure_blocks_execution_acks_failed`, existing idempotency/truncation cases green.
- Unit: extend the allowlist cases (in test_command or a new test_command_service):
  `led rgb` rejected, `led blink` allowed, `sm event button` still rejected.
- HIL: `command inject '{"cmd":{"id":N,"tp":"led","pl":"rgb 0 0 0"}}'` → ack Failed;
  `"tp":"led","pl":"blink"` → Success + LED locate pattern.

**Done when:** unit green with the new contract; HIL inject paths behave; boss decision on U3/U4
recorded in ADR 0005.
**Size:** M.

---

## Slice 6 — Clock/begin-alarm race pack (B4/DR-32+DR-33+DR-34)

**Design:**
1. **DR-32:** generation-checked re-arm. Add `uint32_t arm_gen` under `lock`; `clock_arm_begin`
   increments it; `date_time_evt_handler` snapshots `{begin, gen}`, and the re-arm path re-takes the
   lock and aborts if `gen` changed. (Or fold the recompute into `clock_arm_begin` with the lock held
   across decision+start — but `clock_begin_eval` reads the clock, keep that outside.)
2. **DR-33:** in `tracker_effects.c` `post()`: log on failure; for `EV_BEGIN_REACHED` specifically,
   have `clock.c` keep `alarm_outstanding=true` when the callback reports failure — change
   `clock_alarm_cb_t` to return int (posted/failed) and re-arm a short retry (e.g. 1 s k_timer) on
   failure. Small contract change: 2 implementers (tracker_effects, test_clock fakes).
3. **DR-34:** add `clock_cancel_begin()` (stop timer + clear `alarm_outstanding` + bump gen under
   lock); call from the SM clear-begin path — cleanest as part of the `sm_clear_begin` helper from
   slice 1 via a new effect or directly in `fx`-land (`tracker_effects.c` owns clock calls; add
   `cancel_begin_timer` to the effects struct alongside `arm_begin_timer`).

**Files:** `src/clock/clock.{c,h}`, `src/state/tracker_effects.c`, `src/state/tracker_sm.{c,h}`
(effect addition), `tests/unit/test_clock`, `tests/unit/test_tracker_sm`.

**Blast radius:** `clock_arm_begin|clock_cancel` → 3 hits in src (clock.c, tracker_effects.c) +
test_clock; `alarm_outstanding` internal to clock.c.

**Tests:**
- Unit `tests/unit/test_clock`: `test_stale_sync_rearm_does_not_clobber_newer_begin` (arm B1 deferred,
  arm B2, simulate sync recompute of B1 → timer targets B2), `test_cancel_begin_stops_fire`,
  `test_failed_post_keeps_alarm_outstanding_and_retries`.
- Unit `tests/unit/test_tracker_sm`: `test_clear_begin_cancels_timer_effect`.

**Done when:** both suites green; no spurious EV_BEGIN_REACHED after cancel in HIL
(`sm event begin <future>` → `sm event clearbegin` → wait past begin → state stays ACTIVE, log clean).
**Size:** M. Pairs well immediately after slice 1 (same files).

---

## Slice 7 — Deslop: shrink filesystem.c, delete gps.c, kill dead EPO API (A3/DR-51, A4/DR-48, DR-25)

Pure Flow-3 refactor slice — no behavior change intended; do after slices 1–6 so it never blocks a fix.

**Design:**
1. **filesystem.c** (A3): keep `filesystem_init/uninit` + DT-chosen mount + `filesystem_format` fixed
   to unmount→mkfs→remount under `fs_mutex`; replace the `#else &lfs_storage_mnt` with
   `BUILD_ASSERT(DT_NODE_EXISTS(FILESYSTEM_PARTITION_NODE), "set the nrfmodule,fs chosen node")`.
   Port `epo_storage.c`'s wrapper calls (grep `filesystem_` in it) to direct `fs_*` under its existing
   `epo_file_mutex`; then delete the unused wrapper fns + `END_OF_BUFFER/END_OF_FILE` from
   filesystem.h (keep whatever `filesystem_shell.c`/`test_filesystem` still exercise, or port those
   too). Update `tests/unit/test_filesystem` to the surviving API (add `test_format_remounts`).
2. **gps.c** (A4): delete `src/gps.c` + the CMake line. Port the fix-print diagnostic into
   `gnss_shell.c` if wanted (`gnss fix` already exists — check first). Verify EPO bench flows fully
   covered by `agnss_shell.c` (`agnss status|apply|receiver|refresh`) + `test_agnss_epo.py`. Grep
   `epo_read_packet|epo_data_check|epo_get_` → 36 hits, 5 files — after deletion only agnss files
   remain.
3. **DR-25:** delete `epo_is_valid/epo_is_update_needed/epo_force_update_flag` (+`epo_delete_file`
   unless factory_reset claims it), the root-Kconfig `EPO Configuration` menu
   (`EPO_VALIDITY_MARGIN_HOURS`), and any `EPO_FORCE_DOWNLOAD_FOR_TESTING` remnants. Move the root
   `USB` menu into `src/system/` or filesystem Kconfig while there (A9).

**Files:** `src/filesystem/filesystem.{c,h}`, `src/filesystem/filesystem_shell.c`,
`src/agnss/epo_storage.{c,h}`, `src/gps.c` (delete), `CMakeLists.txt`, `Kconfig`,
`tests/unit/test_filesystem`, `tests/unit/test_agnss`.

**Blast radius:** `filesystem_` → 25 hits in src, 5 files (all named above). gps.c symbols are
file-local except shell commands (grep `cmd_gps` → gps.c only).

**Tests:** `tests/unit/test_filesystem` (updated), `tests/unit/test_agnss`, `tests/unit/test_fs_access`
all green; full `west build -b livetracker/nrf52840` links (the real deletion test);
HIL `tests/hil/test_agnss_epo.py` green (EPO flows intact); shell shows no `gps` root command.
**Done when:** build + suites green; `git grep lfs_storage_mnt` empty; LOC delta strongly negative.
**Size:** M (mechanical but wide).

---

## Slice 8 — agnss policy edges (A6 riders: DR-21, DR-22, DR-26/B5, DR-08)

**Design:**
1. **DR-26/B5:** `sampler.c` `prod_gps_on`: only call `agnss_ensure_applied()` when
   `gnss_producer_start()` returned 0. Core: on any `gps_on() < 0` (not just -ESHUTDOWN) skip the
   wait loop; keep `sample()` + `gps_off()` + return `SAMPLER_CYCLE_TIMEOUT` for non-shutdown errors
   (always-send contract), `CANCELLED` only for -ESHUTDOWN.
2. **DR-21:** margin belongs to *refresh* only. `agnss_ensure_applied` checks the raw window
   (`now <= end`); `agnss_refresh` keeps `covers_now` (end − margin). Update the unit test that
   enshrines the old behavior.
3. **DR-22 (decision U5, recommend apply-anyway):** `now_unix()==-1` → in `ensure_applied`, skip the
   window check and apply if dirty (receiver validates internally; worst case a wasted upload);
   `refresh` with invalid clock → treat as stale (fetch allowed — modem up implies time will sync).
   Add explicit `-1` unit cases through both entry points (none of the 16 cover it).
4. **DR-08:** hold a dedicated apply-lock across the whole `epo_mtk_apply()` (not per-packet), and
   have the fs_mgmt FILE_ACCESS (start-of-write) hook set a transfer-in-progress flag that makes
   `ensure_applied` defer this cycle (`agnss_src_ble.c` registers FILE_ACCESS in addition to
   FILE_ACCESS_DONE, or extend `fs_access.c`'s existing hook — mind hook ordering with the allowlist).

**Files:** `src/tracking/sampler.c`, `src/agnss/agnss.c`, `src/agnss/epo_mtk.c`,
`src/agnss/agnss_src_ble.c`, `src/agnss/epo_storage.c`, `tests/unit/test_agnss`,
`tests/unit/test_sampler`.

**Blast radius:** `covers_now|margin` → 21 hits, 7 agnss files + test; `agnss_ensure_applied` → 3
call sites (sampler, agnss_shell, agnss.h).

**Tests:**
- Unit `tests/unit/test_sampler`: `test_gps_on_error_skips_wait_and_apply`.
- Unit `tests/unit/test_agnss`: `test_apply_within_margin_tail_still_applies`,
  `test_invalid_clock_applies_when_dirty` (per U5), `test_refresh_uses_margin`,
  `test_apply_deferred_while_transfer_in_progress`.
- HIL: `tests/hil/test_agnss_epo.py` (all 3 existing green) + re-run the BLE-push-during-apply case
  with short `gps_fix_interval_s` (DR-08 verify).

**Done when:** suites green; HIL EPO loop green incl. mid-apply push.
**Size:** M.

---

## Slice 9 — Extract the poweroff protocol + boot recipe (A7/DR-70; riders DR-37, DR-38)

Do after slices 1–8 (pure movement then).

**Design:**
1. New `src/system/power_off.c`: `power_off_execute(const struct power_off_steps *steps)` — ordered
   quiesce list (uploader quiesce → modem offline → sampler stop → gnss stop → sensors off → button
   release-wait → sense wipe → arm wake → `sys_poweroff`), each step injected (function pointers) so
   the sequence is unit-testable as a pure ordering property. `fx_poweroff` becomes a 5-line adapter
   building the production steps.
2. **DR-37 rider:** on the 10 s release timeout, do NOT arm-and-poweroff with the line active —
   abort: post a re-entry event (needs a small `EV_OFF_ABORTED`? simplest: re-post EV_BUTTON_LONG is
   wrong; prefer LOG + error LED + skip `sys_poweroff`, SM stays in OFF-zombie where a second
   long-press retries — that path already exists via `off_run`). Decide with Vincent if UX matters (U6).
3. **DR-38 rider:** re-check `usb_present()` immediately before `sys_poweroff`; if VBUS appeared,
   skip poweroff (same OFF-zombie fallback) and log.
4. Hoist `uploader_service_init()` + `sampler_start()` from `tracker_effects_init()` into `main()`
   with explicit ordering comments; `tracker_effects_init()` returns the vtable only.

**Files:** `src/system/power_off.{c,h}` (new), `src/state/tracker_effects.c`, `src/main.c`,
`tests/unit/test_power_off` (new).

**Blast radius:** `fx_poweroff` internals are file-local; `uploader_service_init|sampler_start` →
grep, 2 call sites each. `quiesce_wake_sources` local.

**Tests:**
- Unit `tests/unit/test_power_off` (new, qemu): step-order assertions with fakes
  (`test_uploader_quiesced_before_modem_offline`, `test_sampler_stopped_before_gnss_stop`,
  `test_abort_on_vbus_recheck`, `test_no_arm_while_button_held`).
- HIL: existing long-press cycle via `scripts/hil_cycle.py`; wake-cause log (`[OFF]` + button LATCH)
  intact; PPK2 floor ~23 µA if rigged.

**Done when:** boot-log ordering unchanged; long-press HIL cycle green; new unit suite green.
**Size:** M.

---

## Slice 10 — Boss BLE command surface (DR-12) + BLE resilience riders (DR-36, DR-50)

**Design:**
1. **DR-12:** one new file `src/command/boss_shell.c` (or extend `shell_commands.c`) registering the
   spec names as thin shell commands: `getid` → print `modem_lte_imei()`; `set delay <s>` → post
   `EV_SLEEP_CMD` (mirror `sm event sleep`); `check delay` → print SM state + remaining sleep (needs a
   `sleep_remaining` getter — add to tracker_effects via the k_timer remaining API); `get config` →
   arm config_sync (`config_sync_set_enabled` kick or a dedicated `config_sync_force()`);
   `send data` → `uploader_service_notify_config()`-style wake + log pending count; `blink` → alias
   `led blink`. Extend `cmd_allow[]` with the server-invocable subset (per-verb). Keep handlers
   ≤10 lines each — mapping only, no logic.
2. **DR-36:** `main.c` — log-and-continue past `ble_peripheral_init` failure (delete the `return err`;
   tracking must not die with BLE).
3. **DR-50:** `ble_peripheral.c` — make `adv_work` delayable; on `bt_le_adv_start` error,
   `k_work_reschedule(1–2 s)` backoff.

**Files:** `src/command/boss_shell.c` (new), `src/command/command_service.c` (allowlist),
`src/main.c`, `src/ble/ble_peripheral.c`, `CMakeLists.txt`, `src/command/Kconfig`.

**Blast radius:** additive; allowlist file self-contained (8 hits); `adv_work` local to
ble_peripheral.c.

**Tests:**
- Unit: allowlist additions in `tests/unit/test_command` (each new verb allowed; `sm event button`
  still rejected).
- HIL: `tests/hil/test_ble.py` extended — over NUS run `getid`, `set delay 60` (state→SLEEP),
  `check delay`, `send data`; DR-50: not HIL-forceable — review-verified.
- Manual/bleak: nRF Connect run-through of the boss command list.

**Done when:** every boss-spec command answers over NUS on bench; main survives a forced
`bt_enable` error (review + optional fault-injection build).
**Size:** M.

---

## Parallel infra slice (any time, independent) — CI + build variants (DR-17, DR-56)

1. `.github/workflows/build.yml` calling the manifest's `reusable-build.yml`
   (board `livetracker/nrf52840`, app-dir `.`) + a unit job running
   `scripts/run_test.py` over `tests/unit/*` (or twister `-T tests/unit -p qemu_cortex_m0`) in
   `ghcr.io/nrfmodule/nrfmodule-dev-manifest:latest`. Mind: workflow must `west init` per
   `reusable-ci.yml` conventions — copy the nrfmodule-core caller as template.
2. **DR-56:** gate `configs/hil.conf` behind a CMake env toggle (`HIL=1`, same pattern as GNSS_SIM,
   default ON for dev; demo/release builds set it off) — removes `sm event button` from the open NUS
   shell in shipped images. Verify server sleep/begin still work with it off
   (`TRACKER_SM_COMMAND` is independent — test exactly that in HIL).

**Tests:** a PR produces hex/bin artifacts + green unit job; local `HIL=0` build boots and serves
server sleep/begin (HIL test with the fragment off).

---

## Unknowns ledger (resolve before/while the slice that names them)

- **U1 (slice 3):** Does the AviRings server accept `{i,t,b,c,p}`-only (no `a`/`o`) DataDtos? HIL
  against staging decides drop-at-collector vs 4xx-drop policy. Owner: bench session.
- **U2 (slice 4):** Overflow policy — delete-oldest (doc'd) vs reject-newest (implemented). Boss/
  Vincent call; recommend delete-oldest.
- **U3 (slice 5):** `id < last_id` semantics — ADR 0005 re-ack vs current ignore. Vincent call;
  recommend re-ack per ADR.
- **U4 (slice 5):** AviRings `lc` wire width (int32 vs int64) — boss confirmation (known open item).
- **U5 (slice 8):** Invalid-clock apply policy — apply-anyway (recommended) vs explicit skip+log.
- **U6 (slice 9):** UX on button-held-past-timeout: abort-with-error-LED (recommended) vs wait
  indefinitely.
- **U7 (slice 2 rider):** Cadence semantics — document interval-gap vs implement fixed-period.
- **U8 (background):** L76 EPO retention across VBACKUP brown-out + PMTK707 epoch basis
  (DR-09 tail) — HIL-only; the guarded test `test_real_epo_receiver_reports_and_skips` needs
  `HIL_EPO_FILE=<real slice>`.
- **U9 (background):** `%PERIODICSEARCHCONF` exposure over the SLM bridge and socket-cancel→PSM
  behavior (architecture.md caveat, pre-existing).
- **U10 (infra):** Whether the CI Docker image (NCS v3.1.1 Python deps per manifest CLAUDE.md) builds
  this NCS v3.2.1 app — may need the image bump path in `infra/docker/`.
