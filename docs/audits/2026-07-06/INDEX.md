# Fable audits — 2026-07-06

Three parallel last-day-of-Fable audit sessions, run from the handoffs in `.claude/handoffs/handoff-2026-07-06-*.md`. Review-only: no code changed, no builds run, git/GitHub read-only during the audits. All deliverables staged here; the two reference docs also land in nrfmodule-core (see below).

## Deliverables

| File | Session | What it is | Final home |
|------|---------|-----------|------------|
| `ncs-seam-inventory.md` | A | 13 NCS-internal seams (S1–S13): upstream touchpoint, breakage mode, verifying build/test | here |
| `NCS_UPGRADE_PLAYBOOK.md` | A | 8-phase checkable NCS-bump procedure; supersedes `NCS_PORTING_GUIDE.md` (guide becomes pointer + version notes — follow-up PR) | `nrfmodule-core/docs/` |
| `ncs-3.4-migration-plan.md` | A | Phased NCS 3.4 / SLM v2.0.0 migration (A stabilize → B RI rehearsal → C host port → D SLM 2.0 → E release), risk register, HIL per phase | here |
| `core-threading-model.md` | B | Contexts C1–C6, locks/sems/atomics, lock-order rules, URC pipeline constraints, block-where matrix, reviewer checklist | `nrfmodule-core/docs/THREADING_MODEL.md` |
| `at-lock-api-recommendation.md` | B | Lock-API design: single internal mutex, `nrf_modem_at_exclusive(fn, ctx, timeout)`, datamode API; SDK txn API rejected; Waggi convergence map | here (drives core/sdk changes) |
| `core-concurrency-fix-plan.md` | B | 8 slices for Opus, blast radius for tracker AND Waggi, test/HIL per slice; S6 gates the v2.3.0 tag | here |
| `trackerfw-architecture-findings.md` | C | 10 architecture findings (A1–A10) + 10 correctness hazards (B1–B10), each marked NEW vs KNOWN (DR-xx from `demo_readiness_plan.md`), status re-verified against main | here |
| `trackerfw-opus-fix-plan.md` | C | 10 execution slices + 1 infra slice, named unit/HIL tests, grep-verified blast radii, unknowns ledger | here |
| `issues-to-file.md` | all | 25 ready-to-file issue drafts: 8 nRFTrackerFW, 9 nrfmodule-core (C1–C9), 8 seam-audit (A1–A8, across manifest/sdk/core) | GitHub issues once approved |

## Cross-cutting conclusions (the synthesis the individual docs can't see)

1. **v2.3.0 tagging is now gated.** Session B: remove SDK `sm_modem_power_mgmt_txn_begin/end` (ABBA trap, draft C5) BEFORE tagging — merged but never tagged, last exit. Session A's migration plan independently puts v2.3.0 tagging first (Phase A.1 / Playbook 0.1). Order: core/sdk fix C5 → tag v2.3.0 → migration phases.
2. **Core CI is vacuous and undermines every other plan's verification story.** `reusable-ci.yml` inits from a stale personal prototype manifest on NCS v3.1.1 and swaps PR code into the wrong path (draft A1). Every "green" core run verified the wrong stack. Fix early — B's and C's fix plans assume CI that means something. (The handoff's suspected Docker Python-deps skew is already fixed; the workflow is the real skew.)
3. **The field-critical bug is B's C1**: blocking AT from the sysworkq self-deadlocks the AT pipeline; `nrfmodule_http.c` timeout path does it in-tree. The tracker's uploader/EPO downloads (the paths session C's plan builds on) hit it exactly when the network is bad. Waggi bench-proved the class 2026-07-03.
4. **A4 (vendored sm_at_client missing upstream fixes) overlaps B's C3/C9** — take the upstream bounds-clamp + RX-recovery fixes in the same slice that hardens the RX path, not separately.
5. **`west.yml` pins ncs-serial-modem to floating `main`** (draft A2), which now targets NCS v3.4.0 — a fresh `west update` today drags 3.4-targeting code into the 3.2.1 workspace. Small fix, do immediately.
6. **The feared sm_at_client breakage from upstream's pipe refactor is overstated** — that refactor is modem-app-side. The real 3.4/SLM-2.0 migration surface is the wire protocol: RI pulse→level, URC-before-response ordering, `#XGNSS`→`#XGNSSPOS`, CTS pull, PM→DTS partitions.
7. **TrackerFW architecture verdict: healthy.** Spine stayed pure across ~30 PRs; residual risk is two product-lifetime gaps (begin/halt persistence DR-10, non-compacting queue) and a too-narrow sampler-cancel seam; legacy `filesystem.c`/`gps.c` hold the last hygiene bugs.

## Suggested execution order for Opus

1. Manifest quick fixes: pin serial-modem (A2), fix reusable-ci.yml (A1).
2. Core: B slice 1 — C1 sysworkq AT deadlock (field-critical).
3. Core+SDK: C5 — remove txn API; then tag v2.3.0 across repos.
4. TrackerFW: C slices 1–2 (persist begin/halt; cancellable sampler), then per its plan.
5. NCS 3.4 migration per `ncs-3.4-migration-plan.md` phases.

## Open questions for Vincent (consolidated)

- `nrf_modem.a` disassembly notes NOT found in the sandbox (thorough search). Remaining hiding place: binary `.docx`/`.pdf` under `Waggi_migration_sandbox\...\Technical Documentation\`. ADR-0002's claim about Nordic-side serialization is marked UNVERIFIED (immaterial to the recommendation).
- SLM v2.0.0: deploy preview2 or wait for final? Minimum mfw version unverified — check on bench before Phase D.
- Version line after the 3.4 jump: v2.4.0 vs v3.0.0 (convention ties v2.x to NCS 3.2.x).
- `drivers/nrf91-sm` (upstream's CMUX/PPP modem driver) — strategic alternative to sm_at_client; deserves a grill session post-migration.
- Is `libmodem_core.a` binary distribution still a live requirement? No regen procedure, no CI exercises binary-mode linking.
- TrackerFW: server acceptance of no-fix records (poison policy), overflow delete-oldest vs reject-newest, `lc` wire width (boss), cadence semantics — full ledger in `trackerfw-opus-fix-plan.md`.
- Whether any consumer silently depends on double URC delivery (C4 halves event rates — soak before/after).
