Detection and recovery map for this issue, traced at pinned SHAs.

Pinned: nRFTrackerFW `7150f1353cc1345cb8bc801988ae3a6aab936b43`, nrfmodule-core `449049287f73cc53257eda2c58440ba36503b8dc`, nrfmodule-sdk `d6302443fd6ce426f9255685cf116b0bd3663a6b`. Bench evidence cross-referenced from nrfmodule-core#64.

## 1. Detection map

Emitter is nrfmodule-core.

- Counter `at_consecutive_timeouts`: nrfmodule-core/src/client/nrf_modem_at.c:271. Increment at nrf_modem_at.c:302.
- Two paths count a timeout: command-phase -EAGAIN (nrf_modem_at.c:444-446) and wake-ladder exhaustion returning -ETIMEDOUT (nrf_modem_at.c:401-405). Wake-path -EAGAIN is lock contention and is excluded (:403-404).
- Threshold: `CONFIG_NRFMODULE_AT_TIMEOUT_RECOVERY_THRESHOLD`, default 5, range 2..20 (nrfmodule-core/src/client/Kconfig:67-70). Check at nrf_modem_at.c:304.
- On firing: one LOG_WRN (nrf_modem_at.c:316), then one app callback (nrf_modem_at.c:321-325).
- Consumer mechanism: a single callback pointer, set via `nrf_modem_at_link_dark_handler_set()` (nrfmodule-sdk/include/nrf_modem_at.h:70 and :89, implemented at nrfmodule-core/src/client/nrf_modem_at.c:550-555). Handler contract: runs on the failing caller's thread with the AT lock held, must not block (nrfmodule-sdk/include/nrf_modem_at.h:62-68).
- Spacing: firings at least `CONFIG_NRFMODULE_AT_TIMEOUT_RECOVERY_SPACING_S` apart, default 1800 s with a hard Kconfig floor of 1800 (Kconfig:79-82, check at nrf_modem_at.c:308-314).
- Counter resets on any successful command phase (nrf_modem_at.c:452) and after a firing (:339). Data-mode payload TX success does not reset it (:495-497).

Consumers on main: zero.

- Tracker-wide search for `link_dark` and the setter: one hit, a docs line stating the handler is never registered (nRFTrackerFW/docs/runtime.md:393). Zero hits in nRFTrackerFW/src, configs, boards, overlays, tests.
- The in-library fallback `CONFIG_NRFMODULE_AT_TIMEOUT_AUTO_RESET` defaults n (nrfmodule-core/src/client/Kconfig:90-92) and is set nowhere in the tracker tree.

The no-consumer claim in this issue is confirmed at the pinned SHAs. When the event fires, the core logs one warning, checks a NULL handler pointer (nrf_modem_at.c:323), and does nothing else.

## 2. Recovery paths on main today

None reach the modem. PR #222 implements the recovery ladder but is unmerged, held for policy sign-off. Main has none of it.

- Uploader: a POST failing with -11 is logged and the records stay queued (nRFTrackerFW/src/upload/uploader.c:121-124, nRFTrackerFW/src/transport/lte_transport.c:170-172). Pacing: normal cadence (send_interval, default 30 s) for the first 2 failures, then exponential backoff, base 60 s, cap 3600 s (nRFTrackerFW/src/sync/sync_policy.c:79-105, nRFTrackerFW/src/upload/Kconfig:43-45). No escalation. That is documented as deliberate (nRFTrackerFW/docs/architecture.md:388-390).
- Link gating: there is no `link_policy` file. The authority is the `registered` latch in nRFTrackerFW/src/modem/modem_lte.c, written only by lte_lc events (:119 set, :143 clear). No timer, no staleness check. Modem dark after registration: latch stays 1, POSTs keep failing on the backoff ladder. Dark before registration: latch stays 0, no POST is ever attempted (sync_policy.c:41-45).
- Modem reset driver: `nrf_modem_lib_reset` has zero call sites in the tracker. `AT#XRESET` has zero hits in tracker src/configs/boards/overlays. The `n91_rst` line (P1.02, nrfmodule-sdk/boards/arm/pigeontracker/pigeontracker_nrf52840.dts:103-111) has zero consumers across all three repos.
- Watchdog: zero across the tracker tree and the core tree. nRFTrackerFW/docs/architecture.md:390 claims "a hardware watchdog handles it"; no config enables one. The doc is wrong on main.
- Latch bug from nrfmodule-core#64: no code path sets the awake latch back to IDLE on a command timeout. With the latch stuck at AWAKE, every command skips the wake ladder (nrfmodule-core/src/client/sm_modem_power_mgmt.c:73-76) and burns its full timeout. The only AWAKE-to-IDLE writer is the sleep path (:162).

Can a wedged modem come back without a user reboot? Only if the modem recovers by itself. If `registered` stayed 1, the next backoff attempt succeeds and cadence resumes (sync_policy.c:72-76). If `registered` is 0, recovery needs a CEREG URC; the tracker never re-drives registration except on dock undock (nRFTrackerFW/src/state/dock_power.c:157) or the manual shell command (nRFTrackerFW/src/modem/modem_lte_shell.c:90). A modem that comes back with wiped CFUN/URC state has no tracker path back short of a dock cycle, a shell command, or a host reboot.

## 3. Blast radius, modem dark indefinitely

| | Positions | Uploads | data_queue | BLE |
|---|---|---|---|---|
| LiveTracker | Unaffected. GNSS is a Quectel L76 on its own UART (nRFTrackerFW/boards/livetracker_nrf52840.overlay:21-29). Real fixes keep landing. | Dead. Dark after registration: attempts on the backoff ladder, at most one per 3600 s. Dark before: never attempted (SYNC_WAIT_LINK_DOWN, sync_policy.c:41-45). | Records with real fixes keep enqueueing. Byte budget is (partition - 64 KiB) * 15/16, 1,904,640 B on the 2 MB partition, about 30k records (nRFTrackerFW/src/data/data_queue.c:24-27, nRFTrackerFW/overlays/partitions.overlay:51-54). When full, whole oldest closed segments are dropped so the newest record fits (data_queue.c:469-475, drop at :172-215). Oldest positions are lost, newest kept. | Up. Dark from boot: error byte shows nothing, only `lte_connected` false. Dark after registration: `last_drain_failed` sets the upload error flag (nRFTrackerFW/src/advertising/adv_sampler.c:188). |
| PigeonTracker | Dead. GNSS rides the same AT bridge (`nrfmodule,gnss-nrf91-slm`, nrfmodule-sdk/boards/arm/pigeontracker/pigeontracker_nrf52840.dts:64-67). Every 10 s cycle burns one ~10 s start timeout plus one ~10 s stop timeout and stores a fix-less record (nRFTrackerFW/src/tracking/sampler.c:32-70, retry wait at :277). No backoff, no failure counter. A dead-modem cycle is log-identical to an indoor no-fix cycle (nRFTrackerFW/src/gnss/gnss_producer.c:122-123). | Same as LiveTracker. | Same mechanics, but the queue fills with fix-less records (battery/time/baro only, nRFTrackerFW/src/collector/collector.c:132-189). ~30k stored, then oldest segments drop-rotate. | Up. Advert error byte shows GPS_TIMEOUT (adv_sampler.c:181-182). Boot with a dark modem delays advertising ~30 s while `modem_lte_init` walks the probe ladder (nrfmodule-core/src/client/nrf_modem_lib.c:99-125). DIS serial stays "unknown", so the hub cannot map the device to an IMEI (nRFTrackerFW/src/main.c:91-95). |

The state machine never observes any of this. Its event set has no failure event (nRFTrackerFW/src/state/tracker_sm.h:17-26). The LED shows the same activity pulse for a TIMEOUT cycle as for a fix (nRFTrackerFW/src/led/led_sources.c:168-174).

## 4. Recovery ladder: assessment of PR #222 against the traces and nrfmodule-core#64

The #222 rungs match every wedge shape observed so far. No competing design needed. Gaps the ladder does not cover, and one per-rung note each:

- Rung 1 vs the #64 latch desync: `nrf_modem_lib_reset()` does reach a modem asleep behind a stuck-AWAKE latch, because it toggles DTR itself (nrfmodule-core/src/client/nrf_modem_lib.c:179-182) and falls back to a 1 s DTR power cycle (:198-209), independent of the wake ladder. But it does not repair the latch: on success it writes no power state (:157-160) and relies on the next `ensure_awake()`, which self-heals only from IDLE. After a rung-1 recovery of the #64 shape the latch is still AWAKE, so the next self-initiated modem sleep recreates the wedge, and the spacing gate holds the next firing at least 1800 s away. Rung 1 treats episodes. The #64 root cause is a core-side latch bug (a timeout should invalidate the AWAKE latch) and must be fixed in nrfmodule-core.
- Detection gap, flapping: any successful command phase zeroes the counter (nrf_modem_at.c:452). The #64 capture shows windows where queued responses flush and commands succeed. Flapping with fewer than 5 consecutive timeouts between good windows never fires the event. The #64 log shows it did fire once in that burst, so 5-in-a-row occurred there, but the threshold is not guaranteed to trip on this shape.
- Detection gap, no traffic: the counter moves only when AT commands are issued. On LiveTracker with the modem dark before registration, GNSS is off the bridge and the uploader never attempts (sync_policy.c:41-45), so nothing generates AT traffic and the event can never fire. PigeonTracker is covered only by accident: its GNSS cycle guarantees 2 AT commands per 10 s.
- Detection gap, spacing residue: `at_last_event_uptime_ms` is never cleared (nrf_modem_at.c:273, gate at :312), so a new wedge within 30 min of a previous, recovered one is silently suppressed. #222 clears its rung state on registration, but this core-side gate still delays the first firing of the next episode.
- Socket leak (#64 secondary finding): a failed `#XCLOSE` leaks the SLM-side socket. A fired rung 1 cleans up incidentally, because `AT#XRESET` reboots SLM and clears its socket table. During sub-threshold flapping nothing fires and leaked sockets accumulate until SLM's table exhausts, undetected. Needs a core-side answer (retry the close, or count leaks), not a ladder rung.
- Rung 2: compile-gated on the `n91_rst` DT node, which exists only on PigeonTracker (nrfmodule-sdk dts:103-111). It is the only rung that reaches a modem whose AT parser and DTR handling are both dead.
- Rung 3 and LiveTracker: `sys_reboot` restarts the nRF52840 only. Its path to the modem is the boot-time `AT#XRESET` in `nrf_modem_lib_init()` (nrf_modem_lib.c:116-118), the same soft path rung 1 already tried. So on LiveTracker a hard-hung SLM stays unrecoverable even with the full ladder, and rung 3's reboot budget caps the resulting reboots correctly. The issue's last paragraph stands: that failure class needs the 9151-side watchdog / reset-on-fatal change, or the next HW rev's reset line.
- Watchdog: neither MCU has one at these SHAs. #222's own recovery thread (deferral via semaphore to a prio-10 thread matches the handler contract) is itself unsupervised. A task watchdog is a separate issue, not a rung.
- Threshold accounting: `put_modem_to_sleep()`'s direct `sm_at_client_send_cmd()` calls are not counted, an accepted core gap (nrf_modem_at.c:268-270).

Summary: merge of #222 is blocked only on the three policy values. Independent of #222, the core side owes fixes for: the #64 AWAKE-latch bug, the flapping detection gap, the `#XCLOSE` socket leak, and the spacing residue.
