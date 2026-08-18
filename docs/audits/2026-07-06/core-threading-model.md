# nrfmodule-core threading model

Status: audit snapshot 2026-07-06 (core @ 59b7df8). Intended final home:
`nrfmodule-core/docs/THREADING_MODEL.md`. This is the document reviewers check
concurrency-touching changes against. Verified against source; nothing here is
inferred from `nrf_modem.a` (core does not link it — the whole point of the
client layer is to reimplement `nrf_modem_at_*` over UART).

## 1. Execution contexts

| # | Context | Defined in | Runs |
|---|---------|-----------|------|
| C1 | UART ISR (`uart_callback`, async UART API) | `src/serial_modem_client/sm_at_client.c` | RX slab alloc/free, `rx_event_queue` put, `tx_buf` ring ops, `k_sem_give(tx_done_sem/uart_disabled_sem)`, submits `rx_process_work` to sysworkq |
| C2 | GPIO ISR (`gpio_cb_func`, RI pin) | `sm_at_client.c` | reads `dtr_config`, submits `dtr_uart_enable_work` (sysworkq, automatic mode only), calls `ri_handler()` **in ISR context** |
| C3 | System workqueue | — | `rx_process_work` (response parse + `sm_monitor_dispatch`), `sm_monitor_work` (URC handler dispatch), `at_monitor_work` (NCS `at_monitor` second-stage dispatch), `dtr_uart_enable_work`, `dtr_uart_disable_work`, `sm_barrier_work`, `nrfmodule_http` `timeout_work` |
| C4 | `power_mgmt_work_q` (dedicated, 1024 B stack, `CONFIG_SYSTEM_WORKQUEUE_PRIORITY`) | `src/client/sm_modem_power_mgmt.c` | `go_to_idle_work` (auto-sleep: trylock txn + `AT#XSLEEP=2`, blocks ≤5 s), `on_ri_work` (wake: txn `K_FOREVER` + DTR re-cycle loop, blocks ≤~11 s) |
| C5 | Caller threads (app main, tracker uploader, lte_lc workq, date_time workq, Waggi transport workq) | consumers | `nrf_modem_at_printf/cmd/cmd_raw/scanf/datamode_send` |
| C6 | Shell thread | `sm_at_client.c` shell cmds | `sm <at>` → `sm_at_client_send_cmd()` **directly, no locks**; `smsh uart enable/disable` → DTR works |

NCS libraries compiled by the client cmakes: `lte_lc` has its own workqueue
(`common/work_q.c`); `date_time` has its own thread. Their **URC handlers**
however run in C3 (see §4).

## 2. Synchronization primitives

### Locks

| Lock | File | Protects | Acquire policy |
|------|------|----------|----------------|
| `nrf_modem_at_lock` (k_mutex, recursive) | `src/client/nrf_modem_at.c` | one AT transaction: `g_cmd_buf`, `g_resp_buf`, send+parse+copy-out | `lock_at()`: `K_MSEC(g_at_cmd_timeout_ms + 1000)`, **`K_FOREVER` if `nrf_modem_at_sem_timeout_set(<0)`** |
| `txn_lock` (k_mutex, recursive) | `src/client/sm_modem_power_mgmt.c` | `modem_state` transitions; excludes auto-sleep from a wake+send window | command path: `K_FOREVER` (nested inside at_lock); auto-sleep: `K_NO_WAIT` trylock; RI wake / explicit sleep: `K_FOREVER`. **Exposed to consumers via SDK `sm_modem_power_mgmt_txn_begin/end` (no timeout, no try variant)** |
| `http_mutex` (k_mutex) | `src/client/http/nrfmodule_http.c` | `ctx` state machine | `K_FOREVER` everywhere, including from sysworkq (`timeout_work`) |

### Semaphores

| Sem | Init | Pairing |
|-----|------|---------|
| `at_rsp` (0,1) | `sm_at_client.c` | given by `response_handler` (C3) on terminator parse; taken by `sm_at_client_send_cmd` (C4/C5/C6). **Not reset at command start** — a late give survives into the next command (see finding F3) |
| `tx_done_sem` (0,1) | `sm_at_client.c` | UART TX pipeline: ISR gives, `tx_write`/`tx_disable` take |
| `uart_disabled_sem` (0,1) | `sm_at_client.c` | `rx_disable()` handshake with `UART_RX_DISABLED` event |
| `sm_barrier_sem` (0,1) | `nrf_modem_at.c` | end-of-command flush: caller submits `sm_barrier_work` to **sysworkq** and waits `K_FOREVER` — every AT command's completion depends on a live sysworkq |

### Atomics (correct usage)

`uart_state` bit flags, `initialized`, `auto_sleep_paused`, per-RX-buf
`ref_counter`.

### Shared state that is NOT synchronized (each is a hazard or a documented advisory)

| State | Written by | Read by | Verdict |
|-------|-----------|---------|---------|
| `sm_at_state` (plain enum) | C4/C5/C6 (`send_cmd`), C3 (`parse_at_response`) | both | **data race**; drives response-vs-URC routing (F3) |
| `dtr_config.active/.automatic/.inactivity` (plain bool/struct) | C3, C4, C5, init | C1(ISR-adjacent TX path), C2 | race in automatic mode (F9) |
| `ri_handler`, `data_handler`, `g_notif_handler` (fn ptrs) | init | C2 (ISR), C3 | benign if registered before traffic; unregistered mid-run = hazard |
| `modem_state` (plain enum) | under `txn_lock` | lock-free advisory reads (`on_ri`, `get_state`) | OK per comment: re-validated under lock |
| `g_resp_buf` | C3 (`sm_client_data_handler`, strlen-append) | C4/C5 (clear + parse under at_lock) | clear-vs-append **data race**; URC bytes interleave into responses (F10) |
| `g_at_cmd_timeout_ms` | any caller | any caller | word-atomic on M4, but changing it mid-flight (probe/reset paths do) affects unrelated callers |
| `g_active_client`, `->is_connected` (mqtt) | C3 (URC) | C5 | TOCTOU on publish; acceptable if documented |
| heaps | `sm_monitor_heap` 1024 B (`K_NO_WAIT`, drops URCs silently), `at_monitor_heap`, `k_malloc` in `handle_mqtt_msg` (C3) | | F7/F11 |

## 3. Lock-ordering rules

Canonical order (outer → inner):

```
consumer/module mutex (e.g. http_mutex)  →  nrf_modem_at_lock  →  txn_lock
```

1. **`nrf_modem_at_lock` before `txn_lock`, always.** The command path
   (`execute_command_locked_ex`) is the canonical instance. Any code that takes
   `txn_lock` first (e.g. a consumer calling SDK `txn_begin()` and then
   `nrf_modem_at_*()`) creates ABBA against every concurrent command. The SDK
   header's own guidance invites this misuse (F5).
2. **Never hold any module/app mutex across an `nrf_modem_at_*` call if that
   mutex is also acquired from C3 or a URC handler.** Violated today by
   `nrfmodule_http` `timeout_handler` (holds `http_mutex` across
   `AT#XCLOSE`, on the sysworkq — double violation, F1b).
3. `txn_lock`-only paths (C4: auto-sleep, RI wake, explicit sleep) must never
   call `nrf_modem_at_*` (would invert rule 1). They speak raw
   `sm_at_client_send_cmd` — which is why they conflict with
   `nrf_modem_at_datamode_send`, which holds only `at_lock` (F2).
4. Callbacks invoked while a lock is held: `nrf_modem_lib_client_on_cfun`
   hooks run on the caller thread **holding `nrf_modem_at_lock`** (recursive
   re-entry is legal but clobbers `g_cmd_buf`/`g_resp_buf`); MQTT/HTTP user
   callbacks run either on C3 (URC/timeout) or the caller thread. A consumer
   callback that takes an app lock establishes `at_lock → app_lock`; that app
   lock must then never be held around an AT call elsewhere.

## 4. URC dispatch pipeline and its constraints

```
UART ISR (C1)
  └─ k_msgq → rx_process_work            [sysworkq]
       └─ response_handler
            ├─ terminator found & sm_at_state==PENDING → k_sem_give(at_rsp)
            ├─ else → sm_monitor_dispatch: split lines, k_heap_alloc, FIFO
            │     └─ sm_monitor_work     [sysworkq]
            │          ├─ SM_MONITOR handlers (incl. nrf_modem_at_mon MON_ANY
            │          │    → at_monitor_dispatch → heap+FIFO
            │          │         └─ at_monitor_work [sysworkq] → AT_MONITOR handlers)   (path A)
            │          └─ direct STRUCT_SECTION_FOREACH(at_monitor_entry) → handlers    (path B)
            └─ data_handler → sm_client_data_handler (appends g_resp_buf)
```

Constraints (checkable):

- **U1 — URC handlers run on the system workqueue.** They must not block, not
  issue `nrf_modem_at_*`/`sm_at_client_send_cmd` (the response would be parsed
  by `rx_process_work` on the same, now-blocked, thread), not sleep, not do
  long work. Copy out and defer to another queue.
- **U2 — today, *no* code on the sysworkq may issue a blocking AT call**, URC
  handler or not: response parsing and the end-of-command barrier both live
  there. An AT call from sysworkq always times out (10 s default) and wedges
  the queue for the duration; with `sem_timeout_set(<0)` it deadlocks
  permanently. In-tree violation: HTTP timeout path (F1b). Waggi hit this
  class on the bench 2026-07-03 (10 s wedge per livestream handshake).
- **U3 — both paths A and B fire for every URC** when `CONFIG_AT_MONITOR=y`
  (selected by lte_lc/mqtt/modem_info/pdn client Kconfigs): every AT_MONITOR
  handler receives every matching notification **twice**, and path B ignores
  the `paused` and `direct` monitor flags (F4).
- **U4 — URC payload integrity is line-based.** `sm_monitor_dispatch` splits
  on `\n` and re-chunks on URC-prefix heuristics (`+`/`%`/filter match).
  Binary or multi-line payloads (`#XMQTTMSG`) can be fragmented; handlers must
  bound their reads by the actual chunk length, never by lengths declared
  inside the URC (F7). Parsers must `strstr` for their marker, never anchor at
  buffer start (URC contamination).
- **U5 — `sm_monitor_heap` is 1024 B with `K_NO_WAIT`**: URC bursts drop
  notifications with only a `LOG_WRN`. Sizing/telemetry is a consumer-visible
  reliability parameter (F11).

## 5. Who may block, where

| Context | May block on | Must never |
|---------|--------------|-----------|
| C1/C2 ISRs | nothing | any wait, any AT, heap alloc beyond slab `K_NO_WAIT` |
| C3 sysworkq | short bounded waits (`uart_disabled_sem` ≤100 ms) | `at_rsp` (any AT command), `http_mutex` while an AT holder may be in flight, `K_FOREVER` on anything |
| C4 pm workq | `txn_lock`, AT round-trips it owns (wake ≤~11 s, sleep ≤5 s) | `nrf_modem_at_*` (lock-order inversion), sysworkq-dependent waits |
| C5 callers | `at_lock` (bounded unless timeout<0), `txn_lock` (nested), `at_rsp` via `send_cmd`, `sm_barrier_sem` (**requires live sysworkq**) | holding consumer locks that C3 also takes (rule 2) |
| C6 shell | today blocks like C5 but **without any lock** | should not exist in this form (F8) |

## 6. Wake/sleep model (XSLEEP=2 over the UART bridge)

- `AT#XSLEEP=2`: modem UART off, LTE/PSM unaffected. Mobile-terminated wake =
  modem pulls **RI** → C2 → `on_ri_work` (C4). Mobile-originated wake = host
  asserts **DTR**; the wake is **edge-triggered and the modem misses the edge
  if still entering sleep** — `ensure_modem_awake()` re-cycles a fresh
  low→high edge per retry (5 × ~250 ms; empirically lands on attempt 2).
- `sm_at_client_enable/disable_dtr_uart()` are **asynchronous**: they submit
  work to the sysworkq and return. The wake path compensates with fixed
  `k_msleep` delays — correctness depends on sysworkq latency staying below
  `UART_ENABLE_DELAY_MS` (50 ms default). A wedged sysworkq (U2 violations)
  breaks wake timing too.
- Every `nrf_modem_at_*` command runs `txn_begin → ensure_awake → send →
  notify_activity → txn_end`. Auto-sleep (`go_to_idle_work`) trylocks
  `txn_lock` and defers if busy — this closes the wake-vs-sleep race for the
  *command* path only. `nrf_modem_at_datamode_send` does **not** participate
  (no txn, no ensure_awake): auto-sleep can fire between a `#XMQTTPUB` command
  and its payload, injecting `AT#XSLEEP=2` into the datamode capture (F2).
- After `AT#XRESET` / `nrf_modem_lib_reset()`, pm `modem_state` is not
  resynchronized and the reset path takes no locks (F13).

## 7. Known violations at snapshot (cross-ref issue drafts)

| ID | Violation | Where |
|----|-----------|-------|
| F1a | AT completion barrier + response parse on sysworkq (U2 root cause) | `nrf_modem_at.c`, `sm_at_client.c` |
| F1b | Blocking AT from sysworkq while holding `http_mutex` | `nrfmodule_http.c` `timeout_handler → close_socket` |
| F2 | Datamode two-phase not atomic; auto-sleep + any caller can inject into payload | `nrfmodule_mqtt.c` publish, `nrf_modem_at_datamode_send` |
| F3 | Stale `at_rsp` give + `sm_at_state` race → permanent cmd/response desync | `sm_at_client.c` |
| F4 | Double URC dispatch to AT_MONITOR handlers; flags ignored in direct path | `sm_at_client_monitor.c` + `nrf_modem_at.c` MON_ANY bridge |
| F5 | SDK `txn_begin/end` invites `txn → at` ABBA order | `sm_modem_power_mgmt.h` |
| F6 | `buf_unref(buf)` passed slab-block pointer → refcount corruption | `sm_at_client.c` `UART_RX_BUF_REQUEST` error path |
| F7 | `#XMQTTMSG` handler memcpy's URC-declared lengths without bounds vs actual chunk | `nrfmodule_mqtt.c` |
| F8 | Shell bypasses all locks; can inject mid-transaction and tear down UART | `sm_at_client.c` shell cmds |
| F9 | Automatic-DTR enable (caller thread) races disable work (sysworkq); plain-bool `active` | `sm_at_client.c` |
| F10 | `g_resp_buf` clear-vs-append race; URC bytes in response buffer | `nrf_modem_at.c` |
| F13 | Reset/init paths lock-free; pm state divergence after XRESET | `nrf_modem_lib.c` |

## 8. Reviewer checklist for concurrency-touching PRs

- [ ] New work item: which queue? Anything it blocks on? If sysworkq: no AT,
      no `K_FOREVER`, no lock also held across AT elsewhere.
- [ ] New AT call: is the caller a URC handler or on the sysworkq? Reject.
- [ ] New lock acquisition: does it respect `module → at_lock → txn_lock`?
      Does anything hold it while calling into consumers/callbacks?
- [ ] New shared flag: `atomic_t`, not `bool`. New shared enum: owned by one
      context or lock-protected.
- [ ] Composite AT sequence (multi-command or command+payload): must be atomic
      under ONE lock hold (see at-lock API recommendation) — never two
      back-to-back locked calls.
- [ ] Timeouts: no `K_FOREVER` on paths reachable from work queues; every
      begin/lock has an end/unlock on all error paths.
- [ ] DTR/UART teardown: can it run while a send is in flight? Who guarantees
      not?
