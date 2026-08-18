# CI cost diet: fit the pipeline into the free tier (plan for a fresh session)

Written 2026-08-05, after the org hit the GitHub Actions wall mid-day.

## Situation

- The nrfmodule org is on the free plan: 2,000 included Actions minutes per
  month for private repos. **No money will be added** (decision 2026-08-05).
  The spending limit stays at $0, so when the minutes run out, hosted CI stops
  starting jobs ("recent account payments have failed or your spending limit
  needs to be increased" on every job, 3-second failures with zero steps).
- The wall is active NOW. Hosted CI is dead until the org's billing cycle
  resets. Step 0 below finds the reset date.
- One nRFTrackerFW PR push currently costs ~47 minutes: tests job ~25 min +
  two board builds ~11 min each + lint ~10 s. Every push re-runs everything;
  a docs-only PR costs the same as a code PR. A single active day (2026-08-05:
  five PRs merged, several review-fix pushes) burned ~470 minutes.
- Left hanging by the wall: **nRFTrackerFW PR #190** (EPO staging, fix for
  #156) is open, fully verified locally (4 unit suites, pristine livetracker
  build, quality gate, 2 review passes), but has no green CI. Merging on local
  evidence is the user's call; otherwise it waits for a working runner.

## Goal

Cut the per-push cost so a normal month fits in 2,000 minutes, and make
docs-only changes free. Self-hosted runner is the endgame (unlimited, $0);
the workflow diet still matters so the hosted fallback stays viable.

## Where things live

- Trigger + test job: `nRFTrackerFW/.github/workflows/ci.yml`
- Board builds: `nrfmodule-dev-manifest/.github/workflows/reusable-build.yml`
  (called by tracker ci.yml and release.yml; also by other product apps)
- Container: `ghcr.io/nrfmodule/nrfmodule-dev-manifest:latest` (pull is free
  bandwidth, ~1-2 min runtime per job; NOT the cost driver)
- The repeated expense inside every job is `west update` cloning the NCS/
  Zephyr tree from scratch (~6-8 min x 3 jobs per push).

## Step 0 — find the billing reset date

Ask the org admin (boss) for Settings > Billing, or with an admin token:
`gh api /orgs/nrfmodule/settings/billing/actions` (needs admin:org scope;
the current user token may not have it). Record: included minutes used,
cycle reset date. Everything hosted resumes on that date.

## Step 1 — docs and non-code changes run nothing (tracker ci.yml)

Add to the `pull_request` trigger:

```yaml
    paths-ignore:
      - 'docs/**'
      - '**.md'
```

- There is NO branch protection in the org (GitHub free), so no check is
  "required" — skipped checks cannot block a merge. Zero risk.
- Do not paths-ignore `scripts/**` or `tests/hil/**` blindly: the tests job
  doesn't run them, but keep the ignore list conservative and explicit.

## Step 2 — gate the tests job on code paths (tracker ci.yml)

The 25-minute twister job should run only when something it tests can have
changed: `src/**`, `tests/unit/**`, `CMakeLists.txt`, `Kconfig*`,
`configs/**`, `boards/**`, `west.yml`, the workflow itself. Options:
job-level `dorny/paths-filter` step, or split the workflow. Keep `lint`
always-on (it costs 10 seconds and catches style in any file type).
Board builds: keep both boards for code changes (the matrix caught real
board-specific breakage in #188/#151); they're already covered by Step 1
for docs.

## Step 3 — cache the west workspace (biggest per-run saving)

`actions/cache` around the NCS tree so `west update` restores instead of
re-cloning. Applies in two places: the tests job (tracker ci.yml) and
`reusable-build.yml` (manifest; benefits every product app).

- Cache paths: the west topdir modules (zephyr/, nrf/, modules/, bootloader/,
  tools/ — NOT the application checkout, NOT build output).
- Key: hash of the resolved manifest (e.g. `west list -f '{name} {sha}'`
  output, or west.yml + NCS rev). Note: nrfmodule-core and nrfmodule-sdk
  track `main` (moving targets) — EXCLUDE them from the cache and always
  fetch them fresh, or key the cache only on the pinned NCS portion. They are
  small; the multi-GB part is zephyr + sdk-nrf, which is pinned (v3.2.1).
- Restore-keys fallback to the newest cache so a manifest bump still restores
  most objects.
- Budget: ~2-4 GB per cache entry, 10 GB free per repo. The cache lives in
  the CALLER repo for reusable workflows — so tracker PR builds cache in
  nRFTrackerFW; watch eviction if both jobs write large entries.
- Expected effect: west update 6-8 min -> 1-2 min per job. Per-push total
  ~47 min -> ~25-30 min.

## Step 4 — self-hosted runner (the real fix, $0 forever)

Self-hosted runners consume NO billed minutes, private repos included.

- Hardware: any always-on Linux box or WSL2 with Docker on a Windows machine
  (the bench PC is a candidate; note HIL flashing also lives there — don't
  let a CI build saturate it mid-HIL-run).
- Register at ORG level (Settings > Actions > Runners) so all repos share it.
  Install as a service (`./config.sh`, `./svc.sh install`), label e.g.
  `self-hosted, linux, x64, nrfmodule`.
- The workflows use `container:` — the runner host needs Docker; jobs then run
  in the same ghcr image as today, so no toolchain drift.
- Switch `runs-on` via a repo/org variable (e.g. `vars.CI_RUNNER` defaulting
  to `ubuntu-latest`) so flipping between hosted and self-hosted is a variable
  change, not a workflow edit. reusable-build.yml needs the same treatment
  (input with a default).
- Security: fine for this org because all repos are private and PRs come from
  branch pushes, not forks. Do NOT enable the runner for public repos.
- Bonus once it exists: a persistent west workspace + ccache on the runner
  makes builds far faster than hosted ever was; Step 3's cache becomes
  irrelevant on the runner but keep it for the hosted fallback.

## Step 5 — verify + close out

1. When a runner (or the billing reset) is available: re-run PR #190's checks
   (`gh run rerun <id>` or push a no-op), confirm green, merge #190.
2. Measure: one code push and one docs push; record job minutes before/after
   (Actions tab shows per-run billable time). Target: docs = 0, code <= ~30
   hosted / ~10 self-hosted.
3. Update manifest CLAUDE.md's CI section with the new trigger rules and the
   runner variable so future sessions know builds may run self-hosted.

## Status 2026-08-05 (executed same day)

- Steps 1+2+3 MERGED: tracker PR #191 (ci.yml gating + restore-only cache +
  new west-cache-warm.yml single-writer workflow) and manifest PR #19
  (reusable-build restore-only cache, zstd in Dockerfile, runs-on via
  vars.NRFMODULE_CI_RUNNER, single label only). Two review rounds; the
  original in-job actions/cache design was scrapped (no main-branch entry
  to restore, gzip fallback, 3-way save race) for the warm-writer design.
- The manifest repo is PUBLIC, so its Actions are free and unaffected by
  the wall: publish-docker already rebuilt :latest WITH zstd (11:41 UTC).
- Step 0 still open: token lacks admin:org; reset date needs the boss.
- Step 4 still open: needs a machine nominated, then set org variable
  NRFMODULE_CI_RUNNER to the runner's label.
- After the reset (or a runner): dispatch West Cache Warm once in
  nRFTrackerFW (first cache entry), re-run PR #190 checks, then do the
  step 5 before/after measurement.

## Order of work in the new session

1. Step 0 (reset date, so you know the hosted timeline).
2. Steps 1+2 as one nRFTrackerFW PR; Step 3 as one manifest PR (+ the tiny
   tracker hunk using it). CI cannot validate them until a runner exists or
   the cycle resets — author them, review them locally (actionlint is in the
   quality tooling), and merge on review since the failure mode of a bad
   workflow edit is visible and cheap.
3. Step 4 if/when a machine is nominated — needs the user to pick the box.
4. Step 5.
