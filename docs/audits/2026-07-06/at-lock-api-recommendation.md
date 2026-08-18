# AT lock API recommendation — one shape for Waggi and the tracker

Date: 2026-07-06. Inputs: nrfmodule-core @ 59b7df8, nrfmodule-sdk @ ccbfd5c
(txn API from sdk #14, merged, **untagged** — pending v2.3.0), waggi_v5
ADR-0002 implementation (`modules/waggi_modem`, bench-validated 2026-07-06:
pub_fail=0 under sleep-gapped publishes).

## The question

waggi_v5 exposed `nrf_modem_at_lock(k_timeout_t)` / `nrf_modem_at_unlock()`.
Vincent dislikes the bare pair. The needs behind it are real:

- **N1 — composite atomic sections**: multi-AT sequences and command+payload
  (datamode publish) must not interleave with other AT traffic or auto-sleep.
  Bench-proven failure: `AT#XMQTTSUB` bytes captured as MQTT payload on the
  broker (Waggi, 2026-07-03); SLM datamode captures *everything* until the
  `+++` terminator.
- **N2 — trylock for the sleep worker**: auto-sleep must skip, not queue,
  when AT traffic is in flight.
- **N3 — bounded wait for PM**: explicit sleep / reset paths need a timeout,
  never `K_FOREVER`.

## What exists today

| | core (tracker) | waggi_v5 shim | SDK public surface |
|---|---|---|---|
| Serialization | `nrf_modem_at_lock` (internal) **+** `txn_lock` (second mutex in pm) | single `at_mutex` | — |
| Composite section | none — MQTT publish is two separate locked calls with an open injection window between them | `nrf_modem_at_cmd_datamode(cmd, data, len)` holds the mutex across both phases (internal locking) | `nrf_modem_at_datamode_send()` only (payload half, no atomicity) |
| PM vs AT exclusion | pm takes `txn_lock` itself; command path nests `at → txn` | pm functions **assert caller holds the AT mutex**; auto-sleep trylocks (500 ms), explicit sleep bounded 30 s | `sm_modem_power_mgmt_txn_begin()/end()` — void, `K_FOREVER`, no try variant |
| Exposed lock | no | `nrf_modem_at_lock/unlock/is_held_by_current` in the module header (zero app-level callers — all three users are inside `waggi_modem` itself) | `txn_begin/end` **is** an exposed bare lock pair, just misnamed |

## Does the SDK txn API cover N1–N3? No.

1. **Wrong lock.** `txn_lock` excludes only auto-sleep. A consumer holding it
   is *not* protected from other AT callers — `nrf_modem_at_*` traffic from
   another thread still interleaves into a datamode window. N1 unmet.
2. **ABBA trap by design.** The canonical internal order is
   `nrf_modem_at_lock → txn_lock`. A consumer that follows the header's
   documented pattern — `txn_begin()`, then its own sends — either calls
   `nrf_modem_at_*` (acquires in reverse order → ABBA with every concurrent
   command; permanent deadlock when `nrf_modem_at_sem_timeout_set(<0)` is in
   effect, ~11 s convoys otherwise) or calls raw `sm_at_client_send_cmd()`
   (bypasses AT serialization entirely → injection). There is no correct way
   for an external consumer to use this API for a composite section.
3. **No timeout, no trylock.** `void txn_begin(void)` is `K_FOREVER`. N2/N3
   unmet.
4. **Same leaky-pair problem** Vincent objects to in waggi's shape — begin
   without end (error paths), end without begin, cross-thread pairing — plus
   the extra failure mode of being the *inner* lock.

Verdict: the txn API is a power-mgmt implementation detail that leaked into
the SDK. It should not survive to v2.3.0 in its current form (see below).

## Recommendation

### R1 — One mutex. Fold `txn_lock` into the AT lock (adopt ADR-0002 in core)

Waggi already proved the shape on hardware: a single recursive `at_mutex`
serializes commands, wake, sleep, and datamode. PM becomes a peer:
`ensure_modem_awake()` / `put_modem_to_sleep()` run **inside** the lock the
command path already holds (`__ASSERT(lock_is_held_by_current())`), auto-sleep
acquires with a 500 ms bounded try, RI wake likewise. With one lock there is
no ordering to get wrong — the ABBA class (F5) is deleted structurally, and
`state_mutex`'s removal in core #19 was already a step down this path.

Cost accepted: a slow AT command blocks all callers for its duration — same
trade-off Nordic's own library makes (per its public header/doc "Thread
safety" statement; **UNVERIFIED at the binary level** — the team's
`nrf_modem.a` disassembly notes were searched for in the sandbox and not
found, so the "Nordic does it with one semaphore" claim rests on
`nrf_modem_at.h`/`at_interface.rst` only. It doesn't matter for this decision:
core's implementation is our own).

### R2 — Composite sections become APIs, not exposed locks

Public surface (SDK `include/nrf_modem_at.h`):

```c
/* N1a: the one composite everyone actually needs. Command + datamode payload
 * + terminator under a single lock hold. Ported from waggi_v5 (bench-proven). */
int nrf_modem_at_cmd_datamode(const char *cmd, const void *data, size_t len);

/* N1b: escape hatch for other composites (reset bracket, cert provisioning,
 * multi-AT reads that must be coherent). Callback-scoped: lock cannot leak.
 * timeout: K_NO_WAIT = try (N2), bounded (N3), K_FOREVER forbidden by
 * convention (assert in debug builds).
 * Returns -EAGAIN if the lock wasn't acquired; else fn's return value. */
int nrf_modem_at_exclusive(int (*fn)(void *ctx), void *ctx, k_timeout_t timeout);
```

Inside an `nrf_modem_at_exclusive()` callback, plain `nrf_modem_at_*()` calls
recurse on the same mutex (k_mutex is owner-recursive) — the callback body
reads naturally. Rules the callback must obey (document in the header):
runs on the caller's thread; no URC-handler or sysworkq callers; must not
stash pointers into the shared response buffer past the callback's return.

- The **bare pair does not enter the SDK.** Vincent's instinct holds: with
  `cmd_datamode` covering the hot path and `exclusive` covering the rest,
  there is no remaining need that justifies unlock-without-lock /
  forgotten-unlock as a consumer bug class.
- `nrf_modem_at_lock_is_held_by_current()` stays **internal** (assert helper
  for the PM peer), not in the SDK header.
- `nrf_modem_at_datamode_send()` remains for source compatibility but is
  documented as "must run inside `nrf_modem_at_exclusive()` together with the
  command that opened datamode" — and `nrfmodule_mqtt_publish()` switches to
  `cmd_datamode` so no in-tree code depends on the two-call pattern.

### R3 — The sleep worker and PM needs are internal, not API

Auto-sleep's trylock (N2) and explicit-sleep bounded wait (N3) live inside
`sm_modem_power_mgmt.c` against the same single mutex — exactly waggi's
current file, which can be ported nearly verbatim. The app-facing PM API stays
what the tracker already uses: `pause() / resume() / sleep() / get_state()`.
None of these need a lock exposed.

### R4 — Gate v2.3.0 on removing `sm_modem_power_mgmt_txn_begin/end`

The txn API is merged in SDK main but **has never shipped in a tag**. The
pending release is the last point where it can be removed instead of
deprecated. Verified consumers today: core's own `execute_command_locked_ex`
(refactored away by R1) and nothing else — nRFTrackerFW does not call it
(grep: only pause/resume/sleep), Waggi vendors its own stack. Remove the two
functions from `sm_modem_power_mgmt.h` in the same PR that lands R1 in core;
if a straggler appears, a deprecated inline shim mapping to
`nrf_modem_at_exclusive` is trivial — but prefer deletion pre-tag.

## Convergence map (one shape, both consumers)

| Need | waggi_v5 today | core today | Converged |
|------|---------------|-----------|-----------|
| Serialize AT | `at_mutex` | `at_lock` + `txn_lock` | single mutex in core (R1) |
| Publish atomically | `nrf_modem_at_cmd_datamode` | two-call gap (F2) | `cmd_datamode` in SDK/core (R2) |
| Other composites | exposed `nrf_modem_at_lock/unlock` | SDK `txn_begin/end` (broken, F5) | `nrf_modem_at_exclusive` (R2) |
| Sleep-worker skip | internal 500 ms try on `at_mutex` | `txn_lock` `K_NO_WAIT` | internal try on the one mutex (R3) |
| Wake-before-send | pm peer asserts lock held | `txn_begin`+`ensure_awake` wrapper | pm peer model (R3) |
| PM app control | pause/resume/sleep | pause/resume/sleep | unchanged |

Waggi's migration off its vendored fork then becomes mechanical: its three
intra-module lock users map to the peer model already in core; its exposed
pair is deleted (no app callers exist); `cmd_datamode` signatures already
match. The tracker recompiles with zero source changes (its API usage —
`nrf_modem_at_printf/cmd/scanf`, pause/resume/sleep — is untouched).

## Rejected alternatives

- **Keep two locks, document the ordering**: ordering rules that only exist
  in documentation lose to the SDK header actively suggesting the wrong
  order; F1/F2 remain reachable. Rejected.
- **Expose the bare pair "like Waggi but documented"**: zero current external
  callers means we'd be creating the API surface *before* any demand, in its
  most error-prone form. Rejected.
- **Token-based `txn_begin() → token, txn_end(token)`**: better than the bare
  pair (pairing checkable), but still allows holding across arbitrary code,
  blocking in callbacks, and cross-thread misuse; callback scoping gives the
  same power with none of the leak modes. Rejected in favor of
  `nrf_modem_at_exclusive`. Revisit only if a consumer genuinely cannot
  express its composite as a callback (none known: publish, reset bracket,
  provisioning, quarantine resync all fit).
- **Owner-thread/queue serialization** (v5's pre-ADR-0002 design): bench-
  proven to wedge (~60 s owner stalls); removed by ADR-0002. Do not resurrect.
