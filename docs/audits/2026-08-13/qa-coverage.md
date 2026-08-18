# QA coverage audit: nRFTrackerFW vs behavior spec v1.0

- Date: 2026-08-13
- Pinned SHA: 7150f1353cc1345cb8bc801988ae3a6aab936b43 (nRFTrackerFW main)
- Method: spec-first derivation blind to implementation, then mapping against the full test inventory (34 unit suites, 659 ztest functions, HIL pytest suites, bench scripts, CI gates).

## Method note and finding zero

The spec document ("GPS Tracker Firmware - Tehnicna specifikacija v1.0") is not checked into the repository. The only tracked reference to it is a section-number citation in docs/diagrams/tracker_state_machine.dot. Expected behaviors below were derived from the recorded section map of the boss's spec (sections 3-21) plus the boss-approved amendments (ACTIVE-is-default model 2026-06-17, DOCKED state 2026-08, clock-invalid wedge recovery, advertising proto v2). The implementation was not consulted to derive expectations; the worktree was consulted only to confirm what named tests assert.

Finding zero: commit the spec to docs/. An audit like this cannot cite exact section text until the document is in the tree.

## Coverage table

| Spec section | Expected behavior | Covering tests | Verdict |
|---|---|---|---|
| 3-4 | State machine OFF / WAIT_BEGIN / ACTIVE / SLEEP with priority OFF > SLEEP > WAIT_BEGIN > ACTIVE; boot fork on beginTime; per-state gating of GPS, uploader, LED, BLE | `test_tracker_sm` (85 tests: boot fork 01-04c, begin edges 05-07c, sleep 08-12, off/power 13-18b, next_wake 19-23) | COVERED |
| 5 | Restart is a fresh boot, no state persistence except beginTime; boot fork re-derives state | `test_tracker_sm` tests 24-29 (begin persistence), 27/29 (no rewrite at boot), 49 (init_ctx matches boot fork) | COVERED |
| 6 | Server config fields g (gpsSamplingInterval) and t (dataSendingInterval) decode, clamp, apply | `test_config_decode` (68 tests, JSON + CBOR, clamp, malformed, atomic reject), `test_tracker_params` (clamps, persistence), HIL `test_transport.py::test_config_rides_back` | COVERED |
| 6 | beginTime via config (set, clear via null, int64, saturation) | `test_config_decode` bt group (16 tests), `test_tracker_sm` persistence tests | COVERED |
| 6 | ledIndicatorMode config field | none; no decode test, no test anywhere (unknown-key tests prove the key is ignored safely) | UNCOVERED |
| 6 | maxFailedTransmissionAttempts | none; field declared vestigial by the recovery decision (backoff replaces it) | UNCOVERED (accepted by decision) |
| 7 | BeginTime semantics: Unix time, needs valid clock, defer/arm/fire, re-arm on re-sync; time from modem network time with GNSS time sink fallback | `test_clock` (17 tests), `test_tracker_sm` clock-synced group 30-37, `test_gnss_producer` time-sink tests | COVERED |
| 7 | Delay = now + secs as UI sugar over BeginTime (SetDelay command) | none found | UNCOVERED |
| 9 (amended) | Modem always PSM, disconnected-by-default, CEREG-gated opportunistic upload with interval, retry window, backoff to cap | `test_sync_policy` (34), `test_uploader_service` (33), `test_uploader` drain (14+6), HIL `test_modem_lte.py` (PSM grant, registration), `test_ri_wake.py` | COVERED |
| 9 | Sample -> store -> upload chain loses no records: flash queue, ack, rotation, drop-oldest, crash recovery | `test_data_queue` (34 tests incl. reboot persistence, deleted-meta recovery, superseded-ack, poisoned cursor), `test_collector`, `test_batch_envelope` | COVERED at unit level; PARTIAL on hardware: no HIL test runs the whole chain (real GPS sample to acked upload); `test_transport.py` posts one synthetic record only |
| 9 (amended) | Always send even with no fix: minimum payload imei + timestamp + battery | `test_collector` (imei-only, battery-without-fix, walltime stamp), `test_sampler` (timeout still samples) | COVERED |
| 12 (amended) | Recovery = exponential backoff for sends, system watchdog for true hangs | backoff: `test_sync_policy`, `test_uploader_service`. Watchdog: no test feeds, trips, or observes the WDT anywhere in the inventory. The T1 trace (same date) found no watchdog is configured at all on main: zero CONFIG_WATCHDOG/task_wdt hits in tracker and core. The gap is the missing feature plus its test. | PARTIAL: backoff covered, watchdog absent and untested |
| 13 | Button: tap = battery status blink, double-tap = GPS status blink, long-press 3 s = off; long-press refused on USB; click triggers config poll + sample + upload | `test_button_gesture` (8), `test_tracker_sm` 13/14/17/61/62, `test_click_flow` (11) | PARTIAL: detection, off path, and click flow covered; routing of tap/double-tap to the LED status blink is untested |
| 14 | Accelerometer double-tap (reserved) | none; feature reserved in spec, not implemented | UNCOVERED (accepted, reserved) |
| 15 / 21 | Command system: one table, three transports (shell, API cmd object, BLE); idempotency, persist-before-execute, ack via lc/lcs, allowlist | `test_command` (14: idempotency, persist-first, repeat id, stale id, ack truncation, boot with stored record), `test_command_allowlist` (5), `test_config_decode` cmd group (12), `test_batch_envelope` ack tests, `test_uploader_service` ack pacing tests, HIL `test_ble.py` NUS shell | COVERED for dispatch and ack plumbing; PARTIAL: the reboot command's ack surviving an actual reboot (the stated priority requirement) is proven only by unit-level persist-before-execute; no test reboots hardware and observes the re-ack |
| 16 | Advertising payload proto v2: 21 bytes, status, battery, position, flags, wake_kind bits 5-6, next_wake, last_error | `test_adv_codec` (11, golden vectors), `test_adv_sampler` (14, clamps and wake_kind derivation), HIL `test_ble.py` (golden vectors + live scan) | COVERED; PARTIAL detail: the DOCKED status value appears in no adv_codec or adv_sampler test (grep confirmed zero matches) |
| 17 | LED indication: per-state cues, mute policy, auto-mute, DFU phases | `test_led_mute` (13), `test_dfu_led` (6), `test_tracker_sm` entry-effect assertions | PARTIAL: policy and mapping covered; the LED render engine has no tests, and the 2026-08-13 bench pass found 4 LED bugs there |
| Amendment: DOCKED | Debounced VBUS enters DOCKED from any state, exit re-derives like the boot fork, dock worker settle handshake, begin survives docking | `test_tracker_sm` dock group (tests 38-70), `test_vbus_debounce` (9) | COVERED |
| Amendment: wedge recovery | Unevaluable beginTime never halts the device; EV_CLOCK_SYNCED reconciles | `test_tracker_sm` 30-37 | COVERED |
| Amendment: SLEEP keepalive | Hub Sleep command refreshes the timer in place, expiry re-derives | `test_tracker_sm` 11b, 08-12 | COVERED |

## Missing negative and boundary cases, ordered by product risk

1. End-to-end race chain on hardware (sections 3, 9). No HIL test runs boot -> ACTIVE -> real GPS acquisition -> enqueue -> upload -> ack as one chain. Every link is proven separately; the chain that decides whether race data reaches the server has never run under test. Highest risk: this is the product.
2. data_queue corrupted meta.bin (section 9). `test_meta_recovery_from_cold_start` covers a deleted meta file. A power cut can leave a torn or garbage meta file instead. Add a test that writes junk into meta.bin and asserts rederivation without record loss.
3. Reboot command ack survives a real reboot (section 15). Add a HIL case: deliver a reboot cmd id, observe the reboot, assert the next upload acks the persisted id with Success. The unit tests prove the persistence logic, not the boot-side path on hardware.
4. Watchdog (section 12). No watchdog is configured on main at all (T1 trace: zero watchdog config in tracker and core), so there is nothing to test yet. The amended spec calls for one. A wedged tracker mid-race transmits nothing until the battery dies. Once enabled: HIL candidate, wedge a thread via shell hook, assert reset and wake_cause DOG.
5. DOCKED status value in the advert (section 16, proto v2). The hub decides behavior from the status byte; no encode test pins the DOCKED value. One golden-vector test in `test_adv_codec`.
6. Boot fork with beginTime exactly equal to now (section 7). `test_eval_fire_now_when_equal` covers the clock predicate; no `test_tracker_sm` boot-fork case pins begin == now to ACTIVE.
7. Tap and double-tap routing to the LED status blink (section 13). Detector and LED policy are tested; the glue between them is not. Cosmetic, but it is the only user-visible battery check in the field.
8. ledIndicatorMode config field (section 6). Not decoded and not tested. Unknown-key tests prove a server sending it does no harm, so the gap is the missing feature, not a safety hole.

## Materiality verdict

Yes, the gaps are material enough for one tracker issue. Items 1-4 all sit on the paths that lose race data or strand a device mid-race (unproven end-to-end chain, torn queue metadata, reboot-ack, watchdog), and none of them is covered by any planned work I can see in the inventory.

## DRAFT ISSUE

Title: QA coverage gaps vs behavior spec v1.0: race-chain HIL, queue meta corruption, reboot-ack on hardware, watchdog

Body:

Coverage audit of main @ 7150f13 against the boss behavior spec v1.0 plus approved amendments (full table in nrfmodule-dev-manifest docs/audits/2026-08-13/qa-coverage.md).

Summary: 13 of 19 spec areas COVERED, 5 PARTIAL (data-path on hardware, recovery/watchdog, button LED routing, reboot-ack proof, LED engine), 3 UNCOVERED but accepted or reserved (ledIndicatorMode, maxFailedTransmissionAttempts, accelerometer). The unit inventory is strong (659 tests); the gaps cluster on hardware proof of the loss-critical paths.

Top missing cases, in risk order:

1. HIL end-to-end race chain: boot -> ACTIVE -> real GPS sample -> enqueue -> upload -> ack, as one test. Every link is tested alone; the chain is not.
2. data_queue recovery from a corrupted (not deleted) meta.bin: write junk bytes, assert rederivation without record loss.
3. HIL reboot-command ack: deliver a reboot cmd, observe the reboot, assert the persisted id is acked Success on the next upload. This is the boss's stated priority requirement for the command system.
4. Watchdog: none is configured on main (see the #210 trace comment), and no test covers one. The amended spec calls for a system watchdog. Enable it, then bench-prove it: wedge a thread, assert reset with wake_cause DOG.
5. Unit golden vector for the DOCKED status value in the advert (proto v2, hub-facing).
6. tracker_sm boot-fork case for beginTime == now.

Also: the spec document itself is not committed. Commit it to docs/ so future audits can cite section text.
