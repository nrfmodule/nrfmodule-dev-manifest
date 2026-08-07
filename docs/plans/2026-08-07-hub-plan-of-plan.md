# BLE Hub: plan of a plan (2026-08-07)

Status: grill COMPLETE 2026-08-07. Decisions D1-D7 resolved; remaining
opens are Damir rulings only (see Open questions). Cross-repo design
record for the BLE Hub (nrfmodule/nRFTrackerFW#125). When nRFHubFW is
created, seed its docs/adr/ from D1, D2, D5, D7.

## Inputs

- Issue nRFTrackerFW#125 (hub idea, Damir): scan trackers, sleep them,
  harvest adv data, bulk-post to the same API, config-driven.
- Existing first-cut plan: nRFTrackerFW `docs/plans/2026-07-31-hub-central-plan.md`
  (new repo `nRFHubFW`, `scan_harvester` + `sleeper` modules).
- Boss chat 2026-08-07: one firmware knows all device types; config selects
  which classes to scan (gps tracker / BLE temp sensor / BLE scale); two
  build flavors differ only in branding + hardcoded bootstrap config URL;
  data-API URL moves into config; hub modes: default (ping+config only),
  scanner, scanner+sleep-management; reference API = tracker (AviRings) API,
  boss unifies all APIs on whatever we define now. Vincent has free hands on
  API fields.

## Fact base (verified in code 2026-08-07)

Tracker (nRFTrackerFW):
- Adv proto v2, 21 B mfg data, company 0x0E34: product_id (0x04/0x05),
  battery %, state, flags + wake_kind, sats, lat/lon e7, next_wake_unix,
  last_error. No device ID on the wire. 8 spare bytes. Legacy adv,
  connectable, 1.0-1.2 s interval, advertises in every powered state (the
  SM ble_adv effect is a logging stub). Name is scan-response only.
- `sm event sleep <secs>` exists; repeat while in SLEEP re-arms in place
  (written as "Hub keepalive"); expiry goes to ACTIVE unless a future begin
  is pending; DOCKED refuses sleep. `wake_kind=HUB` reserved, never emitted.
- NUS shell is open: no pairing, CONFIG_TRACKER_BLE_SECURITY default n.
- GPS_FIX flag = live fix in the current producer session; advertised
  lat/lon = last fix since boot (kept while stale); fix age exists on-device
  (gnss_producer_get_last_fix uptime out-param) but is not on the wire.
- DIS enabled (CONFIG_BT_DIS + SERIAL_NUMBER + DIS_SETTINGS) but nothing
  writes the IMEI into the serial-number characteristic today. Modem init
  runs before BLE init; IMEI is read at CFUN=0, no network needed.
- Tracker allows 1 connection and stops advertising while connected.

API (AviRings, reference):
- Bulk POST /d/b: per-sample `i` (string id), `t`, `a`/`o` lat/lon
  (NON-nullable), `h`, `b` battery, `c` temp, `p` pressure, `l` LTE meta.
  Envelope `id`/`t` exist but are ignored by the server. Bulk response
  returns config, but only for Data[0]'s device.
- Config response = {u, n, g GpsIntervalSec, t TelemetryIntervalSec} only.
- Firmware version reportable only via GET /c/{id}?f=, not on bulk.
- No auth on any endpoint. (Side finding: live SQL password committed in
  appsettings.json; tell Damir.)
- DEPLOYED API is newer than the repo snapshot (swagger at ta.avirings.com,
  checked 2026-08-07): envelope = {id, cv, t, lc, lcs, d}; DataDto gained
  `dt` (device type string) and a/o are nullable; config DeviceDto =
  {u, n, g, t, v, bt, cmd{id,tp,pl}, sgt}. `sgt` = "suspend GPS trackers
  nearby" (hub sleep-management enable) already exists.

BeeScales:
- Scale adv: payload in the SCAN RESPONSE (hub must active-scan), company
  0x0E34 with a layout incompatible with tracker proto v2 (byte 2 = 0x00
  reserved vs protocol version), fields: battery %, weight/10, deltas,
  2 beacon temps, unix timestamp.
- iBS05 beacons: Ingics 0x082C, temp 0.01 C, battery 0.01 V (volts, not %),
  button flag. Identity = MAC only.
- Existing central/beacon code is not portable as-is (one 639-line module
  mixing parse/session/registry/persistence, absolute-offset parsing without
  length checks, registry use-after-free window, max 2 beacons). Carry over
  the format knowledge only.

## Decisions

### D1: Device identity (RESOLVED 2026-08-07)

- The hub keys everything it harvests by BLE MAC.
- Tracker server identity stays IMEI. The hub resolves MAC->IMEI itself by
  reading the DIS Serial Number over the connection it already opens for the
  sleep command, and caches the mapping in flash. In scanner-only mode it
  connects once per unknown tracker just for this read.
- Rationale for hub-side (not server-side) resolution: a tracker held in
  SLEEP by the hub may never reach the server on its own, so a server-built
  MAC->IMEI table can have holes. Reading DIS makes the hub self-sufficient.
- Bulk posts: tracker samples use i=IMEI (same identity as the tracker's own
  uploads, so no split identity); scales and temp beacons use i=MAC; the
  hub's own IMEI goes in the envelope `id` (server change needed: stop
  ignoring the envelope).
- Tracker-side change required (small): write the IMEI into the DIS serial
  number at boot, after modem init (BT_DIS_SETTINGS is already enabled; no
  boot race because modem init precedes BLE init). This makes the 07-31 plan
  doc's "no tracker-side work for v1" stale by exactly this one item.
- Fallback: DIS serial empty or "unknown" (modem fault) -> post i=MAC,
  server reconciles later.
- Tracker issue filed: nRFTrackerFW#197.

### D2: Stale location (RESOLVED 2026-08-07)

- The hub forwards lat/lon only when the adv GPS_FIX flag is 1 (live fix,
  at most ~5-10 s old given the 5 s adv sample tick), posted with harvest
  time. Otherwise lat/lon are omitted from the sample.
- No fix-age byte in the adv for v1; no measured-at API field. Nobody
  consumes hours-old positions in either product.
- Matches Damir's expectation that a hub-slept tracker simply has no
  location.
- Requires the Q3 API change: omitted lat/lon must be stored as null,
  not 0,0 (today a/o are non-nullable; the tracker never posts no-fix
  samples, the hub will).

### D3: Bulk/config field set (RESOLVED 2026-08-07)

Reconciled against the deployed API. Also resolved here: iBS05 temp beacons
are a standalone device class for BOTH brands (loft temperature
monitoring), not a BeeScales accessory.

Adopted from the deployed API as-is:
- Envelope {id = hub IMEI, cv, t, lc, lcs}; command channel via config
  `cmd` reused by the hub unchanged.
- Per-sample `dt` device type string. Values to agree with Damir:
  "hub", "tracker", "ibs05", "scale" (exact strings TBD).
- Nullable a/o; config {v, bt, cmd, sgt}.

Hub sample mapping:
- tracker: i=IMEI, dt, t=harvest time, a/o only when GPS_FIX=1 (D2),
  bp, r, s, x, e
- ibs05: i=MAC, dt, c (temp C), b (volts, native), r
- scale: i=MAC, dt, w, bp, r; scale-embedded beacon temps NOT unpacked
  (hub posts beacons under their own MACs); weight deltas NOT forwarded
  (server derives)
- hub itself: i=IMEI, dt, a/o from own GPS when available, bp or b, l

Ask-Damir list (API changes to request):
1. New per-sample fields: `bp` battery percent (0-100), `w` weight kg,
   `r` RSSI dBm (as seen by hub), `s` tracker state byte, `x` next-wake
   unix, `e` last-error byte. Rationale: bp because the adv only carries
   percent while `b` is volts; s/x/e are the "is everything OK" monitoring
   Damir asked for.
2. Confirm omitted a/o are stored as NULL, not 0,0.
3. Add `f` (firmware version) to the /d/b envelope; today FW version is
   reportable only on GET /c, so a bulk-only device can never report it.
4. Bulk response config must key on the envelope `id` (the hub), not on
   d[0]'s device.
5. Config additions: sleep duration seconds (sgt is only the enable flag),
   scan-classes selector (trackers / ibs05 / scales), `data_url` (data API
   URL, GetConfig URL stays the hardcoded bootstrap), sleep allowlist
   (pending Q4).
6. Agree the `dt` string values.
7. Side finding: appsettings.json in the API repo has a live SQL password
   committed.

### D4: Sleep ownership (INTERIM 2026-08-07, Damir ruling pending)

- v1 plans for a "dumb" hub: it sleeps every tracker it can see and
  reports everything it can parse. No allowlist.
- Vincent pinged Damir with the ownership question (basketing-site
  mass-sleep risk, neighbor devices at the loft, posting strangers'
  positions). If the ruling changes, the allowlist arrives via config
  (see D3 ask list) with default-deny commanding.
- Architecture consequence NOW: the sleeper module gets a single policy
  seam, e.g. `bool sleep_policy_allows(mac, adv)`. v1 implementation
  returns true for any tracker. The allowlist becomes a policy swap, not
  a redesign. Same seam pattern for reporting.
- The related security question (open NUS shell means anyone, not just
  our hub, can command sleep) rides in the same Damir batch. Standalone
  reviewable doc: `2026-08-07-hub-api-change-request.md`.
- Consequence for double reporting (old Q6): the dumb hub forwards
  everything it parses. In scanner-only mode an ACTIVE tracker uploads
  itself while the hub also posts its adv data; accepted for v1. The
  server can tell the streams apart (hub samples carry `r` and arrive in
  the hub's envelope) and the `s` state field lets it filter. Revisit
  only if server data gets noisy.

### D5: Repo home + shared-code strategy (RESOLVED 2026-08-07)

- Hub = new repo nRFHubFW, generated from nrfmodule-product-template. Not
  inside nrfmodule-sdk (SDK = public customer distribution). One codebase,
  two build flavors (branding + hardcoded bootstrap config URL via
  Kconfig); CI builds both.
- Phase-0 SDK promotions (each moves with its unit tests):
  1. Adv codec: one SDK module owning the company 0x0E34 wire formats
     (tracker proto v2 encode+decode, BeeScales layout, iBS05 parser).
     Tracker's golden vectors become the module's tests; tracker switches
     to encoding through it, hub decodes through it, BeeScales migrates
     when ported. Kills cross-repo wire drift (hole 10).
  2. Cloud client: lte_transport (protocol), batch_envelope, config
     decode, avirings_http/rsp_accum. Damir is unifying all product APIs
     on this protocol, so this layer is platform by definition.
  3. modem_lte + modem_iccid (radio mechanism: boot recipe, registration
     authority, PSM/eDRX). Hub reuses verbatim and never calls the deep
     power-down paths (modem_lte_power stays tracker-side). Timing
     caveat: may be promoted last (hub copies in the interim) if the
     tracker's testing phase is still producing modem fixes.
- Stays product-local (hub copies thin versions; divergence expected and
  wanted): collector (sample building), uploader_service + sync_policy
  (upload policy; pure-with-ports so copying is cheap), clock (sync half
  generic, begin-timer half tracker-specific; promotion candidate later),
  data_queue (promote once its API survives multi-device samples),
  battery/LED/button, state machines.
- AT bridge + nrfmodule_http already live in core/sdk: nothing to do.
- Template build-out (Phase 0's other half), copied from nRFTrackerFW:
  HIL scripts (hil_shell/hil_flash/hil_cycle, run_test.py), tests/hil
  pytest harness skeleton, quality-gate wiring, CI (ci.yml -> manifest
  reusable-build with changes-gate + restore-only cache,
  west-cache-warm.yml, release.yml with tag==VERSION + DIS versioning),
  VERSION-file plumbing, docs skeleton (CONTEXT.md, docs/adr/).
  Generating nRFHubFW from the improved template is the template's first
  real test.

### D6: Hub's own location (RESOLVED 2026-08-07)

- The hub gets its own GPS fix and posts a/o when it has one (GNSS driver
  is already in core). No fix (indoor install) -> a/o omitted, which the
  API now tolerates (nullable). Optional later: config-provided fixed
  location for permanently indoor hubs.

### D7: Keepalive policy + benchmark plan (RESOLVED 2026-08-07)

Terms: X = commanded sleep seconds (config), S = sweep period (config `g`
reused as scan-sweep interval), remaining = adv next_wake_unix - now.

- Threshold refresh: connect only to trackers with remaining < 2*S; the
  adv provides remaining for free. Not ownership policy, just efficiency.
- Safety invariant: X >= 3*S. A tracker survives two fully missed sweeps
  (phone connected, radio noise, hub mid-upload) before going ACTIVE.
- Verification without reconnect: `sm event sleep` self-acks
  (state=SLEEP echo); next adv must show next_wake ~= now+X. No movement
  -> failed, retry.
- Retries: two per sweep, then wait for the next sweep (2*S threshold
  guarantees at least one more sweep of margin). No hub-side alarms:
  the posted `x` field makes near-expiry visible server-side (Damir's
  "je vse OK" monitoring).
- Serial connections first; concurrency only if benchmarks demand it.
- Benchmarks (HIL, first thing after the hub skeleton boots):
  1. Per-refresh time scan-hit -> connect -> ack -> disconnect,
     distribution over ~100 cycles, both tracker board types
     (estimate to replace: 3-4 s).
  2. Discovery completeness: time to see 95% of N advertisers at
     1.0-1.2 s adv interval, passive vs active scan (active mandatory
     once scales are in: their payload is in the scan response).
  3. Sweep throughput: refreshes/minute, serial vs 2-4 concurrent links.
  4. Output: measured minimum S + recommended X as a documented sizing
     formula; numbers feed Damir's config defaults.

## Open questions (ordered; next up first)

- Q5 sleep-command security: is the open NUS shell acceptable for v1 races
  (basketing-site mass-sleep risk)? Needs a conscious ruling with Damir
  (batched with the D4 ownership question).
- Q7 scope: is DFU-from-hub in v1? (The Android upgrade-app comparison
  implies it; it is a project-sized feature: SMP client + image staging.)

## Phase plan

Methodology per slice: standard flow (grill -> plan -> TDD -> review ->
qa -> HIL). Damir track runs in parallel and gates nothing in Phase 0.

Phase 0 - Platform + tooling (no hub repo yet; boss's "tooling first"):
- 0a. Adv codec SDK module (golden vectors as tests); tracker PR switches
  encoding to it.
- 0b. Cloud client promotion to SDK (lte_transport, batch_envelope,
  config decode, avirings_http, rsp_accum); tracker PR switches.
- 0c. modem_lte (+modem_iccid) promotion; may slip to last if the
  tracker testing phase is still producing modem fixes (hub copies in
  the interim).
- 0d. Product-template build-out (D5 list: HIL scripts, pytest harness,
  quality gate, CI/release/versioning, docs skeleton).
- 0e. Tracker #197: DIS Serial Number = IMEI.

Phase 1 - Product design (docs-first, Damir's design-before-code
directive; runs in nRFHubFW, which is created empty with README +
docs/ + CONTEXT.md, no template needed yet):
- Behavior spec (boss-reviewable, same style as the tracker's spec
  v1.0): modes, config fields consumed, per-mode behavior, error
  handling, what the hub never does.
- State machine spec + diagram (graphviz, tracker convention): top-level
  modes (default / scanner / scanner+sleep from config) + the sweep
  engine (scan window -> harvest -> refresh queue -> upload) as a
  module-level flow.
- architecture.md draft: module map (scan harvester, device catalog on
  the SDK codec, sleeper + policy seam, identity cache, sample builder,
  uploader, config sync), ownership and threading model.
- docs/adr/ seeded from D1, D2, D5, D7; CONTEXT.md glossary started.
- GATE: Damir reviews behavior spec + state machine before any Phase 2
  code. Drafts can be authored AFK; the review is human by design.

Phase 2 - Hub skeleton:
- Apply the template to nRFHubFW as a PR (this validates the template).
- Boots on livetracker HW: LTE via promoted stack, config fetch + ping,
  DIS/versioning, NUS debug shell.
- Mode skeleton per the approved state machine. No racing states.

Phase 3 - Scanner:
- Active-scan central; device catalog (tracker v2 + iBS05 + scale via
  SDK codec); harvest table; bulk post via cloud client; hub GPS (D6).
- Tests: parser unit tests (golden vectors), harvest/dedup logic; HIL
  with bench boards + a real iBS05.

Phase 4 - Sleeper:
- Connect + DIS identity read + MAC->IMEI flash cache (D1); sleep
  command + threshold policy + verification (D7); policy seam (D4).
- D7 benchmark suite; sizing formula doc; config defaults to Damir.

Phase 5 - Productization:
- Two build flavors (branding + bootstrap URL), release workflow, field
  trial at a loft. Hub self-update path = same BLE-OTA as tracker for v1.

Damir track (parallel): API change request review (see
2026-08-07-hub-api-change-request.md), allowlist/open-shell ruling (D4/Q5),
DFU-from-hub scope (Q7), dt string values.

## Logic-holes register (2026-08-07 grill, one line each)

1. No device ID in tracker adv -> D1.
2. API a/o non-nullable: already fixed in the deployed API (nullable);
   remaining asks tracked in D3.
3. Stale adv location has no age on the wire -> D2 (GPS_FIX-gated).
4. No ownership model for sleep commands -> D4 interim (dumb hub v1,
   policy seam reserved, Damir ruling pending).
5. Sleep command unauthenticated (open shell) -> Q5 (Damir batch).
6. Double reporting tracker-self vs hub -> D4 consequence (dumb hub
   forwards everything, accepted for v1).
7. "Same functionality as Android upgrade app" smuggles in DFU -> Q7.
8. Product app inside nrfmodule-sdk inverts layering -> Q8 (new repo).
9. Per-device-type conditional compilation contradicts boss's config-driven
   single-FW decision: drop it; flavors differ only in branding + URL.
10. Two products share company 0x0E34 with incompatible layouts; hub
    disambiguates by luck -> unify adv envelope, shared codec in SDK (Q8).
11. Hard part is missed-keepalive policy, not throughput -> D7.
