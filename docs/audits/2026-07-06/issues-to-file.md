# Issue drafts — nRFTrackerFW architecture review 2026-07-06

Target repo for all: `nrfmodule/nRFTrackerFW`. The repo has **zero existing issues** (verified
`gh issue list --state all` 2026-07-06), so no dedupe conflicts. Provenance markers: NEW = not in
`demo_readiness_plan.md`; DR-xx = tracked there, filed here because nothing on GitHub tracks it.
File with `gh issue create -R nrfmodule/nRFTrackerFW -t "<title>" -b "<body>"`. No AI attribution.

---

## 1. SLEEP/WAIT_BEGIN cannot abort an in-flight GPS acquisition — L76 stays on up to gps_acq_timeout_s after pause

**Labels:** bug, power
**Provenance:** NEW (residual of DR-04 face (a); commit 3da9547 fixed only the poweroff faces b/c)

`sampling_set(false)` on SLEEP/WAIT_BEGIN entry only clears `sampler_active` and gives
`sampler_wake` — a cycle blocked in `gnss_producer_wait_fix()` (`fix_sem`) is not woken. The cancel
path built for poweroff is welded to the **permanent** `shutdown_latch` (`gnss_producer.c:18-21`,
never cleared), so it can't be used for pause.

Scenario: hub sends sleep mid-acquisition → L76 stays powered for the remaining acquisition budget
(`gps_acq_timeout_s`, runtime param, 10–600 s), then `d->sample()` **enqueues one more record while
nominally paused**, then GPS powers off. Hub-pause is a primary product state; it leaks up to 10 min
of GPS-on power per pause.

Fix sketch: add a resettable `cancel_latch` to gnss_producer (set by new `gnss_producer_cancel()` +
`k_sem_give(&fix_sem)`; cleared in `gnss_producer_start()`); call it from
`sampler_set_active(false)`. Pure core already handles `-ECANCELED` — no core change.
Files: `src/gnss/gnss_producer.{c,h}`, `src/tracking/sampler.c:185-194`.
Tests: `tests/unit/test_gnss_producer` (cancel wakes wait_fix; cancel cleared by next start),
HIL: `sm event sleep 60` mid-acquisition → GPS off within ~1 s, no post-SLEEP record.
Plan: `nrfmodule-dev-manifest/docs/audits/2026-07-06/trackerfw-opus-fix-plan.md` slice 2.

---

## 2. Begin/halt (startAt) not persisted — any reset boots ACTIVE; server `reboot` makes this routine

**Labels:** bug, priority
**Provenance:** DR-10 (still open on main d6ff34b; severity raised since #42/#43 made resets
server-invocable)

`tracker_sm_start()` zeroes the production ctx (`src/state/tracker_sm.c:360`) and nothing reloads a
persisted begin — the WAIT_BEGIN boot fork is dead code in production. Failure chain: server
schedules `begin <tomorrow 06:00>` → WAIT_BEGIN → server sends `reboot` (or battery swap/watchdog) →
boot → ACTIVE → tracker samples/uploads all night, battery dead before the race it was halted for.

Fix sketch: centralize the four `has_begin/begin_unix` mutation sites into two helpers; add a
`begin_persist(bool, int64_t)` effect (settings record like `cmd/last` in command_service.c);
preset the ctx from settings in main before `tracker_sm_start`. Keep persistence out of the pure SM.
Files: `src/state/tracker_sm.{c,h}`, `src/state/tracker_effects.c`, `src/main.c`.
Tests: `tests/unit/test_tracker_sm` (persist effect on set/clear; boot fork with preset begin);
HIL: `sm event begin <now+3600>` → `kernel reboot cold` → `sm state` = WAIT_BEGIN.
Plan: fix-plan slice 1 (do first).

---

## 3. Server-command allowlist over-grants `led`; `blink` depends on a shell module labeled "HIL visual tuning"

**Labels:** security, robustness
**Provenance:** NEW (same trap class as DR-11, which fixed it for `sm event` only)

Two issues in `src/command/command_service.c:31-43`:
1. `cmd_allow[]` entry `"led"` admits the whole subtree — a typo'd/hostile server command
   `led rgb 0 0 0` sets a manual override (`led_indicator_override`) that masks every status layer
   until another led command or reboot; `led off`/`led error` inject arbitrary indicator states.
2. The server `blink` command executes the shell line `led blink`, registered only under
   `CONFIG_TRACKER_LED_SHELL` — whose file header says "HIL visual tuning" (`src/led/led_shell.c:5`).
   Default y today, but a future production-shell slimming silently turns every server blink into a
   Failed ack. Nothing binds `cmd_allow[]` entries to the Kconfig symbols that register them.

Fix sketch: narrow `"led"` → `"led blink"`; add a startup/HIL check that each allowlist verb
resolves against the shell root; mark led_shell (header + Kconfig help) as production-required, or
register a minimal `led blink` under TRACKER_COMMAND.
Tests: allowlist unit cases (`led rgb` rejected, `led blink` allowed) in `tests/unit/test_command`.
Plan: fix-plan slice 5.

---

## 4. `prod_gps_on` runs agnss_ensure_applied() before checking gnss_producer_start rc — EPO upload fired at a dead/refused receiver

**Labels:** bug
**Provenance:** DR-26 (still open) + NEW poweroff-race angle

`src/tracking/sampler.c:91-100`: `prod_gps_on` calls `agnss_ensure_applied()` unconditionally after
`gnss_producer_start()`, before the pure core sees the rc. Consequences:
- Any `gps_on` failure (e.g. -EIO): a PMTK query (3 s timeout) + possibly a ~27 KB EPO UART upload at
  a powered-off receiver, then the cycle still burns the full `gps_acq_timeout_s` budget (DR-26).
- During long-press poweroff: a racing cycle gets `-ESHUTDOWN` from start, but ensure_applied still
  runs — UART traffic inside `sampler_stop_sync`'s 1 s window; the stop reports -ETIMEDOUT and
  teardown proceeds over a mid-write UART.

Fix sketch: gate `agnss_ensure_applied()` on `ret == 0`; in the core, on any `gps_on() < 0` skip the
wait loop (keep `sample()` + `gps_off()` + TIMEOUT for non-shutdown errors to preserve always-send).
Tests: `tests/unit/test_sampler` `test_gps_on_error_skips_wait_and_apply`.
Plan: fix-plan slice 8.

---

## 5. Retire the filesystem.c pass-through wrappers — keep mount/format only

**Labels:** refactor, tech-debt
**Provenance:** NEW (deletion-test verdict); contained bugs are DR-51 (still open)

`src/filesystem/filesystem.c` (391 LOC) fails the deletion test: its only production consumer is
`src/agnss/epo_storage.c` (grep `filesystem_` → 25 hits, 5 files; data_queue/usb_msc/log backend all
use `fs_*` directly). It carries the only legacy-hygiene defects left on main:
- `filesystem_format()` runs `fs_mkfs` on a mounted fs (stale in-RAM lfs state for a future
  factory_reset) — DR-51a.
- `fs_mutex` is decorative: `create_directory`/`list` bypass it — DR-51b.
- The `#else` fallback references undeclared `lfs_storage_mnt` → compile error on any board without
  the chosen node, undermining PR #49's retargetability — DR-51c.
- Half the API has zero callers; Waggi-era style (`END_OF_BUFFER`, commented-out code).

Fix sketch: shrink to `filesystem_init/uninit/format` (+ DT-chosen mount); format =
unmount→mkfs→remount under the mutex; `BUILD_ASSERT` instead of the `#else`; port epo_storage's five
wrapper calls to direct `fs_*` under its existing `epo_file_mutex`.
Tests: `tests/unit/test_filesystem` (updated, add format-remount case), `tests/unit/test_agnss`,
full livetracker build/link.
Plan: fix-plan slice 7. Note: keeps the "generalize in place, promote on demand" strategy — a smaller
blessed base for SDK promotion.

---

## 6. Delete src/gps.c — rival GNSS owner, superseded by agnss_shell

**Labels:** tech-debt
**Provenance:** DR-48 (still open); deletion case strengthened by #48's agnss_shell

`src/gps.c` (467 LOC, unconditionally compiled — `CMakeLists.txt:74`) registers a duplicate
`GNSS_DATA_CALLBACK` with shadow fix state, `LOG_MODULE_REGISTER(..., LOG_LEVEL_DBG)`, and
`gps on/off/rate/power` shell commands that drive PM actions underneath a live gnss_producer
acquisition. Its unique remaining value (EPO bench commands) is superseded by `agnss_shell.c`
(`agnss status|apply|receiver|refresh`). CONTEXT.md already declares it legacy.

Fix sketch: delete the file + CMake line; port any wanted fix-print diagnostics into `gnss_shell.c`;
verify EPO bench flows via `tests/hil/test_agnss_epo.py`.
Plan: fix-plan slice 7.

---

## 7. Sampler cadence is interval-between-cycles, not a fixed period — decide + document

**Labels:** design-decision, docs
**Provenance:** NEW (minor)

`src/tracking/sampler.c:165`: the inter-cycle wait (`gps_fix_interval_s`) starts after the cycle
ends, so effective period = acquisition time (2–60 s+) + interval. A server-set 30 s interval yields
32–90 s actual cadence depending on sky view — the operator's number silently isn't the record rate,
which matters for a product pitched on mid-race re-pacing.

Fix sketch (pick one): document interval-gap semantics in ADR 0003 + `sampler.h` + the API contract,
or anchor the next-cycle deadline at cycle start (`K_TIMEOUT_ABS_MS`).
Plan: fix-plan slice 2 rider (unknown U7).

---

## 8. architecture.md still describes unbuilt designs (timestamp back-dating; queue figures)

**Labels:** docs
**Provenance:** NEW (back-dating divergence) + DR-71 (doc staleness batch, still open)

The timestamp back-dating design (capture-uptime stored in the queue, resolve `t` at drain) was never
built — the shipped model is encode-at-capture (`src/collector/collector.c:159-165`): a no-fix record
before first clock sync omits `t` and the server stamps it at drain time, hours late in a coverage
gap (positions always carry GNSS UTC, so tracks are safe). Also still stale per DR-71: the 1 s/140k/
delete-oldest queue figures, the adaptive GPS power table, the "TLS" claim, and CONTEXT.md's
power-latch description (code is System OFF).

Fix sketch: one doc pass; state encode-at-capture + the no-fix/unsynced-clock caveat explicitly;
align queue figures with `CONFIG_DATA_QUEUE_MAX_RECORDS` and the slice-4 overflow decision.
Plan: fix-plan slices 3 (rider) + 4.

---
---

# Issue drafts — nrfmodule-core AT/concurrency audit 2026-07-06 (session B)

Target repo for all below: `nrfmodule/nrfmodule-core`. Dedupe check: `gh issue list
--state all --limit 100` on nrfmodule-core 2026-07-06 returned **zero issues** — all drafts
are new. Line references @ 59b7df8. Cross-refs: `core-threading-model.md` §7 (finding IDs
F1–F13) and `core-concurrency-fix-plan.md` (slice IDs S1–S8) in this directory.
File with `gh issue create -R nrfmodule/nrfmodule-core -t "<title>" -b "<body>"`. No AI attribution.

---

## C1 — Blocking AT from the system workqueue self-deadlocks the AT pipeline; core's own HTTP timeout path does it

**Labels:** bug, concurrency, critical (F1, slices S3+S4)

AT response parsing (`rx_process_work`), URC dispatch (`sm_monitor_work`, `at_monitor_work`)
and the end-of-command barrier (`sm_barrier_work`, `src/client/nrf_modem_at.c:249-251`) all
run on the system workqueue. Any blocking AT call issued *from* the sysworkq waits on
`at_rsp`, which can only be given by a work item queued behind it on the same thread:
guaranteed timeout (10 s default) plus a wedged sysworkq for the duration. With
`nrf_modem_at_sem_timeout_set(<0)` (K_FOREVER waits) it is a permanent deadlock.

**In-tree instance:** `src/client/http/nrfmodule_http.c` — `timeout_handler()` (sysworkq,
holds `http_mutex`, :152-173) → `cleanup_connection()` (:536) → `close_socket()` →
`nrf_modem_at_cmd("AT#XCLOSE=%d")` (:526). Every HTTP request timeout: wedges the sysworkq
~10 s (URC dispatch, DTR works, other consumers stall); the `AT#XCLOSE` always times out →
socket leaks; `http_mutex` is held across it so concurrent HTTP calls block too. HTTP
timeouts occur precisely when the network is bad — the worst moment to freeze URC/link-state
processing. The tracker's uploader and EPO downloads hit this path in the field.

**Prior art:** Waggi hit this class on the bench 2026-07-03 (livestream handshake publish on
sysworkq: 10 s wedge per handshake, RTT-captured) and fixed it with a dedicated
`sm_at_client_work_q` for RX+DTR work, deleting the barrier.

**Proposed fix:** dedicated AT-client workqueue owning `rx_process_work` + DTR works;
barrier submits to that queue; HTTP timeout work only flags state — the socket close moves
off the sysworkq (caller thread or deferred work), and `http_mutex` is never held across an
AT call.

---

## C2 — MQTT publish datamode window: command and payload are separate lock acquisitions; auto-sleep and any AT caller can inject into the payload

**Labels:** bug, concurrency, critical (F2, slice S6)

`nrfmodule_mqtt_publish()` (`src/client/mqtt/nrfmodule_mqtt.c:191-207`) sends
`AT#XMQTTPUB=...` via `nrf_modem_at_printf()` (lock acquired and **released**) then calls
`nrf_modem_at_datamode_send()` (lock re-acquired). After the `XMQTTPUB` OK, SLM is in
datamode and captures every byte until the `+++` terminator (verified against serial-modem
`sm_at_host.c` quit-string handling). In the gap and during the payload phase:

1. **Any other thread's AT command** wins `nrf_modem_at_lock` in the gap and its bytes
   become MQTT payload. Bench-proven class: Waggi observed `AT#XMQTTSUB` bytes as publish
   payload on the broker.
2. **Auto-sleep** (`go_to_idle_work`, `src/client/sm_modem_power_mgmt.c:115`) contends only
   on `txn_lock`, which is *free* in the gap and during `datamode_send` (that path never
   calls `txn_begin`/`ensure_awake`, `src/client/nrf_modem_at.c:427-452`): `AT#XSLEEP=2` is
   written mid-datamode — corrupted payload, sleep command swallowed, 5 s pm stall, then
   UART/DTR teardown racing the in-flight payload.

Also: `sm_at_client_send_data()` TX-ring writes can run concurrently with pm's
`sm_at_client_send_cmd()` with no common lock → interleaved TX bytes on the wire.

Tracker impact: none today (HTTP-only). Impact is on every MQTT/datamode consumer of the
SDK (product template, customers) and it blocks Waggi's de-vendoring.

**Proposed fix:** `nrf_modem_at_cmd_datamode(cmd, data, len)` executing both phases under a
single lock hold (port from waggi_v5, bench-validated, incl. `+++` quarantine on timeout);
publish switches to it; fold `txn_lock` into the single AT mutex so auto-sleep contends
with the real transaction. See `at-lock-api-recommendation.md`.

---

## C3 — Stale `at_rsp` semaphore + racy `sm_at_state` permanently desync command/response pairing after any timeout

**Labels:** bug, concurrency, high (F3, slice S2)

`src/serial_modem_client/sm_at_client.c`: `sm_at_client_send_cmd()` does not reset `at_rsp`
before sending (:915-952), and `sm_at_state` is a plain enum written by both the caller
(:924 PENDING, :947 ERROR-on-timeout) and the parser on the sysworkq (`parse_at_response`,
:253/:261).

Race: command A times out; between the caller's `k_sem_take` expiry and its
`sm_at_state = AT_CMD_ERROR` write, the response arrives — the parser sees PENDING, records
OK, **gives `at_rsp`**. Nobody consumes it. Command B sends and its `k_sem_take` returns
immediately on the stale give, reading a state that belongs to A (or still PENDING →
returned as positive `AT_CMD_PENDING`). B's real response later re-gives the sem for
command C. Every subsequent command reads its predecessor's completion — the bench-observed
"AT link wedged, even `AT+CFUN?` timing out" URC-desync signature. Late responses with
state != PENDING are additionally dispatched into the URC stream (`response_handler`
:315-322), contaminating monitors. Two concurrent `send_cmd` callers (possible via the
unlocked shell, issue C8) make the sem/state pair ambiguous immediately.

**Proposed fix:** `k_sem_reset(&at_rsp)` at command start (Waggi has this since 07-03);
`sm_at_state` → `atomic_t` with a CAS handshake (PENDING→final exactly once; the timeout
path CASes PENDING→ERROR and on losing the race consumes the give and returns the real
result); WRN-tag stale responses.

---

## C4 — Every URC is delivered twice to every AT_MONITOR handler (MON_ANY bridge + direct dispatch both active)

**Labels:** bug, urc, high (F4, slice S5)

Two parallel delivery paths exist for Nordic `AT_MONITOR` handlers:

- Path A: `SM_MONITOR(nrf_modem_at_mon, MON_ANY, ...)` (`src/client/nrf_modem_at.c:67-75`)
  forwards every notification to `at_monitor_dispatch` (hooked by NCS `at_monitor`'s
  SYS_INIT via `nrf_modem_at_notif_handler_set`), which heap-queues and dispatches on
  `at_monitor_work`.
- Path B: `sm_monitor_task` (`src/serial_modem_client/sm_at_client_monitor.c:185-195`)
  *also* iterates `at_monitor_entry` directly and calls the handlers.

`CONFIG_AT_MONITOR` is selected by the lte_lc/mqtt/modem_info/pdn client Kconfigs, so both
paths are active in every real build: lte_lc gets double CEREG/CSCON/MDMEV (duplicate
events to the app), MQTT consumers get double PUBLISH/CONNACK, and every notification is
heap-copied twice (doubling pressure on both `sm_monitor_heap` and `at_monitor_heap`).
Path B additionally ignores the `paused` and `direct` monitor flags — paused monitors still
fire.

Waggi hit the visible symptom (duplicate CONNACK → double-subscribe) and deleted the
MON_ANY bridge on 2026-07-03.

**Proposed fix:** delete the MON_ANY bridge; keep the direct path as the single dispatch and
honor `paused`/`direct`; keep `nrf_modem_at_notif_handler_set` as a no-op stub for
at_monitor's SYS_INIT.

---

## C5 — SDK `sm_modem_power_mgmt_txn_begin/end` invites ABBA deadlock; remove before v2.3.0 tags it into existence

**Labels:** bug, api, concurrency, high (F5, slice S6 — co-owned with nrfmodule-sdk)

Canonical internal lock order is `nrf_modem_at_lock → txn_lock`
(`execute_command_locked_ex`, `src/client/nrf_modem_at.c:231-243`). The SDK header
(`include/sm_modem_power_mgmt.h:82-95`) tells consumers to "bracket any wake+send that
bypasses send_at() between txn_begin()/txn_end()". A consumer following that advice and
calling `nrf_modem_at_*()` inside the bracket acquires `txn_lock → nrf_modem_at_lock` —
ABBA against every concurrent command: permanent deadlock under
`nrf_modem_at_sem_timeout_set(<0)`, ~11 s convoys otherwise. The alternative reading (raw
`sm_at_client_send_cmd` inside the bracket) bypasses AT serialization entirely and injects
into in-flight transactions. There is no correct external use. The API is also a bare void
lock pair (no timeout, no try variant, cross-thread pairing unenforced).

It is merged (sdk #14 / core #17) but **untagged**; no consumer calls it (tracker uses only
pause/resume/sleep; Waggi is vendored). v2.3.0 is the last point to remove rather than
deprecate.

**Proposed fix:** fold `txn_lock` into the single AT mutex (ADR-0002 model, HIL-proven in
waggi_v5); provide composite needs via `nrf_modem_at_cmd_datamode()` + callback-scoped
`nrf_modem_at_exclusive(fn, ctx, timeout)`; delete `txn_begin/end` from the SDK header in
the paired PR. Full analysis: `at-lock-api-recommendation.md`.

---

## C6 — `UART_RX_BUF_REQUEST` error path corrupts RX slab refcounts (`buf_unref` given the block pointer, not the data pointer)

**Labels:** bug, memory-corruption, high (F6, slice S1)

`src/serial_modem_client/sm_at_client.c:509-518`:

```c
case UART_RX_BUF_REQUEST:
    buf = buf_alloc();               /* struct rx_buf_t *     */
    ...
    err = uart_rx_buf_rsp(uart_dev, buf->buf, sizeof(buf->buf));
    if (err) {
        LOG_WRN("Disabling UART RX: %d", err);
        buf_unref(buf);              /* BUG: expects buf->buf */
    }
```

`buf_unref()` → `block_start_get()` computes
`((size_t)p - offsetof(struct rx_buf_t, buf) - rx_slab.buffer) / BLOCK_SIZE`. Passing the
block pointer instead of the member yields block `i-1` for block `i>0` (decrements a *live*
neighboring buffer's refcount → premature `k_mem_slab_free` → use-after-free of an
in-flight RX buffer) and an underflowed huge index for block 0 (`atomic_dec` on a wild
address). Trigger: `uart_rx_buf_rsp()` failing — exactly the RX teardown window (DTR sleep
entry / `rx_disable()` racing a buffer request). ISR context, silent corruption.

Waggi's vendored copy has the identical bug
(`waggi_modem/serial_modem_client/sm_at_client.c:540`) — fix both. Likely inherited from
the upstream Nordic sample this file derives from; worth an upstream check.

**Proposed fix:** `buf_unref(buf->buf)`; debug assert in `block_start_get()` that the
computed index is `< UART_SLAB_BLOCK_COUNT`.

---

## C7 — `handle_mqtt_msg` trusts URC-declared lengths: heap overread on truncated/split `#XMQTTMSG`

**Labels:** bug, memory-safety, medium-high (F7, slice S7)

`src/client/mqtt/nrfmodule_mqtt.c:75-137` parses `#XMQTTMSG: <topic_len>,<msg_len>` and
`memcpy`s exactly those lengths out of the URC chunk with no validation against the bytes
actually present. `sm_monitor_dispatch` splits chunks on newlines and URC-prefix heuristics
(`+`/`%`), so a payload containing newlines or `+`/`%`-prefixed lines *will* be fragmented —
the handler then reads past the chunk into adjacent heap and delivers garbage. Negative
lengths from a garbled header are unchecked (fed to `k_malloc(len+1)`/`memcpy`).
Additionally `k_malloc` in URC context fails silently under heap pressure (dropped inbound
messages), and `evt_cb` runs on the sysworkq — a consumer callback that blocks on AT
recreates issue C1.

Waggi's fork already carries the fix (static buffers + declared-vs-available bounds checks
+ negative-length rejection, `waggi_mqtt.c:124-198`), added after hitting it during
MQTT/livestream work.

**Proposed fix:** port the waggi hardening; document `evt_cb` context constraints in
`nrfmodule_mqtt.h`.

---

## C8 — `sm` shell and `smsh uart` bypass all AT locking and power management

**Labels:** bug, concurrency, medium (F8, slice S8)

`src/serial_modem_client/sm_at_client.c:1006-1014`: the `sm <at>` shell command calls
`sm_at_client_send_cmd()` directly from the shell thread — no `nrf_modem_at_lock`, no
`txn_lock`, no wake. Effects: injects a command into the middle of another thread's
transaction (or its datamode payload, C2); creates two concurrent waiters on the single
`at_rsp` sem (C3's ambiguity); if the modem is asleep, sends into a suspended UART.
`smsh uart disable` tears down UART/DTR regardless of an in-flight command.

Not a debug-only concern: the PPK2 power-measurement harness and bench flows drive the
device through this shell.

**Proposed fix:** route `sm` through `nrf_modem_at_cmd()` (locking + wake for free, same
output); `smsh uart` commands warn that they bypass PM state. Keep syntax identical for
bench scripts.

---

## C9 — Hardening batch: automatic-DTR races, `g_resp_buf` clear-vs-append, URC heap sizing, buffer/stack defaults, lock-free reset

**Labels:** bug, concurrency, medium (F9–F13, slice S8; reset item folds into S6)

Grouped smaller findings (full detail in `core-threading-model.md`):

1. **Automatic-DTR race (F9):** `tx_write()` calls `dtr_uart_enable()` inline on the caller
   thread while `dtr_uart_disable_work` may run concurrently on the sysworkq
   (`sm_at_client.c:371-376` vs :676-686); `dtr_config.active` is a plain bool also read in
   the RI ISR (:756-763). UART PM resume/suspend and rx enable/disable interleave
   unserialized. Tracker configs don't use automatic mode (PM owns DTR), but the mode is
   public API. Fix: `active` → atomic; single owner = the AT-client workqueue (enable via
   work submit, not inline).
2. **`g_resp_buf` data race (F10):** `sm_client_data_handler` appends via `strlen` on the
   sysworkq while callers zero `g_resp_buf[0]` under `nrf_modem_at_lock`
   (`nrf_modem_at.c:84-96`, :209, :240) — unsynchronized; URC bytes arriving between
   commands interleave into response parses. Fix under the S2/S6 restructure (accumulator
   owned by the AT client, cleared in the context that appends).
3. **URC heap (F11):** `sm_monitor_heap` is 1024 B, `K_NO_WAIT`
   (`sm_at_client_monitor.c:26`) — URC bursts silently drop notifications (missed
   CEREG/#XMQTTMSG). Kconfig the size (default 2048) + a drop counter. C4's fix halves the
   pressure.
4. **Defaults trap (F12):** UART RX buffering defaults to 256×3 = 768 B
   (`serial_modem_client/Kconfig:21-34`). At 115200 no-HWFC that is ~67 ms of headroom —
   Waggi lost AT responses to exactly this before raising to 2048×4. The tracker
   (921600+HWFC) is safe. Raise defaults or document the sizing rule next to the option.
   Also `PM_WORKQ_STACK_SIZE` 1024 (`sm_modem_power_mgmt.c:16`) is thin for its
   logging-heavy paths — bump to 2048 pending a thread-analyzer reading.
5. **Lock-free reset + stale pm state (F13):** `nrf_modem_lib_reset()`
   (`nrf_modem_lib.c:139-167`) cycles DTR and probes without any lock — concurrent commands
   see UART teardown mid-flight; after `AT#XRESET` the pm `modem_state` is not
   resynchronized and the global AT timeout is mutated non-atomically around probes. Fix:
   run the whole bracket inside `nrf_modem_at_exclusive()` (S6) and set
   `modem_state`/inactivity timer explicitly after a successful reset.

---
---

# Issue drafts — NCS-seam audit 2026-07-06 (session A)

Target repos: nrfmodule-dev-manifest, nrfmodule-sdk, nrfmodule-core. Dedupe check: `gh issue
list --state all --limit 100` on all three 2026-07-06 returned **zero issues**; also no overlap
with the session-B drafts above (different subjects — CI/manifest/board/vendoring vs
Tracker/concurrency). Cross-refs: `ncs-seam-inventory.md` (seams S1–S13),
`NCS_UPGRADE_PLAYBOOK.md`, `ncs-3.4-migration-plan.md` in this directory. Ordering = severity.
No AI attribution.

---

## A1. [nrfmodule-dev-manifest] reusable-ci.yml tests PR code against a stale personal prototype manifest (NCS v3.1.1), not this manifest

**Labels:** bug, ci, critical (seam S10)

`.github/workflows/reusable-ci.yml` (called by nrfmodule-core's `Library CI`) initializes the CI
workspace with:

```
west init -m https://github.com/V1incentC/test-premium-manifest
...
rm -rf modules/lib/test-modem-source
mv $GITHUB_WORKSPACE/pr_code modules/lib/test-modem-source
```

`V1incentC/test-premium-manifest` is the pre-migration prototype: it pins **sdk-nrf v3.1.1** and
pulls `test-company-sdk` / `test-modem-source` from the personal account (verified 2026-07-06 via
`gh api`). Consequences:

- Core PRs are twister-tested against **NCS v3.1.1**, while the ecosystem ships on v3.2.1
  (manifest `west.yml`). The Docker image was already fixed to v3.2.1 Python deps (`e59b9fa`,
  `2be851c`) — the workflow was not.
- The SDK the tests link against is a **stale personal snapshot** (`test-company-sdk@main`), so
  core↔sdk integration breakage is invisible. Recent green runs (verified `gh run list`,
  2026-06-24) verified the wrong stack.
- Green CI during any NCS bump verifies nothing about the new pin.

Fix:
1. `west init -m https://github.com/nrfmodule/nrfmodule-dev-manifest` (optionally a
   `manifest-ref` input for testing manifest branches).
2. Swap PR code into `modules/lib/nrfmodule-core`.
3. Add a `west list` echo step so tested revisions are visible in the log.

Acceptance: a no-op nrfmodule-core PR shows `sdk-nrf v3.2.1` and `nrfmodule-sdk main` in its CI
log and passes twister. Blocking precondition for the NCS 3.4 migration (plan Phase A.2).

---

## A2. [nrfmodule-dev-manifest] west.yml pins ncs-serial-modem to `revision: main` — floating dependency now 177 commits ahead, targeting NCS v3.4.0

**Labels:** bug, manifest, high (seam S9)

`west.yml`:

```yaml
- name: ncs-serial-modem
  remote: ncs
  path: ncs-serial-modem
  revision: main
```

Existing workspaces sit at `448cf99` (Feb 2026), but any fresh `west update` fetches upstream
`main` — now 177 commits ahead and pinning **NCS v3.4.0** (upstream `2ee3a42`) — into our v3.2.1
workspace. The module is not passive: its `zephyr/module.yml`, Kconfig, and `drivers/` are
processed by every workspace build, and the nRF52840 host DTS depends on its `nordic,dte-dtr`
binding (`nrfmodule-sdk/boards/arm/livetracker/livetracker_nrf52840.dts` node `dte_dtr`).
Upstream already renamed the binding file once (`9ac2dd5`); only the unchanged compatible string
saved existing builds.

Fix: pin to the revision matching the deployed modem FW line:

```yaml
  revision: 448cf99  # deployed serial-modem FW line; bump deliberately with FW deployments
```

Bump only as part of a deliberate modem-FW migration (`ncs-3.4-migration-plan.md`).

Acceptance: fresh `west init && west update` reproduces `448cf99`; `west list` stable across runs.

---

## A3. [nrfmodule-sdk] livetracker/nrf9151/ns board definition out of sync with deployed modem-FW UART config (115200/no-HWFC vs 921600+HWFC, RTS/CTS swapped)

**Labels:** bug, board, high (seam S11)

`boards/arm/livetracker/livetracker_nrf9151_ns.dts` defines uart2 as:

```dts
current-speed = <115200>;
/* hw-flow-control; */  /* Uncomment to enable RTS/CTS - also update pinctrl */
```

with header comments documenting RTS=P0.12 / CTS=P0.09. The deployed nRF9151 serial-modem
firmware is built with an **untracked** overlay (`d:/Root/serial_modem/boards/livetracker.overlay`)
at **921600 + hw-flow-control, RTS=P0.09 / CTS=P0.12** (deliberately swapped — electrically
correct pairing with the 52840's RTS P1.03/CTS P1.06). The host side (`livetracker_nrf52840.dts`
uart0) is already 921600+HWFC, so modem firmware built from this board definition today **cannot
talk to the tracker**. Interop truth currently lives outside version control.

Fix: set uart2 to 921600, enable `hw-flow-control`, correct pinctrl (uncomment, swap RTS/CTS) in
`livetracker_nrf9151-pinctrl.dtsi`, fix the header comment; retire the untracked overlay.

Acceptance: serial-modem FW built with `-b livetracker/nrf9151/ns` (no overlay) passes an AT
round-trip against a deployed tracker on the bench. Precondition for modem-FW migration work
(playbook Phase 0.4).

---

## A4. [nrfmodule-core] Vendored sm_at_client missing upstream bounds-clamp and RX-recovery fixes

**Labels:** bug, vendored-code, high (seam S1; complements session-B drafts C3/C6/C9 which cover
*original* bugs in the same file — this one covers *upstream* fixes we never pulled)

`src/serial_modem_client/sm_at_client.c` is a diverged copy of `ncs-serial-modem/lib/sm_at_client`.
Upstream fixes to take at the current NCS pin (independent of any NCS bump):

- `d915d10` — clamp copy length to remaining buffer capacity in `response_handler()`. Our copy
  still does an unclamped `memcpy` guarded only by `assert()` (compiled out in release); a URC
  burst against a nearly-full response buffer can overflow `at_cmd_resp`.
- `f34c54a` family — clear `SM_AT_CLIENT_RX_ENABLED_BIT` in the `UART_RX_DISABLED` event and
  tolerate `-EBUSY` in `rx_enable()`. Without these, RX recovery can wedge after an unexpected
  UART disable (state bit says enabled, hardware is not).
- Upstream now gates `sm_monitor_dispatch()` on the buffer ending in `\r\n` before dispatching
  URCs — directly relevant to our URC-contamination bug class. Behavior change: take deliberately
  with tests, not as a blind copy.

Approach: three-way merge (`git diff 448cf99..<upstream> -- lib/sm_at_client/sm_at_client.c`
applied onto our copy), preserving local divergence (renamed `NRFMODULE_SM_AT_CLIENT_*` Kconfig,
`sm_monitor_*` symbols, DTR/RI extensions). Note upstream renamed
`sm_at_client_configure_dtr_uart(bool, t)` → `sm_at_client_automatic_dtr_uart(t)` — decide
adopt-vs-keep and align `nrf_modem_at.c` + `nrfmodule-sdk/include/sm_at_client.h`. Coordinate
with the session-B concurrency slices (S1/S2) so the merges don't collide.

Acceptance: link clean; HIL: multi-URC dispatch, XSLEEP sleep/wake soak, RX-recovery after forced
UART error. Migration plan Phase A.5.

---

## A5. [nrfmodule-core] pdn_client.cmake references nrf/lib/pdn, which is removed in NCS v3.4.0

**Labels:** upgrade-blocker, medium (seam S6)

`src/client/pdn_client.cmake` compiles `${NRF_DIR}/lib/pdn/pdn.c` (+ `esm.c`) when
`CONFIG_NRFMODULE_PDN=y`. The standalone PDN library is deprecated today and **removed in NCS
v3.4.0** (release notes: "Removed the deprecated PDN library"; `lib/pdn` absent from the v3.4.0
tree — verified). Any consumer enabling `NRFMODULE_PDN` fails at CMake configure after the bump
with a path error instead of guidance.

Fix (can ride in the NCS 3.4 port PR; tracked so it isn't forgotten):

```cmake
if(CONFIG_NRFMODULE_PDN)
    message(FATAL_ERROR "NRFMODULE_PDN was removed with NCS 3.4. Use CONFIG_LTE_LC_PDN_MODULE instead.")
endif()
```

plus matching Kconfig help text. Verify no product sets `NRFMODULE_PDN` (grep prj.conf across
repos).

Acceptance: default builds unaffected; enabling `NRFMODULE_PDN` produces the guidance message.

---

## A6. [nrfmodule-sdk] Default west.yml still pins sdk-nrf v3.1.1 — standalone SDK consumers get an untested NCS

**Labels:** bug, manifest, medium (seam S9)

`nrfmodule-sdk/west.yml` (the "default recommended version" for customers who `west init`
directly from the SDK repo) pins `sdk-nrf` at **v3.1.1**, while the ecosystem develops and tests
on v3.2.1. The stale default is only masked when initializing from nrfmodule-dev-manifest (whose
sdk-nrf entry is listed first and wins import precedence). Standalone SDK consumers build against
an NCS a full minor behind what we test.

Fix: bump to `v3.2.1`; keep it in lockstep with the manifest pin going forward (playbook
Phase 4.3 makes this a standing upgrade step).

Acceptance: fresh `west init -m https://github.com/nrfmodule/nrfmodule-sdk && west update`
fetches the same NCS the manifest pins.

---

## A7. [nrfmodule-sdk] SDK has no CI — changes are never built or tested by automation

**Labels:** ci, medium (seams S8/S10)

`nrfmodule-sdk/.github/` contains no workflows. SDK changes (board DTS, public headers, LED/BMP390
libs, the source-vs-binary auto-detect CMake) merge with zero automated build coverage;
integration breakage surfaces only via nrfmodule-core CI (currently mis-pointed, see A1) or a
developer workspace.

Minimum viable CI, reusing manifest infrastructure:
1. `reusable-lint.yml` wrapper (shared quality gate already supports this).
2. Build job: init the real manifest workspace, swap PR code into `modules/lib/nrfmodule-sdk`,
   run SDK unit tests (`tests/led_effect`, `tests/led_arbiter` via twister/qemu) + one product
   smoke build (`livetracker/nrf52840`).
3. Optional but valuable: binary-mode link check (`libmodem_core.a` fallback) — currently
   exercised by nothing anywhere.

Acceptance: an SDK PR that breaks a board DTS or public header fails CI before merge.

---

## A8. [nrfmodule-dev-manifest] Docs claim the Docker image installs NCS v3.1.1 Python deps — stale since the v3.2.1 image fix

**Labels:** docs, low

`CLAUDE.md` ("All CI runs in Docker container ... NCS v3.1.1 Python deps") predates
`e59b9fa`/`2be851c`, which moved `infra/docker/Dockerfile` to `west init --mr v3.2.1` for its
requirements install. The stale claim sends CI auditors down the wrong path (the *actual*
remaining skew is `reusable-ci.yml`, issue A1). Also stale: `reusable-ci.yml`'s inline comment
"Download everything (NCS v3.1.1 + Your Libs)" and `nrfmodule-product-template`'s west.yml
comment "brings in NCS v3.1.1".

Fix: one doc-sweep commit updating CLAUDE.md + the workflow comment (or fold into A1's rewrite),
plus a one-line PR to nrfmodule-product-template.

Acceptance: `grep -ri "3\.1\.1"` across manifest + product-template returns only
changelog/history context.

---

*Session A items not filed as issues (tracked in the migration plan instead):*
`lte_lc_client.cmake` condition-model drift + missing `cellular_profile.c` (pure port work,
playbook Phase 3.2 — not a defect at v3.2.1); `libmodem_core.a` regeneration procedure (open
question for Vincent — needs a product decision on binary distribution before it's actionable).
