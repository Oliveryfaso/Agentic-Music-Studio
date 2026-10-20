# P2.3 试听可靠性集成计划

Stage: P2.3 playback reliability follow-up to accepted M2. Requirements: MF-P11 (DAW interaction), MF-P18 (Eval), MF-P20 (truthful interface), MF-P21 (safe local operation).

Scope: six Web production files and two regression files. Source base is d68b900bd8dce6c5786dd0b6c6b531429c9d38a2. No persisted schema, API, DSP, Worker, paid model, theme or infrastructure change. Three-score semantic v2 and score-picker work remain separate and incomplete.

User-visible behavior: Stop/source changes invalidate delayed play receipts; native media pause/play drives the transport; only one audio plays at a time; A/B keeps absolute position and resume intent; the saved Revision and static exported audio are explicitly distinguished from unsaved EQ drafts.

Inputs are available Artifact identities and native media events. Output is browser playback state, never a new Revision. Loading/source switch, unavailable media, normal AbortError, stale async errors and component unmount are bounded locally. There are no retries, new jobs, cost or persistent trace changes. Existing artifact/Revision identity remains the observable reference.

- [x] Candidate RED: delayed play after Stop, native pause and changed source regressions fail on original code.
- [x] Candidate GREEN: four focused files / 25 tests, full Web typecheck and production build pass.
- [x] Candidate real boundary: Mac local Chromium, actual API/Worker artifacts, A/B position and bidirectional media exclusion; retained baseline plus 6 new EQ/bypass jobs, 0 product model calls. This is prior candidate evidence, not integrated evidence or human acceptance.
- [x] Apply only the hash-pinned 8-file playback patch after HEAD/content guards. Preserve existing untracked score plans.
- [x] Run those 25 tests, full Web typecheck and production build in the real repository. Run focused audio/export contract regressions without re-running the original 26 jobs.
- [x] One fresh independent review of the integrated slice; at most one repair/recheck for blocking findings.
- [x] Update implementation status and technical evidence truthfully, inspect Guide diff and scoped storage. No Guide contract change expected.
- [x] Prepare a single human acceptance entry: listening first, then playback switches, score/source disclosures and UI status. Record actual device/user feedback separately. Do not label incomplete three-score UI/semantic work complete.
- [ ] Create a normal development-branch Git checkpoint/push after gates; no main merge, force push or deployment.

Acceptance failures: stale transport state, simultaneous audio, wrong Artifact/Revision, seek reset during A/B, or draft presented as rendered sound. Objective PCM/identity evidence cannot replace physical-device listening.
