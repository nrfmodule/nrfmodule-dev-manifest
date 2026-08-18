# Issues to file from the 2026-08-13 audit

Dedupe basis: open issue list snapshot 2026-08-13. Findings map to 8 new nRFTrackerFW issues, 1 new nrfmodule-sdk issue, 1 extension of an open issue. Nothing routes to the T3 docs PR: the only doc drift found is in release notes and a code comment, both handled inside their issues. No finding is dropped without a tracker entry.

---

## NEW: nRFTrackerFW

### 1. security: raw modem AT shell (smat/smsh) ships in every image, including the v0.4.0 release

Severity: blocker. Not covered by #179 or #168; those track BLE pairing, this is a config wiring bug that widens what the unpaired shell can reach.

Body:

> configs/hil.conf:8 sets CONFIG_NRFMODULE_SM_AT_CLIENT_SHELL=y. CMakeLists.txt:20 merges hil.conf into the base EXTRA_CONF_FILE list with no flavor gate, so the symbol is in every build for both boards, including the shipped v0.4.0 livetracker image (git tag --contains 488ca4d includes v0.4.0).
>
> What this exposes: smat is raw AT passthrough to the modem, smsh is DTR/UART controls that bypass power management state (nrfmodule-core src/serial_modem_client/Kconfig:73-78). The shell runs over BLE NUS in all images (configs/shell.conf:5) and pairing is not implemented (#179), so any nearby phone can issue AT+CFUN=0 or %XFACTORYRESET to a tracker in the field.
>
> The adding commit (488ca4d, PR #211) says "all bench builds" and hil.conf's own header says "Safe to drop from production builds", but nothing ever drops it. The repo's own note in configs/gnss_modem.conf:37-44 says this option must come out before field builds.
>
> Fix: move the line to a bench-only fragment (gnss_nrf91.conf:39 and gnss_modem.conf:44 already set it for bench flavors), or gate hil.conf on a build flavor. Related: #179, #168.

### 2. power: battery-critical LED layer keeps the 40 ms render tick alive for the rest of battery life

Severity: should-fix. No open issue covers it (#159 and #160 are unrelated power items).

Body:

> src/led/led.c:326 installs the battery-critical cue as a looping LED_EFFECT_FLASH(80, 5000) with lifetime 0 (effect at led.c:99-101). A looping slot never retires in the SDK arbiter (led_arbiter.c:17-30) and the engine re-arms its 40 ms tick while any slot is live (rgb_led.c:46-48). Once battery is below 3300 mV off USB, the system workqueue wakes about 25 times per second, rendering black for 4.92 s of every 5 s, until the battery dies.
>
> Nothing bounds it: the condition clears only on USB or recovery above threshold, auto-mute does not cover the BATT_CRIT layer (led.c:206-210), and there is no battery-driven poweroff. The tracking base layer got LED_TRACK_AUTO_OFF_MS = 180000 (led.c:24) for exactly this reason. This engages when battery reserve is smallest.
>
> Fix options: give the critical cue an auto-off like tracking, or a finite lifetime re-triggered from the 3 s battery poll in led_sources.c.

### 3. log_flush: shutdown flush no longer guarantees an fs_sync

Severity: should-fix. Fix is one restored LOG_INF plus a comment correction.

Body:

> log_flush_for_shutdown() (src/system/log_flush.c:30, from 3684618) posts one LOG_INF marker. In NCS v3.2.1 the FS backend runs fs_sync only in its PROCESS_THREAD_DONE handler, and DONE fires only for a pass that had at least 2 queued messages (log_core.c:970-978; log_process() returns pending-after-processing-one). A flush that lands with an otherwise-empty queue drains the single marker, never gets DONE, then log_panic() deactivates the backend before its flush loop and the unsynced shutdown tail dies in the littlefs cache.
>
> The original flush (d54f530) posted two lines with a comment explaining this exact precondition; the move into log_flush.c dropped the second line and the new comment (log_flush.c:28-29) wrongly claims one line is enough.
>
> Live paths today: the fallback flush when device_is_ready(power_latch) fails (tracker_effects.c:336, its nearest predecessor line is 50 ms earlier so the 1 s log timer can split them), and every future caller, including the modem recovery cold reboot named in 3684618's own commit message.
>
> Fix: restore the second LOG_INF and correct the comment.

### 4. button: ignored long-press still counts as user activity and lifts the LED auto-mute

Severity: should-fix. #228 (merged) built the auto-mute; no open issue covers this leak.

Body:

> emit() (src/button/button.c:117-123) calls led_indicator_user_activity() before the switch, so BUTTON_GESTURE_LONG registers as user activity even when handle_long() (button.c:55-67) discards it because TRACKER_BUTTON_POWEROFF is off (the default).
>
> The Q2 thermal fake hold that the poweroff gate exists to neutralize (ADR 0004) arrives as exactly a LONG gesture: input-longpress emits INPUT_KEY_X on a 3 s hold and on_input maps it to LONG. led_mute_user_activity() (led_mute.c:81-94) both restarts the 30 min auto-mute window and lifts an active mute. A recurring thermal fake press mid-flight therefore keeps the LED cue drain enabled for the whole flight.
>
> Fix: do not count a LONG gesture as user activity when the poweroff gate discards it. Taps and double-taps still lift the mute for real fingers.

### 5. scripts: ble_download_logs.py rejects every PigeonTracker (product_id filter hardcoded to 0x04)

Severity: should-fix. Same failure class as the proto byte PR #212 fixed.

Body:

> scripts/ble_download_logs.py:60 sets PRODUCT_ID = 0x04 (LiveTracker) and the detection callback at line 268 drops any advertisement where value[1] != PRODUCT_ID. PigeonTracker advertises product_id 0x05 (Kconfig.identity:19, byte at payload offset 1 per tracker_adv.c:31), so the script exits "tracker not found" on that board. There is no CLI override.
>
> This matters because configs/rtt_console.conf turns USB fully off on pigeontracker, so this script is that board's only field log pull path.
>
> Fix: accept both known product ids, or add a --product option. PR #212 fixed the same class of staleness for the proto byte at value[0].

### 6. uploader: kick vs quiesce TOCTOU lets a drain POST race modem teardown during poweroff

Severity: should-fix. Confirmed by two independent reviewers. One-line fix.

Body:

> uploader_service_kick() reads kick_enabled (src/upload/uploader_service.c:395) then ORs kick_req (:399) with no lock. A kicker preempted between the two lines survives the whole quiesce handshake; its atomic_or lands after uploader_service_quiesce()'s final kick_req clear (:429). run() consumes the flags at :305 with no kick_enabled re-check, and the drain and config steps gate only on quiesce_req (already CAS-consumed by the handshake) and link_up, which stays true until modem_lte_offline (tracker_effects.c:311).
>
> The schedule is real: the kicker is click_flow's on_sample_done on the sampler thread (prio 7), SM and uploader run at prio 5, and fx_poweroff quiesces the uploader before sampler_stop_sync, so the sampler is live mid-kick and starved through the handshake.
>
> Result: an HTTP POST or config fetch runs concurrently with the CFUN=0/XSLEEP teardown, DTR-wakes the modem, and can leave it registered at mA through System OFF. This is the hazard the gate's own comment (:90-94) exists to prevent.
>
> Fix: in run(), discard consumed kicks when atomic_get(&kick_enabled) == 0, making the gate closure authoritative on the service thread.

### 7. shutdown: wait_button_release misreports the marginal Q2 case it exists to diagnose

Severity: nit (two grouped findings). The diagnostic from PR #226 fails on its target case and the release notes oversell it.

Body:

> Two related problems in the poweroff release-wait diagnostic (src/state/tracker_effects.c:251-260):
>
> 1. The poll loop exits on the first low sample (20 ms grid, no confirming re-read), then a single instantaneous re-check picks the log branch. A marginally leaking Q2 that flickers logs "button released after N ms"; the shutdown then arms LEVEL_ACTIVE wake on the flickering pin (lines 342-346) and the device reboots instead of powering off, under a log line claiming a clean release. Only a solidly stuck pin rides the 10 s timeout. The WRN branch also hardcodes "(release timeout)" even when waited_ms is far below 10 s.
>
> 2. The v0.4.0 release notes (release_assets/v0.4.0-NOTES.md:11) call this a "button hold-duration trace", but the counter starts after the multi-second shutdown quiesce and the comment at lines 239-242 says it is not press duration. No code records actual hold duration.
>
> Fix: require M consecutive low samples before declaring release, make the WRN text state the actual condition, and correct the notes wording (or log real hold duration from the input-longpress timestamps if wanted).

### 8. config: non-ASCII name is dropped but the config version is recorded as applied

Severity: nit, but needs a contract decision with the server side. No open issue covers it (#183 is a different decode gap).

Body:

> gather_name drops the whole name on any byte outside 0x20-0x7E (src/config/config_decode.c:176-179), but apply() stores v into applied_version unconditionally (:227-229). The next upload echoes cv == v, the cv-gated server sends empty bodies, and the dropped rename is never re-offered until the version changes or the device reboots (applied_version is RAM only, so each boot re-fetches and re-drops with one WRN).
>
> There is no feedback channel telling the server the name did not apply. A name with non-ASCII characters ("Golob st. 5" with s-caron) is plausible in this market. The drop-whole behavior is documented in config_decode.h; the interaction that makes the drop unretryable is not.
>
> Options: transliterate instead of dropping, or skip the applied_version store when a field was dropped, or add a status field to the upload. Pick one with the server side.

---

## NEW: nrfmodule-sdk

### 9. board_power: fold the per-board copies into lib/power (three forks, one already stale)

Severity: should-fix. Distinct from sdk#39, which becomes a one-place edit after this.

Body:

> boards/arm/pigeontracker/board_power.c and boards/arm/livetracker/board_power.c are byte-identical 281-line files except the board name in the line-2 comment. PR #38 grew both copies by the same 130 lines (debounce work item, shell-log-backend gate, app-owned enable).
>
> The file has no board-specific content: VBUS is read from the NRF_POWER register, the USBD context is found via STRUCT_SECTION_FOREACH, and the shell backend name string is identical in both copies. boards/arm/beescales_bt/board_power.c is a third, 170-line fork missing the debounce and the shell-log wedge fix, which shows the drift already happening.
>
> Fix: fold into lib/power (which #38 already created for the shared VBUS pieces) as one source compiled for any board with a USBD context, leaving nothing in the per-board dirs. #39 (export the USB init priority) then edits one place instead of two.

---

## EXTEND open issues

### #171 (edge cleanups): add LED_CUE_CLASS_WARNING removal

Comment draft:

> The 2026-08-13 audit adds one more edge cleanup. LED_CUE_CLASS_WARNING (src/led/led_mute.h:26) is behaviorally identical to ALWAYS: the only consumer, led_mute_allows() (led_mute.c:44), tests cue_class != LED_CUE_CLASS_MUTED, so the middle class is a bool in practice and the header's rank-order doc describes a policy that does not exist. Delete WARNING and fold the LED_CUE_LOW_BATTERY row (led.c:178) to ALWAYS. Behavior-preserving: tests at test_led_mute/src/main.c:34,45 already assert WARNING and ALWAYS behave the same.

---

## ROUTE TO T3 DOCS PR

None. The release-notes drift (finding 7, part 2) lives in release_assets, not in docs/architecture.md, docs/runtime.md, README, or headers, so it stays inside issue 7. The wrong comment in log_flush.c dies with the code fix in issue 3.

## NO ISSUE

None. All four nit findings are tracked: two grouped into issue 7, one is issue 8, one extends #171.
