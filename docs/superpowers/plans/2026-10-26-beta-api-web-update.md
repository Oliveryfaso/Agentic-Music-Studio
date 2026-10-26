# API/Web-only Beta update preparation

> For agentic workers: implement the approved narrow slice in the original mainline session, then request one independent review. No runtime execution is authorized by this plan.

**Goal:** Prepare the 14ce937 / schema0030 no-Key update without changing the live Beta.
**Stage:** Personal Beta; MF-P01/P13/P16/P17/P18/P20/P21.
**Architecture:** Reuse the existing release loader and Compose selection. A small stdout-only planner validates source, reported image identity and baseline, then proposes an API-only image override and exact old-ID rollback. It never invokes Docker or writes a release pin.
**Spec:** Existing PERSONAL_BETA_RUNBOOK.md, API_KEY_SETTINGS.md and parent-approved API/Web-only maintenance scope.

## Constraints

- Target source is 14ce93714123edeb61a6e71a413882e68dd08385; baseline is approved Inspector a3bfb1a, schema20261020_0030.
- Keep actual release pin, workers, database, resources and services untouched.
- No real Key, provider call, new container, image build, backup or migration.
- Reported image-file hashes are not independent live image verification. Every generated plan remains NOT_READY pending real gates.
- Current activity is UNKNOWN: existing HTTP listings cannot cover all Runs/Jobs/Outbox leases. Do not invent an idle result.

## Review focus

Wrong/old image ID; source drift including untracked migration; schema0031; accidental worker/migrate activation; unsafe or UNKNOWN rollback.

## Tasks

- [x] Add failing tests for the stdout planner: valid proposal, wrong evidence, source/schema drift and exact old-ID API-only rollback.
- [x] Implement only scripts/plan_personal_beta_api_update.py; retain existing release loader and pin.
- [x] Integrate the peer API boundary test-only patch; frontend tests remain owned by the original frontend session.
- [x] Document one bounded build/identity/maintenance/rollback procedure, with actual unknowns and approval gates.
- [x] Run affected offline checks and one independent review. Record source-only completion, not runtime readiness.

Observed: initial11 missing-feature failures, then11PASS; Dockerfile drift RED1→GREEN1;
review-found ignored-source drift RED1→GREEN, final13 proposal cases. Combined gate28PASS
includes original release10 and peer API boundary5 (one existing Starlette warning).
One Important closed at the sole narrow recheck. No actual maintenance occurred.

## Frontend integration follow-up (same stage and requirements)

Integrate the original frontend session's six-file v2 patch once. Preserve its
mock-browser evidence and missing independent process-exit receipt separately.
The API build remains fixed at 14ce937; require a full, explicit Web commit that
descends from that source and matches the selected Web files, including ignored
untracked additions. Test a Web-only commit, source drift and invalid identity
before changing the proposal tool. Re-run affected Python/React checks, types and
build, then one narrow integration review. Commit locally and record the API and
Web identities outside the source tree; no live switch, image build or push.

The last permitted read-only aggregate at 12:02:53 UTC found no active persisted
work (all 22 Jobs succeeded, no leases), not a permanent idle certificate.
The build-capacity gate remains HOLD. Reconnection does not close that gate.
