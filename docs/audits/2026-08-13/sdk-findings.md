# nrfmodule-sdk audit findings, 2026-08-13

- Date: 2026-08-13
- Pinned SHA: d6302443fd6ce426f9255685cf116b0bd3663a6b (nrfmodule-sdk main)
- Scope: code merged since the 07-29 audit. PRs reviewed: sdk #38, sdk #42, plus a rubric pass and an over-engineering pass.
- Method: parallel dimension reviewers, then one adversarial verifier per finding.
- Severity counts: 0 blocker, 1 should-fix, 0 nit.

## Board support

### 1. board_power.c is a byte-identical fork across boards, and a third copy is already stale [should-fix]

- File: boards/arm/pigeontracker/board_power.c:2
- Claim: the whole 281-line file is byte-identical to boards/arm/livetracker/board_power.c except the board name in the line-2 comment. PR #38 grew both copies by the same 130 lines (debounce work item, shell-log-backend gate, app-owned enable). Fold the file into lib/power, which #38 already created for the shared VBUS pieces, as one source compiled for any board with a USBD context.
- Evidence: diff at HEAD d630244 shows exactly one differing line. The file has no board-specific content: VBUS is read from the NRF_POWER register, the USBD context is found via STRUCT_SECTION_FOREACH, and the shell backend name string is identical. boards/arm/beescales_bt/board_power.c is a third, 170-line fork missing the debounce and the shell-log wedge fix, which shows the drift already happening. Every future fix must be hand-applied to each copy; sdk#39 would edit the same priority constant in two places.
