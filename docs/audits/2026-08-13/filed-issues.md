# Filed issues, 2026-08-13 review wave

Every proposal in issues-to-file.md was filed after the dedupe check against
the open-issue snapshot. Numbers assigned:

## nRFTrackerFW

| # | Title | Source |
|---|---|---|
| [#233](https://github.com/nrfmodule/nRFTrackerFW/issues/233) | security: raw modem AT shell (smat/smsh) ships in every image, including the v0.4.0 release | T2 finding 1 (blocker); corroborated by the PR #230 script run |
| [#234](https://github.com/nrfmodule/nRFTrackerFW/issues/234) | power: battery-critical LED layer keeps the 40 ms render tick alive for the rest of battery life | T2 finding 2 |
| [#235](https://github.com/nrfmodule/nRFTrackerFW/issues/235) | log_flush: shutdown flush no longer guarantees an fs_sync | T2 finding 3 |
| [#236](https://github.com/nrfmodule/nRFTrackerFW/issues/236) | button: ignored long-press still counts as user activity and lifts the LED auto-mute | T2 finding 4 |
| [#237](https://github.com/nrfmodule/nRFTrackerFW/issues/237) | scripts: ble_download_logs.py rejects every PigeonTracker (product_id filter hardcoded to 0x04) | T2 finding 5 |
| [#238](https://github.com/nrfmodule/nRFTrackerFW/issues/238) | uploader: kick vs quiesce TOCTOU lets a drain POST race modem teardown during poweroff | T2 finding 6 (two independent reviewers) |
| [#239](https://github.com/nrfmodule/nRFTrackerFW/issues/239) | shutdown: wait_button_release misreports the marginal Q2 case it exists to diagnose | T2 finding 7 (two grouped nits) |
| [#240](https://github.com/nrfmodule/nRFTrackerFW/issues/240) | config: non-ASCII name is dropped but the config version is recorded as applied | T2 finding 8 |
| [#231](https://github.com/nrfmodule/nRFTrackerFW/issues/231) | QA coverage gaps vs behavior spec v1.0: race-chain HIL, queue meta corruption, reboot-ack on hardware, watchdog | T4 materiality verdict |

## nrfmodule-sdk

| # | Title | Source |
|---|---|---|
| [#43](https://github.com/nrfmodule/nrfmodule-sdk/issues/43) | board_power: fold the per-board copies into lib/power (three forks, one already stale) | T2 finding 9 |

## Extensions (comments on existing issues)

- nRFTrackerFW [#210 comment](https://github.com/nrfmodule/nRFTrackerFW/issues/210#issuecomment-5281100238): the T1 detection/recovery map, blast-radius table, and PR #222 gap assessment (copy: t1-modem-wedge-210-comment.md).
- nRFTrackerFW [#171 comment](https://github.com/nrfmodule/nRFTrackerFW/issues/171#issuecomment-5281282466): LED_CUE_CLASS_WARNING removal added to the edge-cleanup list.
