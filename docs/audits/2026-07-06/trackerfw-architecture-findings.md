# nRFTrackerFW — Architecture & Correctness Findings (2026-07-06)

Repo: `d:\Root\nrfmodule_workspace\nRFTrackerFW` @ main `d6ff34b` (post #48/#49/#50/#51/#52).
Lenses: embedded-quality-review (thermo-nuclear) + improve-codebase-architecture (depth/seams/deletion test).

**Prior review**: `D:\Root\nrfmodule_workspace\demo_readiness_plan.md` (2026-07-02, findings DR-01..DR-72).
This pass builds on it. Every finding below is marked **NEW** (not in the DR review) or **KNOWN (DR-xx)**
(re-verified against today's main, with status). No GitHub issues exist on the repo (issue list empty
as of today) — DR items live only in that doc.

## Verdict

**The architecture is healthy and the discipline held.** The pure-spine SM + injected-effects seam,
pure-core + injected-deps modules, three justified threads, and the policy/mechanism split
(sync_policy / sync_engine / transport_if / lte_transport) all survived ~30 fast-moving PRs intact.
tracker_sm.c is still 100% control flow — no logic leaked into entry/exit actions. Kconfig is
disciplined (~90 symbols, consistent MODULE/MODULE_SHELL/bounds pattern), not sprawl. The demo-safety
PR #51 fixes (quiesce handshake, CEREG gating, backoff-on-link-up, shutdown latch) are competently done.

The residual risk concentrates in three places:
1. **Two behavior gaps that break the product outside a one-day demo**: begin/halt state is not
   persisted (KNOWN DR-10 — and now *server-invocable reboot* makes reset a routine event), and the
   data queue never compacts / rejects newest on overflow (KNOWN DR-14/15 — multi-day failure).
2. **One seam built too narrow**: sampler cancellation was implemented as a *permanent poweroff latch*
   only; ACTIVE→SLEEP still can't abort an in-flight acquisition (NEW A1 — GPS burns up to
   `gps_acq_timeout_s` after the hub pauses the tracker).
3. **The pre-architecture legacy remnant**: `src/filesystem/filesystem.c` and `src/gps.c` fail the
   deletion test and carry the only real hygiene bugs left (KNOWN DR-51/DR-48, sharpened here).

Nothing found rises to a *new* Critical. The one product-killing scenario (A2/DR-10) was already known;
it is re-proven below because its severity increased since the DR review.

---

## Part A — Architecture findings (ranked)

### A1. Sampler cancellation seam is one-shot — SLEEP/WAIT_BEGIN cannot abort an in-flight acquisition — **NEW** (refines KNOWN DR-04 face (a), explicitly left unfixed by #51)

**Files**: `src/tracking/sampler.c:185-215`, `src/gnss/gnss_producer.c:18-21,107-128`,
`src/state/tracker_sm.c:202-210` (sleep_entry), commit `3da9547` (scope statement).

PR #51 built a clean cancel path (`wait_fix` → `-ECANCELED`, cycle exits without a record) but welded
it to `gnss_producer_shutdown()`, a **never-cleared latch** usable only on the road to System OFF.
`sampler_set_active(false)` — what SLEEP and WAIT_BEGIN entry actually call — only flips a flag the
thread checks *between* cycles and gives `sampler_wake`, which does **not** wake a `wait_fix` blocked
on `fix_sem`.

**Concrete scenario** (from code, not speculation): hub sends sleep → `sleep_entry` runs
`sampling_set(false)`; the sampler is mid-acquisition blocked in `k_sem_take(&fix_sem, remaining)`.
The L76 stays powered for the *remaining acquisition budget* — `gps_acq_timeout_s` is a runtime param,
range 10–600 s — then `d->sample()` runs and **enqueues one more record while the tracker is nominally
paused**, then GPS powers off. The hub-pause state (a primary product state — "quiet in the loft")
leaks up to 10 minutes of GPS-on power and a trailing record per pause.

**Why it's architecture, not just a bug**: the cancel mechanism exists but was scoped to one consumer.
The general form is cheap: a *resettable* cancel (cleared on the next `gnss_producer_start`) consumed
by `wait_fix`, invoked from `sampler_set_active(false)`. The pure core already handles `-ECANCELED`;
zero core changes, ~15 lines in gnss_producer + 2 in sampler. Fix plan slice 2.

### A2. Begin/halt state not persisted — server-invocable `reboot` now makes this a routine product break — **KNOWN (DR-10, still open; severity raised)**

**Files**: `src/state/tracker_sm.c:360` (`tracker_sm_prod_ctx = (struct tracker_sm_ctx){0}`),
`src/main.c:109`, `src/command/command_service.c` (reboot now a live server command since #42/#43).

Proof of the failure (constructed, all steps verified in code):
1. Server schedules a race: config/command delivers `sm event begin <tomorrow-06:00>` → SM →
   WAIT_BEGIN. `has_begin/begin_unix` live **only in `tracker_sm_prod_ctx` RAM**.
2. Any reset happens. Since #42 the server itself can cause one (`reboot` command, persisted-ack,
   deferred `SYS_REBOOT_COLD`) — resets are now *routine*, not anomalous. Battery swap and watchdog too.
3. Boot: `tracker_sm_start()` zeroes the ctx; nothing reloads a begin. `begin_pending()` false →
   **ACTIVE**. The tracker samples GPS all night at full duty cycle and uploads, killing the battery
   before the race it was halted for. The WAIT_BEGIN boot fork (`tracker_sm_init_ctx`) is dead code in
   production — reachable only from unit tests.

DR-10 called this majors-tier for the demo; with the command channel live it is the top product
defect in the repo. Fix plan slice 1 (design: persist on the SM thread at the existing four mutation
sites via one choke-point helper + a `begin_persist` effect; load in `main()` before
`tracker_sm_start`).

### A3. `src/filesystem/filesystem.{c,h}` fails the deletion test — retire the file-op wrappers, keep mount/format — **NEW** (bugs within it are KNOWN DR-51, still open)

**Files**: `src/filesystem/filesystem.c` (391 LOC), users: grep `filesystem_` → 25 hits in 5 files,
but the only production consumer is `src/agnss/epo_storage.c` (+ its own shell + main.c's include).
`data_queue.c`, `usb_msc.c`, and the log backend all use Zephyr `fs_*` directly.

- Deletion test: delete the wrapper and complexity does *not* reappear across N callers — it lands in
  exactly one file (epo_storage), which already holds its own `epo_file_mutex` and could call `fs_*`
  directly, as every other module does.
- The wrapper's one honest job since PR #49 is **mount-point selection via DT chosen + format** —
  ~80 LOC. The rest is pass-through with a *decorative* mutex (`create_directory`/`list` bypass
  `fs_mutex` — DR-51b), the format-under-mount bug (DR-51a), the undefined `lfs_storage_mnt` fallback
  that breaks any board without the chosen node (DR-51c — directly undermining #49's retargetability
  goal), Waggi-era style (magic `END_OF_BUFFER`/`END_OF_FILE` sentinels, commented-out code, `\n` in
  LOG_ERR), and zero callers for half the API.
- Memory says this file is "the blessed base for on-demand SDK promotion". Counterpoint: promote the
  *mount ownership* (small, correct), not the wrapper API. A smaller blessed base is a better one.

Remedy (fix plan slice 7): shrink to `filesystem_init/uninit/format` + DT-chosen mount; port
epo_storage's five call sites to `fs_*`; fix format = unmount→mkfs→mount; replace the `#else` with
`BUILD_ASSERT`. Tests `test_filesystem` + `test_agnss` already exist and survive the seam.

### A4. `src/gps.c` (467 LOC) — a second, rival GNSS owner still unconditionally compiled — **KNOWN (DR-48, still open; deletion case now stronger)**

**Files**: `src/gps.c`, `CMakeLists.txt:74` (unconditional), `LOG_MODULE_REGISTER(gps, LOG_LEVEL_DBG)`.

It registers a **duplicate `GNSS_DATA_CALLBACK`** with shadow `last_fix/has_fix` state, and its
`gps on/off/rate/power` shell commands drive PM actions underneath a live `gnss_producer` acquisition
(operator hazard DR-48 documented). What's changed since the DR review: PR #48 shipped
`agnss_shell.c` (`agnss status|apply|receiver|refresh`), which supersedes gps.c's EPO bench role — the
file's remaining unique value is near zero. CONTEXT.md already says "legacy/reference … do not build
new logic on it." It now passes the deletion test *for deletion*: port any still-wanted fix-print
diagnostics into `gnss_shell.c`, delete the rest. Fix plan slice 7.

### A5. "Server commands are shell lines" makes shell modules load-bearing — the `blink` command depends on a module self-described as HIL tuning; the allowlist over-grants `led` — **NEW**

**Files**: `src/command/command_service.c:31-43` (`cmd_allow[]`), `src/led/led_shell.c:1-7`
("LED shell — HIL visual tuning"), `src/led/Kconfig` (`TRACKER_LED_SHELL` default y),
`src/state/Kconfig` (contrast: `TRACKER_SM_COMMAND` was correctly productionized by #51/DR-11).

Two connected problems:
1. **Latent DR-11 pattern, second instance.** The server `blink` command executes the shell line
   `led blink`, which exists only if `TRACKER_LED_SHELL=y`. Today it defaults y, so nothing is broken —
   but the file header says "HIL visual tuning", and the obvious future "slim the production shell"
   cleanup silently turns every server blink into a Failed ack. Exactly the trap DR-11 fixed for
   `sm event`, one module over. Nothing binds `cmd_allow[]` entries to the Kconfig symbols that
   register them.
2. **Allowlist over-grant.** `"led"` admits the whole subtree: a (typo'd/hostile) server command
   `led rgb 0 0 0` sets a **manual override that masks every status layer until another led command or
   reboot** (`led_indicator_override`), and `led off`/`led error` inject arbitrary indicator states.
   The DR-11 fix narrowed `sm event *`; `led` kept the blanket grant.

Remedy (fix plan slice 5): narrow to `"led blink"`; add a boot-time (or HIL-test) check that every
`cmd_allow[]` verb resolves against the shell root; move the `led blink` registration under
`TRACKER_COMMAND` or mark led_shell production in its header/Kconfig help.

### A6. agnss — the 3-port abstraction mostly earns its keep; the provider port is the one speculative leg — **NEW assessment** (policy-edge bugs are KNOWN DR-21/22, still open)

**Files**: `src/agnss/agnss.{c,h}` (150 LOC manager), `epo_mtk.c`, `agnss_src_ble.c`,
`agnss_src_http.c` (stub), `agnss_service.c`.

Deletion-test results, port by port:
- **Manager (policy core)**: keep. Owns staleness/dirty/apply lifecycle used by two real trigger
  contexts (sampler `ensure_applied`, uploader `refresh`); 16 unit tests; the DR-07 atomic dirty CAS
  landed correctly.
- **Codec port**: real seam — two adapters (epo_mtk + the test fakes), and the optional
  `receiver_window` port paid for itself immediately (HIL-proven skip of a redundant 27 KB upload
  after VBACKUP retention). This is what a good seam looks like.
- **Provider port**: speculative on the pull side. Push sources bypass the port entirely
  (`fetch=NULL`, they call `agnss_notify_updated()` directly); the only `fetch` implementation is a
  stub returning `-EAGAIN`; the `name` field is written and never read. The provider array + iteration
  exists to serve a hypothetical HTTP source whose design ("proxy vs direct-MediaTek") is undecided.
  Cost is small (~20 LOC), so this is a trim note, not a redesign: acceptable to keep **if** the HTTP
  story is expected within a quarter; otherwise delete the array (re-adding it later is mechanical).
- Open policy edges from the DR review remain: **DR-21** (margin applied on the apply path —
  `covers_now` subtracts `margin_s` inside `agnss_ensure_applied`, so valid EPO is withheld for its
  last 24 h; a unit test enshrines it) and **DR-22** (unsynced clock `now=-1` silently blocks apply —
  the first-boot chicken-and-egg where EPO would help most). Both verified still present. Slice 8.

### A7. Boot recipe hidden in `tracker_effects_init()`; `fx_poweroff` is a 60-line teardown recipe living in the effects vtable — **KNOWN (DR-70, still open, grew with #51)**

**Files**: `src/state/tracker_effects.c:181-268,283-296`, `src/main.c:109`.

The effects seam is otherwise pristine — this is the *one* place logic accumulated. Since the DR
review, #51 added the uploader quiesce + sampler stop_sync calls, so fx_poweroff now sequences five
subsystems, raw `NRF_P0/P1->LATCH` pokes, a button release-wait loop, and `sys_poweroff()` — an
ordered teardown protocol, untestable where it sits. And
`tracker_sm_start(tracker_effects_init())` still boots the uploader wiring and sampler thread as a
side effect of an argument expression. Extract `src/system/power_off.c` with an injected quiesce
list; hoist `uploader_service_init()`/`sampler_start()` into `main()`. Do it *after* the behavior
slices so the extraction is pure movement (fix plan slice 9). Note DR-37 (held button past the 10 s
release timeout arms DETECT with the line active → instant reboot) and DR-38 (VBUS re-check) land
naturally inside this extraction.

### A8. Sampler cadence is interval-*between*-cycles, not a fixed period — server pacing math is off by the acquisition time — **NEW (minor)**

**Files**: `src/tracking/sampler.c:165` (`k_sem_take(&sampler_wake, K_SECONDS(p.gps_fix_interval_s))`
runs *after* the cycle), `docs/adr/0003`.

Effective period = acquisition duration (2–60 s+) + `gps_fix_interval_s`. A server-set 30 s interval
yields 32–90 s actual cadence depending on sky view. For a product whose pitch is "server re-paces
sampling mid-race", the operator's number silently isn't the record rate. Options: anchor the next
cycle deadline at cycle *start* (one `k_uptime_get()` + arithmetic), or document interval-gap
semantics in ADR 0003 and the API contract. Decide once; slice 2 rider.

### A9. Cross-cutting inventories — mostly clean bills — **NEW (verdicts), residual items KNOWN**

**Threads** (justified, no unjustified concurrency): `tracker_sm` (prio 5, 2048 B — DR-06 fixed),
`uploader` (prio 5, 4096 B, K_THREAD_DEFINE at boot — DR-46's park-until-init still relies on
mode=OFF short-circuit, benign), `sampler` (prio 7, 2048 B). Sysworkq users: battery poll,
led_sources poll, button tap-timeout, adv_sampler self-reschedule, usb_msc VBUS poll (LOG_FS builds),
config_sync refresh, deferred reboot, BLE adv_work. Two k_timers (sleep, begin). Notes: SM shares
prio 5 with the uploader — the design memo said "SM slightly above workers"; consider prio 4 for OFF
responsiveness (cosmetic today). All cross-context flags audited here are `atomic_t`; the quiesce
handshake (request-gated sem) is correct.
**Kconfig**: disciplined, not sprawl. Real smells: `EPO_VALIDITY_MARGIN_HOURS` duplicates
`AGNSS_MARGIN_HOURS` (KNOWN DR-25, still open, both live), and the root `Kconfig` hosts stray EPO/USB
menus that belong in module Kconfigs.
**hil.conf**: still unconditionally merged (`CMakeLists.txt:19`) — now only 3 bench shells, but that
includes `sm event button` = **remote System OFF over the open NUS shell** (KNOWN DR-56/DR-18
residual, still open).
**SDK boundary**: clean (public `nrf_modem_*`/`lte_lc_*`/`sm_modem_power_mgmt_*`/`nrfmodule_http_*`
only). The one reach-across is the System-OFF sense wipe over core's RI arming (KNOWN DR-64 — ask for
an SDK quiesce API; keep the sweep as fallback). Promotion on-demand: correct; nothing here is ripe
except possibly the adv common-header proposal in BLE_SCOPE.

### A10. Data path & BLE-surface verdicts — **NEW (assessments)**

**Data path** (gps_sampler → collector → data_queue → uploader/sync_* → lte_transport): ownership is
single-writer/single-consumer throughout, the cooperative-stop story (keep_draining + quiesce
handshake + shutdown latch) is now real and well built. The **timestamp back-dating design**
(capture-uptime → resolve at drain; planned in the PR-B design notes) was **never built** — current
model is encode-at-capture. Consequence: a no-fix record captured before first clock sync omits `t`
and the server stamps it at *drain* time, hours late in a coverage gap. Positions always carry GNSS
UTC, so track integrity is safe; only no-fix telemetry drifts. Verdict: accept + document in
architecture.md (the design docs still describe the unbuilt model), or drop-`t`-less records at the
collector. Rider on slice 3.
**BLE surface vs DR-12**: the current shape absorbs the boss commands cleanly — the "every command is
a shell line" unification (one command table, three transports: NUS shell, server cmd channel, UART)
was the right code-judo move, made early. DR-12 is thin: `getid`/`set delay`/`check delay`/
`get config`/`send data` as shell commands mapping to `modem_lte_imei()`, `EV_SLEEP_CMD` post, SM
state read, `config_sync` kick, `uploader_service_notify_config()`+wake. No refactor needed; put them
in one file and extend `cmd_allow[]` per-verb (slice 10). The known-open BLE risks are unchanged:
open DFU/img_mgmt + NUS shell (KNOWN DR-18, accepted posture), adv name compile-time (DR-54), adv
start no-retry (DR-50), `fx_ble_adv` stub so the SM can't actually gate advertising (DR-55).

---

## Part B — Correctness hazards (ranked, all re-verified on today's main)

| # | Finding | Status | Files | Notes |
|---|---------|--------|-------|-------|
| B1 | Poison record stalls drain forever: server 4xx on the head batch → `uploader_drain` retries the same batch until link drop; no-fix records (indoor start) are the likely trigger | **KNOWN DR-01 — open** | `src/upload/uploader.c:73-84`, `src/transport/lte_transport.c` (all non-2xx → `-EIO`) | Slice 3. HTTP 4xx is indistinguishable from transport failure today |
| B2 | Data file never compacted; overflow rejects newest (`-ENOMEM`) while docs promise delete-oldest | **KNOWN DR-14/DR-15 — open** | `src/data/data_queue.c:266-269,369-431` | Multi-day soak fails; overflow loses the *newest* (most valuable) fixes. Slice 4 |
| B3 | Command idempotency: `id < last_id` ignored without re-ack (server DB reset bricks the channel, ADR 0005 says re-ack); `save_last` failure logged then execution proceeds (reboot-loop hole) | **KNOWN DR-30/DR-31 — open** | `src/command/command.c:89-97`, `command_service.c:106-113` | test_older_id_ignored locks in the ADR deviation. Slice 5 |
| B4 | Begin-alarm races: stale re-arm can strand WAIT_BEGIN (evt-handler re-arm outside lock, no generation check); timer→SM posts silently dropped on full msgq with `alarm_outstanding` already cleared; no `clock_cancel_begin` | **KNOWN DR-32/DR-33/DR-34 — open** | `src/clock/clock.c:106-161`, `src/state/tracker_effects.c:51-56` | Verified: `date_time_evt_handler` snapshots then calls `clock_arm_begin(begin)` unlocked. Slice 6 |
| B5 | `gps_on()` non-shutdown failure ignored: cycle burns the full acq budget waiting on a dead receiver — **and** `prod_gps_on` runs `agnss_ensure_applied()` *before* the core sees the rc, so during poweroff a racing cycle can fire a 3 s PMTK query + ~27 KB EPO upload at a refused/powered-off receiver inside the 1 s stop window | **KNOWN DR-26 — open; poweroff-race angle NEW** | `src/tracking/sampler.c:31,91-100` | Cheap fix: gate ensure_applied + wait loop on `gps_on()==0`. Slice 8 |
| B6 | SMP EPO write not serialized against `epo_mtk_apply` packet reads (`epo_file_mutex` is per-packet; fs_mgmt writes the file directly) → interleaved old/new packets streamed to the L76 | **KNOWN DR-08 — open** | `src/agnss/epo_mtk.c:55-103`, `epo_storage.c` | Slice 8 |
| B7 | `main()` returns if `ble_peripheral_init` fails — no SM, no tracking, no long-press; every other init is log-and-continue | **KNOWN DR-36 — open** | `src/main.c:102-106` | One-line fix. Slice 10 |
| B8 | `data_queue_peek` returns aliases into the shared static `peek_buf` with the lock dropped; shell `data_queue peek/decode` between uploader peek and assemble corrupts the batch | **KNOWN DR-47 — open** | `src/data/data_queue.c:25,297-367` | Contract undocumented. Slice 4 rider |
| B9 | Partial drain counts as success (backoff never engages if batch 1 lands); ack() rc ignored (meta-save failure → duplicate re-POST loop) | **KNOWN DR-42/DR-41 — open** | `src/upload/uploader.c:80,84` | Slice 3 |
| B10 | Server `sleep` command's ack can't be sent until wake (SLEEP sets uploader OFF; ack rides the next ACTIVE drain; idempotent re-ack covers it) | **NEW (informational)** | `src/state/tracker_sm.c:202-210`, `uploader_service.c` | Correct-by-idempotency; latency quirk only. No action, documented here |

**Fixed since the DR review (verified in code, don't re-fix)**: DR-02/03 (CEREG gates + `link_up_edge`
backoff reset), DR-04 faces b/c (shutdown latch + `sampler_stop_sync` — face (a) remains, see A1),
DR-05 (quiesce handshake), DR-06 (SM stack 2048 Kconfig), DR-07/DR-20 (agnss dirty CAS + write-only
notify), DR-11 (per-event allowlist + `TRACKER_SM_COMMAND` production Kconfig), DR-13 (ZBASIC gone
from dfu.conf), DR-16 (CMake warning + `-SIM` adv/banner marker), DR-29 (asserting agnss HIL test).

**Still-open DR items not individually re-argued here** (spot-checked, unchanged): DR-09, DR-17 (no CI
— still true, no `.github/` in repo), DR-19 (bench gate — operational), DR-21..25, DR-27/28, DR-35,
DR-37..40, DR-43..47, DR-49/50, DR-51..63, DR-65..72.

---

## What the pre-existing review covered vs. what this pass adds

- **demo_readiness_plan.md** covered demo-survival correctness exhaustively (72 findings) — this pass
  re-verified its open/fixed status against `d6ff34b` (table above) instead of re-deriving it.
- **NEW here**: A1 (one-shot cancel seam / SLEEP GPS leak — the concrete residual of DR-04(a)),
  A3 (filesystem deletion-test verdict — retire, don't polish), A5 (allowlist↔shell-module coupling +
  `led` over-grant), A6 (agnss port-by-port deletion-test assessment), A8 (cadence semantics),
  A9/A10 (threading/Kconfig/SDK-boundary/data-path/BLE-absorption verdicts), B5's poweroff-race angle,
  B10, and the timestamp back-dating design-vs-code divergence.
- **Elevated here**: A2 (DR-10) from demo-major to top product defect, because #42/#43 made resets
  server-invocable routine events.
