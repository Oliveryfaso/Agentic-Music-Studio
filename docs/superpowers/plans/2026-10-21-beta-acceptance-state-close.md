# B2c personal Beta acceptance-state coverage

Stage: P2.3 / B2c; MF-P06/P13/P18/P21. Baseline: dev 767be74; PROJECT_GUIDE remains at d68b900 and unchanged.

## Scope

Integrate the original frontend line's single new component test file. It covers two mock edit confirmations, the new Undo Revision identity and route/score/audio/export propagation, plus reopening an existing fixed export plan. The independent review found that the approval mock ignored action; the reviewed candidate now requires the exact project, approve action, known thread and candidate hash. No runtime behavior, provider configuration, dependencies, services or persisted schema change.

## Verification and completion boundary

Run the two new tests and full Web TypeScript against the actual integration. Preserve the original frontend results, independent review and the initial isolated dependency-resolution failure. The workspace reviewed candidate already passed both tests and TypeScript; integration results still require their own receipt. No need to rerun the previously passed full 164-test suite for this test-only change.

These are module-mocked route/props checks, not legal musical IR validation, real model/Job/PG verification, audio playback, downloads or browser UAT. The same-environment real-model two-round/Undo loop is still blocked on explicit/native secret configuration approval; the isolated free API preparation was not executed after two automatic approval timeouts. No new model requests or fee reservations. Do not fill missing real project/Revision identifiers using fixtures or historical projects.

## Delivery

Keep main and PROJECT_GUIDE unchanged, integrate only this test, plan and factual status/evidence records, report exact checks and limitations, then use the already-authorized normal dev push after verification. No container refresh is needed for test-only content. Keep the existing Beta and original candidates/works untouched.
