# nrfmodule-core concurrency fix plan (sliced, for Opus)

Date: 2026-07-06. Targets nrfmodule-core @ 59b7df8 + nrfmodule-sdk @ ccbfd5c.
Findings F1–F13 per `core-threading-model.md` §7; issue drafts in
`issues-to-file.md`. Order = risk reduction per unit of review effort, with
structural dependencies respected. Each slice is one PR, reviewable alone,
tests pass after each. **Slices 4+6 must land before tagging v2.3.0** (S6
changes the SDK surface; shipping the txn API then removing it is a breaking
minor-to-major mistake).

Consumers for blast-radius purposes:
- **Tracker** (nRFTrackerFW): builds core from source via the SDK; uses
  `nrf_modem_at_printf/cmd/cmd_raw/scanf`, `nrfmodule_http`, pm
  pause/resume/sleep, the `sm` shell on the bench (PPK2 harness). No MQTT, no
  datamode, no txn_begin/end.
- **Waggi** (waggi_v5): vendored fork of the whole client stack
  (`modules/waggi_modem`). Core changes do NOT flow automatically; each slice
  notes whether Waggi already has the equivalent (convergence credit) or needs
  a port.

Verification infra available: unit tests via
`nrfutil toolchain-manager launch --ncs-version v3.2.1 -- python scripts/run_test.py tests/unit/<dir>`
(qemu_cortex_m0; use m3 for anything time-based — m0 clock freezes under
QEMU), HIL via nRFTrackerFW `scripts/hil_cycle.py` (COM57, J-Link; force
`kernel reboot cold`), product-template build for MQTT paths.

---

## S1 — Fix `buf_unref(buf)` slab-pointer corruption (F6)

**Change**: `sm_at_client.c` `UART_RX_BUF_REQUEST` error path:
`buf_unref(buf)` → `buf_unref(buf->buf)`. Consider a debug assert in
`block_start_get()` that the computed block index is `< UART_SLAB_BLOCK_COUNT`.

**Risk of change**: near zero (one line, error path).
**Blast radius — tracker**: none functional; removes a memory-corruption
landmine hit when `uart_rx_buf_rsp()` fails during RX teardown (every
sleep-entry DTR window is a candidate).
**Blast radius — Waggi**: same bug present verbatim in
`waggi_modem/serial_modem_client/sm_at_client.c:540` — port the same line.
**Verification**: unit-test `block_start_get` math with both pointer kinds if
practical; otherwise HIL sleep/wake soak (100 cycles via hil_cycle) with
`CONFIG_ASSERT=y` — pre-fix corruption is silent, so rely on the assert.

## S2 — Command/response handshake hardening (F3, part of F10)

**Change** (`sm_at_client.c`):
1. `k_sem_reset(&at_rsp)` at the top of `sm_at_client_send_cmd()` before
   setting state (Waggi's fix).
2. Make `sm_at_state` an `atomic_t` and define the ownership handshake:
   caller sets PENDING before TX; parser transitions PENDING→final exactly
   once (atomic_cas), gives sem only on a successful transition; caller's
   timeout path does atomic_cas(PENDING→ERROR) — if it loses the race, the
   response arrived: consume the pending give (`k_sem_take(K_NO_WAIT)`) and
   return the parsed state instead of a timeout.
3. Late responses (state != PENDING) keep flowing to `sm_monitor_dispatch`
   but get logged at WRN with a `stale-response` tag so bench logs make the
   desync visible instead of silent.

**Risk**: low-medium — touches the hot path; the CAS handshake needs care.
**Blast radius — tracker**: fixes the bench-observed "AT link wedged, even
AT+CFUN? timing out" URC-desync class (off-by-one response pairing after any
timeout). No API change.
**Blast radius — Waggi**: has the `k_sem_reset` fix already; the CAS
handshake is an improvement to port later (their `sm_at_state` is also plain).
**Verification**: new unit suite for the handshake with a fake `tx_write`
(inject late/duplicate terminator sequences); HIL: force a wake timeout
(unplug 9151 / drop DTR) then confirm the next command returns its own
response, not the stale one.

## S3 — Dedicated AT-client workqueue (F1a)

**Change** (`sm_at_client.c`, `nrf_modem_at.c`): port Waggi's structure —
private `sm_at_client_work_q` owns `rx_process_work`,
`dtr_uart_enable/disable_work`; the end-of-command `sm_barrier_work` is
submitted to that queue instead of the sysworkq. `sm_monitor_work` (URC
handler dispatch) STAYS on the sysworkq (handlers are consumer code;
isolating parse is what removes the self-deadlock). Kconfig for stack size
(Waggi uses 2048; default 2048, mirror their sizing note).

**Rule change this enables**: blocking AT from the sysworkq stops being a
guaranteed self-deadlock (parse no longer depends on sysworkq); it remains
*discouraged* (stalls other sysworkq users). URC handlers still must never
block on AT — that now deadlocks against the *sysworkq's own* `sm_monitor_work`
only if the AT path needs URC progress (it doesn't) — i.e. it degrades from
deadlock to stall. Update THREADING_MODEL U1/U2 accordingly when landing.

**Risk**: medium — changes scheduling of the entire RX path; +1 thread,
+~2 KB RAM.
**Blast radius — tracker**: DTR wake timing improves (enable work no longer
queued behind app sysworkq items); barrier no longer exposed to app sysworkq
stalls. Watch: work items that assumed sysworkq serialization with consumer
work — none found in core, but re-check `rx_recovery` vs `rx_disable`
interleavings (they relied on same-queue serialization; the disable spin-wait
now actually spins — verify it exits).
**Blast radius — Waggi**: already has it (their fix is the reference);
convergence credit — core moves toward the fork, diff shrinks.
**Verification**: HIL AT storm (two threads issuing commands at 10 Hz while
`sm` shell polls) + sleep/wake soak; regression: `smsh uart auto` inactivity
path; RAM/stack report (thread_analyzer on debug build).

## S4 — HTTP timeout path off the blocking-AT-on-sysworkq pattern (F1b)

**Change** (`nrfmodule_http.c`): `timeout_handler` must not call
`close_socket()` (blocking AT) on the sysworkq, and must not hold `http_mutex`
across it. Reshape: timeout work marks `ctx.state = HTTP_STATE_ERROR` +
signals the requesting thread (the request path already polls/blocks on
responses); the socket close happens on the *caller's* thread in the request
teardown, or on the S3 workqueue as a deferred close work item. User
`response_cb` for the timeout fires from the caller thread, not sysworkq.

**Risk**: medium — HTTP state machine edges (timeout-vs-completion race is
currently "handled" by the mutex; keep the state CAS).
**Blast radius — tracker**: direct — the tracker's uploader and A-GNSS/EPO
HTTP downloads hit timeouts on flaky links; today each timeout wedges the
sysworkq ~10 s and the `AT#XCLOSE` always fails (socket leaks until next
request's `-EBUSY`/reopen). After: closes actually succeed, no wedge.
**Blast radius — Waggi**: n/a (no `nrfmodule_http`; their HTTP is
socket-based EPO chunking in app code).
**Verification**: unit: fake a timeout with response never arriving; assert
close issued from non-sysworkq context and state returns to IDLE. HIL:
airplane-mode the modem mid-download (or point at a black-hole IP), confirm
timeout → next request succeeds; watch sysworkq latency via thread analyzer.

## S5 — Single URC dispatch path (F4, enables F11 relief)

**Change**: delete the `SM_MONITOR(nrf_modem_at_mon, MON_ANY, ...)` bridge in
`nrf_modem_at.c` (and `nrf_modem_at_notif_handler_set` becomes a stub kept
for the NCS `at_monitor` SYS_INIT to call harmlessly). Keep
`sm_at_client_monitor.c`'s direct AT_MONITOR dispatch as the single path, and
fix it to honor `paused` and `direct` flags (direct handlers: still dispatch
from `sm_monitor_task`, i.e. thread context — document that "direct" loses
its ISR meaning here, which is safer, not less safe). Net: every URC delivered
exactly once; `at_monitor_heap` stops double-buffering every notification.

**Risk**: medium — behavioral change for every AT_MONITOR consumer (halves
deliveries). Anything accidentally *relying* on double delivery would break —
none plausible, but soak.
**Blast radius — tracker**: lte_lc CEREG/CSCON/MDMEV events stop firing
twice → link_policy/uploader see single edges (verify no logic counted on
duplicates being coalesced); modem_info/pdn the same. Log volume drops.
**Blast radius — Waggi**: already deleted the bridge on 2026-07-03 (their
duplicate-CONNACK fix); port is convergence.
**Verification**: unit: registered AT_MONITOR + SM_MONITOR handlers with a
counting fake, feed one URC, assert exactly one delivery each, paused honored.
HIL: CEREG event count over a registration cycle (expect halved); MQTT
CONNACK single-fire on product template.

## S6 — Single-lock convergence + atomic datamode + SDK txn removal (F2, F5)

The big one; land after S2/S3/S5 so its diff is only the lock model.

**Change**:
1. Core `nrf_modem_at.c` + `sm_modem_power_mgmt.c`: fold `txn_lock` into the
   single AT mutex per ADR-0002 / `at-lock-api-recommendation.md` R1/R3
   (waggi_v5's two files are the reference implementation — port, don't
   reinvent: PM functions assert lock-held, auto-sleep 500 ms try, explicit
   sleep bounded 30 s, RI wake bounded).
2. Add `nrf_modem_at_cmd_datamode(cmd, data, len)` (port from waggi, incl.
   its datamode quarantine: on timeout send `+++` before drain);
   `nrfmodule_mqtt_publish()` switches to it. `nrf_modem_at_datamode_send`
   stays but documented as exclusive-context-only.
3. Add `nrf_modem_at_exclusive(fn, ctx, timeout)`; reimplement
   `nrf_modem_lib_reset()`'s DTR+probe bracket inside it (fixes F13's
   lock-free reset while at it; also resync pm `modem_state = AWAKE` after a
   successful reset).
4. SDK: remove `sm_modem_power_mgmt_txn_begin/end` from
   `sm_modem_power_mgmt.h`; add the two new prototypes to `nrf_modem_at.h`.
   Same-PR pairing across core+SDK (co-dependent, like core#17/sdk#14 were).

**Risk**: high — replaces the locking model under everything. Mitigation: the
target design is already HIL-proven in waggi_v5 under MQTT + auto-sleep load,
which is *more* adversarial than the tracker's HTTP duty cycle.
**Blast radius — tracker**: no source changes (uses only printf/cmd/scanf +
pause/resume/sleep). Behavior: commands now hold one lock; wake retries no
longer convoy other callers behind a second mutex; auto-sleep skip semantics
unchanged. Must re-validate the DTR re-cycle wake on hardware (the -11 wake
bug's regression test).
**Blast radius — Waggi**: this is the convergence event — after S6, core's
lock model equals waggi's, and waggi can plan de-vendoring (separate effort).
**Blast radius — SDK/product template**: `txn_begin/end` deleted before ever
shipping in a tag; template doesn't call it.
**Verification**: unit: exclusive callback recursion, try-variant contention,
publish-vs-sleep interleave with fake client. HIL (tracker): 100× sleep→wake→
HTTP-POST cycles, wake-attempt histogram ≈ pre-change; PPK2 power floor
unchanged (~89 µA regime intact). HIL (product template or bench MQTT build):
publish storm with `INACTIVITY_TIMEOUT` deliberately set equal to publish
cadence (the pathological alignment) — zero payload corruption on broker,
zero `-11`. This is the Waggi bench scenario replayed against core.

## S7 — `#XMQTTMSG` bounds + static buffers (F7)

**Change**: port waggi's `handle_mqtt_msg` hardening: validate
topic_len/msg_len ≥ 0, ≤ static buffer sizes, and ≤ bytes actually present in
the chunk; replace `k_malloc/k_free` with static buffers (URC context, heap
under contention); reject rather than truncate on mismatch.
**Risk**: low. **Tracker**: unused path (no MQTT) — zero risk. **Waggi**:
already fixed; convergence. **Product template/customers**: closes a heap
overread reachable from the radio side.
**Verification**: unit with malformed/truncated URC corpus (lengths bigger
than chunk, binary payload with embedded `\n+`, split headers).

## S8 — Peripheral hardening batch (F8, F9, F10, F11, F12)

Small independent changes, one PR, or fold into nearby slices:
- **F8**: `sm` shell routes through `nrf_modem_at_cmd()` (gets locking +
  wake for free); `smsh uart` commands log a warning that they bypass PM.
  Tracker bench scripts (PPK2 harness) keep working — same command syntax.
- **F9**: `dtr_config.active` → `atomic_t`; in automatic mode, `tx_write`
  submits `dtr_uart_enable_work` instead of calling `dtr_uart_enable()`
  inline (single owner: the S3 workqueue). Tracker unaffected (automatic=false
  under PM); protects the non-PM SKU path.
- **F10**: guard `g_resp_buf` clear+append with a spinlock or move the
  accumulator into `sm_at_client` behind the S2 handshake; at minimum
  document that URC bytes can interleave and parsers must strstr (already the
  Waggi rule).
- **F11**: `sm_monitor_heap` size → Kconfig (default 2048), drop counter
  exposed via log-once-per-burst; S5 halves pressure already.
- **F12**: raise `NRFMODULE_SM_AT_CLIENT_UART_RX_BUF_SIZE/COUNT` defaults
  (2048×4, Waggi's bench numbers) or gate a build-time warning when
  baud/HWFC combination makes 768 B risky; bump `PM_WORKQ_STACK_SIZE` 1024 →
  2048 (logging headroom).
**Verification**: build-only for defaults (tracker uses HWFC so behavior
unchanged); shell HIL smoke (`sm AT`, `smsh uart auto 100`); unit for the
atomic flag.

---

## Sequencing summary

| Order | Slice | Sev fixed | Effort | Depends on |
|-------|-------|-----------|--------|-----------|
| 1 | S1 buf_unref | memory corruption | XS | — |
| 2 | S2 handshake | high (desync) | S | — |
| 3 | S3 AT workqueue | critical (F1a) | M | S2 helpful |
| 4 | S4 HTTP timeout | critical instance (F1b) | M | S3 |
| 5 | S5 single dispatch | high (double URC) | S-M | — |
| 6 | S6 single lock + datamode + SDK gate | critical (F2) / high (F5) | L | S2, S3, S5 |
| 7 | S7 mqtt bounds | med-high | S | — |
| 8 | S8 batch | medium/low | S | S3 for F9 |

v2.3.0 tag gate: S6 (SDK surface). If v2.3.0 must ship sooner, the minimum is
reverting sdk#14's header exposure (keep the symbols internal to core) — do
not tag the txn API into a release.
