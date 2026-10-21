# B2c acceptance-state test closure and outstanding runtime gate

Stage P2.3/B2c; MF-P06/P13/P18/P21. Source baseline dev767be74; PROJECT_GUIDE last commit d68b900, unchanged.

The original frontend patch adds only BetaAcceptanceState.test.tsx. Root independent review found that the decision mock accepted any action; the only repair now asserts project, approve action, an existing thread and the precise candidate hash. One narrow recheck closed this finding. The original frontend's two unknown readonly review receipts remain unknown; this new explicit review does not rewrite their history.

## Actual checks this task

- Reviewed test-only patch SHA256: 323824b9375d80103d58e2f7f79a821c9351439b3eeddd87546add2667036552.
- Two isolated component tests passed, then both passed again from the integrated repository. Full Web TypeScript and git diff --check passed. The first isolated attempt executed zero tests because the task-local runner could not resolve repo dependencies; the task-local config was corrected and the failed receipt retained.
- No production behavior, provider, schema, runtime configuration, container or browser change. The existing previously verified normal Beta entry remains http://127.0.0.1:15173/; this change needs no refresh. This is not a fresh live-health or browser receipt.

The fixtures exercise given mocked route/props/audio-src/link responses. They are not domain-valid musical IR or proof of original-track preservation, actual model calls, persisted canonical Undo, audible sound, downloaded bytes or keyboard interaction. The full 164-test result belongs to the earlier checkpoint; it was not rerun here.

## Real multi-round gate remains open

The new same-environment scenario was prepared and independently reviewed, but the free-baseline command and its sole allowed retry both failed automatic permission review before CreateProcess. No new project, Job, candidate or Revision was created; no unknown business mutation is being retried. The API and resume-dispatcher have no model configuration. No .env content was read, secret injected, Docker secret config saved or model request made.

A precise two-container temporary secret configuration requires explicit and native approval because the existing Compose environment path records the value in Docker configuration metadata. There is no public elicitation_request_id or secret approval card issued by this session. The old browser native request remains unknown and is not reissued or bypassed.

The same CNY10 cumulative ceiling remains. Prior upper estimate CNY0.059998 is not billing; this task has zero new requests and zero reserved spend. A future two-request CNY0.20 ceiling is only a blocked draft, not an executed or reserved batch. No real-model R0/R1/R2/Undo U/export entry is fabricated using the older projects or fixtures.

Task-local JSON receipts, reviews, the corrected free script, the first runner failure and budget draft are kept in the task evidence folder beta-model-multiround-20261021. No user audio or secrets are committed. The parent owns the next explicit/native secret decision; the original frontend owns browser UAT.
