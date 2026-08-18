# Plan 2026-08-17: merge session, then the serial-modem base decision

Two phases. Phase 1 lands the proven work and produces the stable baseline.
Phase 2 decides, on bench evidence, whose UART code the 9151 runs going
forward. No time pressure; correctness over speed.

## Phase 1: PR merge session (Vincent merges, agent rebuilds/smokes after)

Composition is already proven: a local integration branch of all five
tracker PRs merges clean in any order, builds both boards, passes the
touched suites, and survived 22 h 45 m in the field.

Merge order (smallest first, no hard dependencies):

| # | PR | Note / decision needed |
|---|---|---|
| 1 | tracker#245 positive AT error | none |
| 2 | tracker#249 log flush fs_sync | none |
| 3 | tracker#246 kick/quiesce TOCTOU | none |
| 4 | tracker#247 AT shell out of releases | DECISION (Vincent): confirm release images drop smat/smsh; pigeontracker keeps NO smat bench flavor for now; TRACKER_PWR_SHELL stays for a separate ruling |
| 5 | tracker#248 slim recovery | merges with conservative defaults; Damir's values adjustable later via Kconfig; #253 (live CEREG verify) is the required follow-up, separate PR |
| 6 | core#66 + sdk#44 | merge as a pair (sdk is the doc companion) |
| 7 | serial-modem#5 GNSS idempotent stop | field-proven 11/11; upstream still ships the bug |
| — | serial-modem#3 watchdog | DO NOT MERGE. Stays held until Phase 2 settles the base and the fire test runs |

After the merges (agent):
- Close PR #222 as superseded (#248 landed).
- Rebuild + flash bench livetracker from main+main; smoke (register, POST 200).
- Rebuild pigeontracker images from main (replaces the integration-branch builds).
- Bump ncs-serial-modem-livetracker west.yml pin to fork master (picks up #5;
  the RI/flush regressions do not affect livetracker, which uses the L76, but
  note them in the bump PR anyway).
- Update tracker#210 / core#65 with what landed. Refresh the run report.

Baseline after Phase 1: tracker main + core main on both boards, fork master
(core64 + GNSS stop) on the 9151, watchdog parked.

## Phase 2: serial-modem base decision (needs 9151 debug access)

Question: keep maintaining our UART rework (and fix its regressions), or
rebase the fork onto Nordic's current upstream master (which reworked the
same area after our December snapshot).

Prep:
- J-Link on a 9151 (bench livetracker or the pigeontracker) for RTT.
- Check upstream master builds against plain NCS v3.2.1 at all (it may
  target a newer NCS; if so, that cost enters the decision).

Reproducer battery (all already scripted/known from this wave):
1. E4c wedge test: smat AT#XRECV 60 s block. Old deployed FW wedges; our
   rework passes. Does upstream master pass?
2. Sleep/delivery test (stationary, window sill): mid-window auto-sleep,
   then count spontaneous RI assertions and malformed #XGNSS lines.
   Old FW: RI fires, flush intact (race A/B). Our rework: RI dead, flush
   truncated. What does upstream do?
3. Wake-failure rate over ~50 sleep/wake cycles (old FW 0/63, ours 16/736).

Decision matrix:
- Upstream passes 1+2 -> rebase the fork onto upstream master. Drop our
  UART rework. Fork carries only: GNSS stop fix (offer upstream), board
  overlays, build recipes. Then full re-validation (bench soak + 2 h
  continuous drive).
- Upstream fails 1 (still wedges) -> keep our rework; fix fork#6 (assert RI
  on URC queued against suspended UART) + fork#7 (resume flush must not be
  aborted by the 1 s TX bound; wake handshake first). Acceptance = race A/B
  criteria: spontaneous RI > 0, malformed = 0, wake failures ~0, E4c still
  clean.
- Either way afterwards: rework the watchdog (#3) on the winning base with
  the XSLEEP interplay root-caused via RTT, mandatory bench fire test
  (AT#XWDTTEST), then the ncs-serial-modem-livetracker pin follows.

Re-validation gate for "race ready": a 2 h continuous drive with fix rate
compared against the race baseline (100% in flight); the same run feeds
tracker#257 (genuine-acquisition investigation) with delivery-clean data.

## Parked / follow-ups (not in either phase)
- tracker#253 live-CEREG verify in the dereg watchdog (first PR after Phase 1).
- tracker#254 pause-auto-sleep: mitigation only, do not implement unless a
  race lands before Phase 2 concludes.
- tracker#257 in-vehicle acquisition study (needs the re-validation drive).
- tracker#250 reset-cause in littlefs + fork#4 reset-reason URC.
- DevZone post of the robustness report (fork#2), Damir's watchdog values,
  pigeontracker bench-flavor decision.
