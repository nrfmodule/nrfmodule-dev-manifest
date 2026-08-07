# Hub: API change request (for review)

Date: 2026-08-07. Author: Vincent. Reviewer: Damir.

Scope: extend the tracker API (reference = deployed version, per swagger at
ta.avirings.com) so the BLE Hub can post harvested BLE data and be
configured. Full design record: `2026-08-07-hub-plan-of-plan.md`.

## Context: what the hub will post

One bulk POST per upload interval. Envelope `id` = the hub's IMEI. The `d`
array mixes device types, distinguished by the existing `dt` field:

| Device | `i` | Fields sent |
|---|---|---|
| tracker | IMEI (read from DIS) | `t`, `a`/`o` only with a live GPS fix, `bp`, `r`, `s`, `x`, `e` |
| iBS05 temp beacon | MAC | `t`, `c` (temp C), `b` (volts, native), `r` |
| BeeScales scale | MAC | `t`, `w`, `bp`, `r` |
| hub itself | IMEI | `t`, `a`/`o` when it has a fix, `bp`, `l` (LTE meta) |

Notes: iBS05 beacons are a device class of their own (loft temperature),
not tied to BeeScales. The hub does not unpack the beacon temps embedded in
the scale advertisement (it sees the beacons directly) and does not forward
the scale's weight deltas (server derives them from the weight series).

## 1. New per-sample fields on /d/b (DataDto)

| Key | Type | Unit | Used by | Why |
|---|---|---|---|---|
| `bp` | int | percent 0-100 | trackers via hub, scales, hub | The advertisement only carries percent. `b` stays volts; converting between them honestly is not possible on the hub. |
| `w` | double | kg | scales | Scale weight. |
| `r` | int | dBm | all hub-forwarded samples | RSSI as seen by the hub; range/placement diagnostics. |
| `s` | int | enum byte | trackers | Tracker state (OFF/WAIT_BEGIN/ACTIVE/SLEEP/DOCKED) from the adv. |
| `x` | long | unix seconds | trackers | Next wake time from the adv. The "kdaj se bo sprozil, je vse OK" check. |
| `e` | int | enum byte | trackers | last_error from the adv (storage/upload/LTE/GPS). |

## 2. Behavior changes

1. Omitted `a`/`o` must be stored as NULL, not 0,0. Beacons and scales have
   no location; trackers held in sleep have no live fix.
2. Add `f` (firmware version) to the /d/b envelope. Today firmware version
   is only reportable on GET /c, so a device that only bulk-posts can never
   report it.
3. The config returned by the /d/b response must be the config of the
   envelope `id` device (the hub), not of `d[0]`'s device.

## 3. Config additions (DeviceDto)

1. Sleep duration in seconds. `sgt` is only the on/off flag; the hub also
   needs how long to command (`sm event sleep <secs>`).
2. Scan-classes selector: which device classes to scan and report
   (trackers / ibs05 / scales).
3. `data_url`: the data-API base URL. The GetConfig URL stays hardcoded as
   bootstrap; everything else follows config (same reason as the
   ThingSpeak swap).
4. Future, pending product decision (dumb hub vs allowlisted hub): a
   device allowlist ("my devices" MAC list) plus a report-unknown flag.
   v1 plans for a dumb hub that sleeps every tracker it sees; see the
   open risk in the design record (mass-sleep at basketing sites).

## 4. dt values to agree

Proposed: `"hub"`, `"tracker"`, `"ibs05"`, `"scale"`.

## 5. Side note (unrelated to the hub)

`appsettings.json` in the API repo contains a live SQL connection string
with a plaintext password. Rotate the password and move the secret out of
the repo.
