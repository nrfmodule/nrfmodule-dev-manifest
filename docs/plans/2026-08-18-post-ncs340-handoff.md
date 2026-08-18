# Handoff: post-NCS-3.4.0-migration state + tracker issue triage (2026-08-17 night)

Companion to `2026-08-17-afk-ncs340-report.md` (full run detail). This doc is
the working state for the next sessions: what is where, the open-issue
triage, and the agreed sequencing.

## Where everything is

- **PRs open, hardware-proven, awaiting Vincent**: core#68, sdk#45,
  tracker#259 (all on `ncs340` branches; tracker#259 needs the outdoor fix
  test before merge).
- **Serial-modem `upstream-340`** branch pushed (nrfmodule/ncs-serial-modem):
  upstream main + #XGNSS idempotent stop + nrfmodule.conf (MEMFAULT=n, TX
  buf 1024, RTT logging) + partition overlays for both 9151 boards +
  sm_log_flush console-less link fix. No PR by design; master stays the
  deployed fleet base.
- **v2.x freeze branches** pushed on core/sdk/manifest (NCS 3.2.x
  maintenance line; land-on-main-first, cherry-pick, tag v2.x.y).
- **Bench state**: 52840 = 3.4.0 gnss-nrf91 bench image incl. the
  #XGNSSPOS parser (shell COM58, `dock override on` after boot); 9151 =
  upstream-340 RTT variant. Restore images: byte-exact 9151 backup at
  `nRFTrackerFW/logs/bench_340/bench9151_backup_pre340.hex`, v2 tracker
  hex at `nRFTrackerFW/build_nrf91/merged.hex` (d: checkout).
- **Workspace**: `c:/ncs/nrfmodule_v3x` (v3.4.0 toolchain). Tracker clone
  for the line: `c:/ncs/nrfmodule_v3x/apps/nRFTrackerFW`.
- Bench checklist for 2026-08-18 is at the end of the run report.

## Two port bugs worth remembering

- MCUboot main stack: 2048 overflows during ECDSA verify on the 3.4.0
  PSA/Mbed TLS 4 backend → silent FIH_PANIC brick. 4096 now committed.
  Any other 3.4.0 product build must carry the same bump.
- Upstream renamed the GNSS fix URC `#XGNSS:` → `#XGNSSPOS:` (payload
  unchanged). Status URCs kept the old prefix, so everything looks healthy
  until you wait for a fix. Core parser now accepts both.

## Tracker open-issue triage (~45 open)

**Decided by the 08-18 bench (base swap is the fix candidate):**
- #256 URC flush truncation and #255 DTR wake failures: upstream-340's RI
  level-latch + chunked flush claim to fix exactly these. The
  sleep/delivery and wake-rate runs are their verdict; pass = close both.
- #254 auto-sleep truncates GNSS windows: NOT fixed upstream, needs the
  bench RTT trace.
- #210/#222 link-dark recovery: consumer is PR #248 (gated, awaiting
  review); #222 waits on Damir's values.

**Release-gating decision: #192 (MCUboot ships the default dev signing
key).** Anyone can flash over BLE. Decide before v3.0.0 tags — v3.0.0
re-provisions the fleet bootloader anyway, so it is the natural moment to
introduce a real key. Belongs on the v3.0.0 checklist, not the backlog.

**Small desk-fixable batch (next AFK fix wave, ~10):** #243 + #237
(ble_download_logs truncation + hardcoded product_id), #239
(wait_button_release misreport), #236 (ignored long-press lifts auto-mute),
#240 (non-ASCII name vs config version), #250 (store modem reset cause),
#234 (battery-critical LED tick), #251 (LED mute), #244 tail (drop dead
sats/hdop fields from the fix log line). Fixes land on post-merge main,
cherry-pick to v2.x per the freeze rule.

**Refactor debt cluster (~10, separate wave):** #160-#175 audit findings —
DataDto implemented three times (#164), segment format ownership (#163),
cursor traversal triplication (#162), wanted-leaf re-derive (#161),
SYS_INIT tier ownership (#173), usb_msc USB ownership (#169), BLE security
prompt lying (#168), consumer enums in tracker_sm.h (#175), agnss MTK
constraint placement (#166), edge cleanups (#171).

**Needs Vincent/boss (~8):** #179 pairing/bonding, #183 lc/lcs decode
(boss), #181 + #205 advertising (blocked on sdk#40 merge + manifest pin
bump), #180 PPK2 release-gate harness, #177 CHG_STAT on pigeon, #182
nRF Cloud A-GNSS codec, #252 SleepFor/WakeUpAt commands (needs a spec
conversation).

**Field-data investigations:** #257 genuine no-fix windows, #201
spontaneous reset, #214 pigeon log analysis, #242 brownout cascade —
need logs or hardware sessions; some overlap with the 08-18 bench.

## Agreed sequencing

1. 08-18 bench (checklist in the run report) — decides #255/#256, feeds
   #254/#257.
2. Vincent merges core#68, sdk#45, tracker#259 (after the outdoor fix
   passes).
3. AFK small-fix wave on the new main (the ~10 desk items above),
   cherry-picks to v2.x where relevant.
4. Refactor wave (#160-#175) separately.
5. #192 signing-key decision at v3.0.0 tag time, alongside v2.4.0 tags on
   the freeze branches and the manifest pin bump
   (`feature/ncs-3.4.0-migration` branch).
