# AFK run 2026-08-13 — post-v0.4.0 review wave (desk only)

Second AFK track. Desk work only: the bench belongs to the wedge hunt
(`2026-08-13-afk-wedge-hunt.md`). Five independent tasks; run them in
parallel where the tooling allows. No firmware changes. The only PRs this
run may open: one docs-only tracker PR (T3) and one scripts-only tracker PR
(T5). Never self-merge.

## Why now

v0.4.0 shipped 2026-08-13 after 14 same-day merges. Fast-landed code is
where rot starts. The last full audit was 2026-07-29; its findings were
filed as tracker #147-#183 and many are still open. This run checks the new
code, the docs, and the test coverage against the spec, and answers one
product question: what does the firmware do today when the nRF9151 goes
dark.

## Ground rules

- Desk only. Do not touch the bench, J-Link, or any COM port. The wedge-hunt
  run owns the hardware.
- Review `main` of each repo at a fixed SHA; record the SHAs in the report.
  Do not review open PRs (sdk#40 and manifest#20 wait for human review).
- Before filing any issue, search open issues for a duplicate. The 07-29
  wave already filed most edge debt (#147-#183). Extend an existing issue
  with a comment instead of filing a twin.
- Findings are counts plus file:line references. No adjectives.
- If a PR's hosted CI fails within seconds with a billing error, note it in
  the PR body and leave the PR open. Do not retry.
- Vincent is AFK: make the conservative call and write it down.

## Tasks

### T1 — modem-wedge handling posture (highest priority)

Question: if the nRF9151 wedges in the field, does the firmware handle it in
any way? On PigeonTracker the nRF9151 is also the GNSS source, so a dark
modem means no positions at all, not just no uploads.

Method: code reading only. Sources: nrfmodule-core (`sm_at_client`,
`sm_modem_power_mgmt`) and nRFTrackerFW (network, uploader, link_policy,
gnss_producer, tracker_sm). Trace and cite file:line for each:

1. **Detection.** The `AT interface dark after 5 consecutive timeouts`
   event seen in the core#64 capture: who emits it, who consumes it.
   Tracker #210 claims no consumer; confirm or refute.
2. **Recovery paths that exist today.** Uploader/link_policy retry behavior
   against a dark modem; any code that drives a modem reset (PigeonTracker
   has n91_RST on P1.02 — does anything use it?); any watchdog that covers
   AT liveness; whether a wedged modem can ever come back without a user
   reboot.
3. **Blast radius per product.** Table: LiveTracker (external L76 GPS,
   positions survive) vs PigeonTracker (GNSS is the modem, total loss).
   Include what the data_queue does while uploads fail indefinitely.
4. **Proposed recovery ladder.** Sketch only, no code: escalation steps
   (re-wake, UART re-init, XRESET/pin reset, last-resort reboot) with where
   each would hook in. This is input for the fix discussion, not a design
   record.

Deliverable: ONE comment on tracker #210 containing the map, the gap list,
the blast-radius table, and the proposed ladder. Cross-reference
nrfmodule-core#64 so the bench evidence and this map meet in one place.
Keep a copy in the audit directory.

### T2 — post-v0.4.0 code audit (the ultracode fan-out)

Scope: nRFTrackerFW `main` and nrfmodule-sdk `main`. Focus first on code
merged since the 07-29 audit: LED subsystem and auto-mute refresh, button
poweroff gate (#209), DIS/IMEI (#203), MSC-default build flip (#202), the
08-13 v0.4.0 merge wave, and sdk changes on main since the same date.

Method: parallel subsystem reviewers plus one pass with the review rubric
(the 10 recurring priorities). Every candidate finding gets an adversarial
verification pass against the actual code before it is filed; only confirmed
findings survive. Add one over-engineering pass: speculative abstractions,
dead flexibility, scaffolding left by the merge rush.

Deliverable: `docs/audits/2026-08-13/trackerfw-findings.md`,
`sdk-findings.md`, and `issues-to-file.md` in this repo. File confirmed
findings as issues only after the dedupe check; record filed numbers in
`filed-issues.md`. An `INDEX.md` ties the directory together.

### T3 — docs truth sweep (closes tracker #172)

Tracker #172 is the contract and already lists confirmed drift (runtime.md
poweroff order inverted, plus its drift list). Sweep `docs/architecture.md`
and `docs/runtime.md` (the canonical pair) and README claims against
`main`. Fix the docs, not the code: where the code is wrong and the doc is
right, extend or file an issue instead of editing source.

Deliverable: one docs-only PR on nRFTrackerFW that closes #172. Docs-only
paths trigger no CI, so the billing wall does not apply. List any claims
that could not be verified from source in the PR body.

### T4 — spec-vs-tests QA audit

QA discipline: derive expected behavior from the behavior spec v1.0 (boss's
spec, in tracker docs) WITHOUT reading the implementation. Then audit the
existing test inventory (unit suites and HIL scripts) against it and derive
missing negative and boundary cases.

Deliverable: `docs/audits/2026-08-13/qa-coverage.md` with a
spec-section -> covering-test -> verdict table. If gaps are material, ONE
tracker issue carrying the table.

### T5 — flavor-check script plus release-skill line

Context: the v0.4.0 release added a manual step, checking each image's
`.config` flavor (right features in the right image). This automates it.

Build `scripts/check_flavors.py` in nRFTrackerFW. Input: a build directory
or a directory of release images with their `.config` files. The
expected-flags matrix lives at the top of the script (or a small file next
to it) as the editable policy table. Output: pass/fail per image, nonzero
exit on any mismatch, one runnable self-check included. Derive the matrix
from the v0.4.0 release notes and the config fragments (hil, bench, MSC
flavors); mark any flag you cannot confirm as TODO in the table instead of
guessing.

The release-skill step: propose the exact line as text in the PR body. Do
not edit the release skill itself; process files are Vincent's call.

Deliverable: one scripts-only PR on nRFTrackerFW.

## End state

One summary message at the end of the session listing every deliverable:
the #210 comment link, both PR links, issues filed or extended (numbers),
and the report paths under `docs/audits/2026-08-13/`. Leave the audit
directory uncommitted in this repo; committing it is Vincent's call. Nothing
merged, nothing flashed, bench untouched.
