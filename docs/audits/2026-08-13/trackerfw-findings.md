# nRFTrackerFW audit findings, 2026-08-13

- Date: 2026-08-13
- Pinned SHA: 7150f1353cc1345cb8bc801988ae3a6aab936b43 (nRFTrackerFW main, contains v0.4.0)
- Scope: code merged since the 07-29 audit. PRs reviewed: #202, #203, #209, #211, #212, #218, #219, #220, #221, #223, #224, #225, #226, #228, plus a rubric pass and an over-engineering pass.
- Method: parallel dimension reviewers, then one adversarial verifier per finding. 14 candidates of 18 survived verification; 13 are in this repo. Three findings independently confirmed the same hil.conf defect and two confirmed the same uploader race, so this report lists 10 distinct defects.
- Severity counts (distinct defects): 1 blocker, 5 should-fix, 4 nit.

## Build and configuration

### 1. Raw modem AT shell ships in every image, including the v0.4.0 release [blocker]

- File: configs/hil.conf:8
- Claim: CONFIG_NRFMODULE_SM_AT_CLIENT_SHELL=y was added for bench builds (PR #211, commit 488ca4d) but hil.conf sits in the unconditional EXTRA_CONF_FILE list (CMakeLists.txt:20), so smat (raw AT passthrough) and smsh (DTR/UART controls that bypass power management state) are in all release builds for both boards, reachable over the unpaired BLE NUS shell.
- Evidence: no config fragment ever sets the symbol back to n; configs/shell.conf:5 enables CONFIG_SHELL_BT_NUS=y in all images with no pairing (open #179); the repo's own note in configs/gnss_modem.conf:37-44 says this option must come out before field builds; git tag --contains 488ca4d includes v0.4.0. Any nearby phone can issue AT+CFUN=0 or %XFACTORYRESET to a tracker in the field.
- Confirmed independently by three reviewers (build, rubric, over-engineering passes).

## LED

### 2. Battery-critical cue keeps the 40 ms render tick running for the rest of battery life [should-fix]

- File: src/led/led.c:326
- Claim: led_indicator_battery_critical installs a looping LED_EFFECT_FLASH(80, 5000) with lifetime 0; a looping slot never retires in the SDK arbiter and the engine re-arms its 40 ms tick while any slot is live, so once battery is below 3300 mV off USB the system workqueue wakes about 25 times per second, rendering black for 4.92 s of every 5 s, until the battery dies.
- Evidence: effect defined at led.c:99-101; sdk led_arbiter.c:17-30 never sets done for a looping effect with expire_ms 0; sdk rgb_led.c:46-48 re-arms at RGB_LED_TICK_MS. Nothing bounds the condition: auto-mute does not cover the BATT_CRIT layer (led.c:206-210) and there is no battery-driven poweroff. The tracking base layer got LED_TRACK_AUTO_OFF_MS = 180000 (led.c:24) for exactly this reason. Engages when reserve is smallest.

### 3. LED_CUE_CLASS_WARNING is dead flexibility [nit]

- File: src/led/led_mute.h:26
- Claim: the three-value cue class enum is a bool in practice; WARNING behaves identically to ALWAYS everywhere.
- Evidence: the only consumer, led_mute_allows() (led_mute.c:44), tests cue_class != LED_CUE_CLASS_MUTED; WARNING appears only in the enum, one cue_defs row (led.c:178), and tests that assert it behaves like ALWAYS (test_led_mute/src/main.c:34,45). The header doc claims a rank order the policy does not implement.

## Button and shutdown

### 4. Ignored long-press still counts as user activity and lifts the LED auto-mute [should-fix]

- File: src/button/button.c:122
- Claim: emit() calls led_indicator_user_activity() before the TRACKER_BUTTON_POWEROFF gate discards the gesture, so the Q2 thermal fake long-press that PR #209 exists to neutralize still lifts or postpones the 30 min LED auto-mute mid-flight.
- Evidence: button.c:117-123 runs the activity call unconditionally; handle_long() (button.c:55-67) only suppresses the EV_BUTTON_LONG post; the fake hold arrives as exactly a LONG gesture (input-longpress emits INPUT_KEY_X on a 3 s hold, ADR 0004 documents the thermal fake); led_mute.c:81-94 restarts the window and lifts an active mute. A recurring fake press keeps the LED cue drain enabled for the flight.

### 5. wait_button_release misclassifies the marginal Q2 case it exists to diagnose [nit]

- File: src/state/tracker_effects.c:256
- Claim: the release-wait loop exits on the first low sample with no confirming re-read, so a flickering or leaking button logs "button released after N ms" while a clean release that bounces high at the post-loop re-check logs "(release timeout)" far below the 10 s timeout.
- Evidence: lines 251-260 sample on a 20 ms grid and branch on a single instantaneous re-check; the shutdown then arms LEVEL_ACTIVE wake on the flickering pin (lines 342-346), so the device reboots instead of powering off under a log line claiming a clean release. Only a solidly stuck pin rides the timeout. PR #226 sells the trace as separating those two cases.

### 6. Release notes advertise a hold-duration trace that does not exist [nit]

- File: src/state/tracker_effects.c:259
- Claim: the v0.4.0 release notes call the shutdown log a "button hold-duration trace", but the only related line measures time to release after the multi-second shutdown quiesce, and the code comment above it says it is not press duration.
- Evidence: release_assets/v0.4.0-NOTES.md:11 makes the claim; the counter starts only when fx_poweroff reaches the release wait, after the 3 s hold and the quiesce; no code in the tree records actual hold duration.

### 7. Shutdown flush no longer guarantees an fs_sync [should-fix]

- File: src/system/log_flush.c:30
- Claim: the refactor that moved the shutdown flush into log_flush.c (3684618) dropped the second LOG_INF that d54f530 posted on purpose, so a flush that lands with an otherwise-empty log queue drains its single marker, never triggers the FS backend's sync, then log_panic() deactivates the backend and the shutdown log tail dies in the littlefs cache.
- Evidence: in NCS v3.2.1, LOG_BACKEND_EVT_PROCESS_THREAD_DONE fires only for a pass with at least 2 queued messages (log_core.c:970-978, log_process() returns pending-after-processing) and log_backend_fs.c fs_syncs only in the DONE handler. The moved version posts one line and its comment misstates the mechanism. Live paths: the fallback flush when device_is_ready(power_latch) fails (tracker_effects.c:336) and every future caller, including the modem recovery cold reboot named in 3684618's own commit message. Fix is one restored LOG_INF.

## Uploader

### 8. Kick vs quiesce TOCTOU lets a drain POST race modem teardown during poweroff [should-fix]

- Files: src/upload/uploader_service.c:395 and :305
- Claim: uploader_service_kick() reads kick_enabled then ORs kick_req with no lock; a kicker preempted between the two lines survives the whole quiesce handshake and its atomic_or lands after quiesce's final kick_req clear (:429). run() consumes the flags at :305 with no kick_enabled re-check, so the service serves the kick after uploader_service_quiesce() reported done, running an HTTP POST or config fetch concurrently with fx_poweroff's modem teardown.
- Evidence: the schedule is realistic with real priorities (kicker sampler thread prio 7, SM and uploader prio 5; fx_poweroff quiesces the uploader before sampler_stop_sync, so the sampler is live mid-kick and starved through the handshake); the drain and config steps gate only on the already-consumed quiesce_req and on link_up, which stays true until modem_lte_offline (tracker_effects.c:311). Result is the DTR-wake, modem-left-registered-at-mA hazard the gate's own comment (:90-94) exists to prevent. Fix: in run(), discard consumed kicks when kick_enabled is 0.
- Confirmed independently by two reviewers (small-fixes and rubric passes).

## Config transport

### 9. Non-ASCII name is dropped whole while the config version is recorded as applied [nit]

- File: src/config/config_decode.c:176
- Claim: a server name with any byte outside 0x20-0x7E is dropped, but apply() stores v into applied_version unconditionally, so the next upload echoes cv == v, the cv-gated server sends empty bodies, and the rename is never re-offered until the version changes or the device reboots.
- Evidence: drop at config_decode.c:176-179, version store at :227-229; applied_version is RAM only, so each boot re-fetches and re-drops with one WRN; there is no feedback channel telling the server the name did not apply. The drop-whole behavior is documented; the unretryable interaction is not. A name like "Golob st. 5" with s-caron is plausible in this market.

## Tooling

### 10. ble_download_logs.py rejects every PigeonTracker [should-fix]

- File: scripts/ble_download_logs.py:60
- Claim: PRODUCT_ID is hardcoded to 0x04 (LiveTracker) and the detection callback drops any advertisement where value[1] != PRODUCT_ID, so the script exits "tracker not found" on PigeonTracker, which advertises product_id 0x05.
- Evidence: Kconfig.identity:19 defaults CONFIG_TRACKER_ADV_PRODUCT_ID to 0x05 on BOARD_PIGEONTRACKER_NRF52840; tracker_adv.c:31 puts the byte at payload offset 1; configs/rtt_console.conf turns USB fully off on pigeontracker, so this script is that board's only field log path. Same failure class as the proto byte PR #212 fixed at value[0].
