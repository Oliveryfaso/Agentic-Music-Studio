# S7 Portfolio Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Productize Motif Forge's existing Agent/Studio loop with authoritative Export and Run Inspector surfaces, a truthful 96+ case Eval report, and a deterministic portfolio demonstration.

**Architecture:** New backend modules are read-only projections over existing PostgreSQL Revision, Run, Job, Artifact, approval, and event facts. React pages consume generated OpenAPI types and preserve existing state machines. Eval and demo assets remain deterministic and local; S7 adds no Graph, model role, persistence schema, or paid-call requirement.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI/OpenAPI, SQLAlchemy/PostgreSQL, React 19, TypeScript 5.9, TanStack Query, Vitest, Pytest, Docker Compose, Chromium smoke.

**Spec:** `docs/superpowers/specs/2026-08-25-s7-portfolio-release-design.md`

## Global Constraints

- Preserve exactly one production Parent Graph, `motif-forge-parent.v2`; S7 read surfaces cannot create or resume Graphs.
- Preserve PlanApproval, CandidateSelection, EditPreview HITL, immutable Revision, persistent usage budget, and seven-step Export contracts.
- Use Portfolio Engineering Mode: focused RED/GREEN, one representative PostgreSQL boundary per persisted slice, and combined gates after Tasks 2, 4, and 7.
- Do not add a frontend or backend dependency.
- Do not expose raw prompts, approval assertions, secrets, absolute storage paths, arbitrary event payloads, or unvalidated filenames.
- Do not compute repository/source/document/cache hashes. Verify only existing Artifact/Bundle checksums required by the delivery protocol.
- Internal Eval inventory must be at least 96; public measured inventory at least 50. Expected rejects and `not_measured` cases do not enter measured denominators.
- No paid model call is required. Deterministic S7 smoke must attest zero provider requests and zero tokens.
- Do not implement multi-tenancy, long soak/load certification, disaster recovery, full OTel deployment, or exhaustive fault permutations.
- Every page must cover loading, empty/not-found, partial/failure, and ready states; 390 px remains readable and wide evidence regions scroll horizontally.

---

### Task 1: Authoritative Export projection and secure Bundle delivery

**Files:**
- Create: `services/api/src/motif_forge/application/export_reads.py`
- Create: `services/api/src/motif_forge/infrastructure/persistence/export_reads.py`
- Create: `services/api/src/motif_forge/api/exports.py`
- Modify: `services/api/src/motif_forge/application/generation.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Test: `services/api/tests/unit/application/test_export_reads.py`
- Test: `services/api/tests/unit/api/test_exports.py`
- Test: `services/api/tests/integration/test_postgres_s7_export_reads.py`

**Interfaces:**
- Promote the existing private ordered tuple to public `EXPORT_STEPS` in `application/generation.py` without changing its values or cursor behavior.
- Produce `ExportProjectionStore`, `ExportStepSummary`, `ExportFileSummary`, `ExportBundleSummary`, `RevisionExportProjection`, `ReadRevisionExport`, `BundleFile`, and `ResolveBundleFile`.
- Produce `PostgresExportProjectionStore(SessionFactory)` with `read_revision_export(project_id, revision_id)` and `read_bundle(bundle_id)`.
- Produce `build_export_router(store, artifact_root)` with `GET /projects/{project_id}/revisions/{revision_id}/exports` and `GET /export-bundles/{bundle_id}/files/{filename}`.
- Consume existing `RevisionRow`, `AIRunRow`, `MediaRunRow`, `MediaJobRow`, `AudioArtifactRow`, `ExportBundleArtifactRow`, `EXPORT_STEPS`, and Artifact availability/status enums.

- [ ] **Step 1: Write RED projection and lineage tests**

```python
async def test_export_projection_returns_exact_ordered_delivery_facts() -> None:
    projection = await ReadRevisionExport(store)(PROJECT_ID, REVISION_ID)
    assert tuple(step.step for step in projection.steps) == EXPORT_STEPS
    assert projection.status == "ready"
    assert len(projection.files) == 13
    assert {item.storage_key for item in projection.files} == set()

async def test_cross_revision_artifact_fails_closed_without_a_download_url() -> None:
    projection = await ReadRevisionExport(cross_lineage_store)(PROJECT_ID, REVISION_ID)
    assert projection.status == "failed"
    assert projection.error_code == "EXPORT_LINEAGE_INVALID"
    assert all(item.artifact_id != MALICIOUS_ARTIFACT_ID for item in projection.files)
```

- [ ] **Step 2: Write RED secure file resolver tests**

```python
@pytest.mark.parametrize("filename", ("../master.wav", "folder/master.wav", "master.wav%2f.."))
async def test_bundle_file_rejects_non_leaf_names(filename: str) -> None:
    with pytest.raises(ApplicationError) as captured:
        await ResolveBundleFile(store, artifact_root=ROOT)(BUNDLE_ID, filename)
    assert captured.value.code == "EXPORT_FILE_NAME_INVALID"

async def test_bundle_file_requires_manifest_membership_size_and_checksum() -> None:
    resolved = await ResolveBundleFile(store, artifact_root=ROOT)(BUNDLE_ID, "project.json")
    assert resolved.path == ROOT / "protected/exports/p/r/b/project.json"
    assert resolved.media_type == "application/json"
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_export_reads.py services/api/tests/unit/api/test_exports.py -q`

Expected: collection fails because `motif_forge.application.export_reads` and `motif_forge.api.exports` do not exist.

- [ ] **Step 4: Implement strict application models and safe resolver**

```python
class RevisionExportProjection(DomainModel):
    project_id: UUID
    revision_id: UUID
    source_run_id: UUID | None
    status: Literal["partial", "failed", "ready"]
    bundle: ExportBundleSummary | None
    steps: tuple[ExportStepSummary, ...]
    files: tuple[ExportFileSummary, ...]
    error_code: str | None = None

class ResolveBundleFile:
    async def __call__(self, bundle_id: UUID, filename: str) -> BundleFile:
        if Path(filename).name != filename or not SAFE_FILENAME.fullmatch(filename):
            raise ApplicationError("EXPORT_FILE_NAME_INVALID", "invalid Export filename")
        bundle = require_available_bundle(await self._store.read_bundle(bundle_id))
        directory = resolve_below_root(self._root, bundle.storage_prefix)
        manifest = load_strict_export_manifest(directory / "export-manifest.json")
        member = require_manifest_member(manifest, filename)
        target = resolve_non_symlink_leaf(directory, filename)
        verify_existing_protocol_file(target, byte_size=member.byte_size, checksum=member.sha256)
        return BundleFile(path=target, filename=filename, media_type=media_type_for(filename))
```

- [ ] **Step 5: Implement PostgreSQL exact-lineage projection and routes**

Query the Revision first, select its source Run and one Media Run, then load only Jobs and Artifacts tied to that exact Revision. Build seven step slots in `EXPORT_STEPS` order even when Jobs are missing. Bundle manifest files use `/api/v1/export-bundles/{bundle_id}/files/{filename}`; audio rows use the existing audio content route. Mount the router only when PostgreSQL persistence is configured.

- [ ] **Step 6: Run GREEN and real PostgreSQL boundary**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_export_reads.py services/api/tests/unit/api/test_exports.py -q`

Run: `MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge .venv/bin/pytest services/api/tests/integration/test_postgres_s7_export_reads.py -q`

Run: `.venv/bin/ruff check services/api/src/motif_forge/application/export_reads.py services/api/src/motif_forge/infrastructure/persistence/export_reads.py services/api/src/motif_forge/api/exports.py services/api/tests/unit/application/test_export_reads.py services/api/tests/unit/api/test_exports.py services/api/tests/integration/test_postgres_s7_export_reads.py`

Run: `.venv/bin/mypy services/api/src/motif_forge/application/export_reads.py services/api/src/motif_forge/infrastructure/persistence/export_reads.py services/api/src/motif_forge/api/exports.py`

- [ ] **Step 7: Commit Task 1**

```bash
git add services/api/src/motif_forge/application/export_reads.py services/api/src/motif_forge/application/generation.py services/api/src/motif_forge/infrastructure/persistence/export_reads.py services/api/src/motif_forge/api/exports.py services/api/src/motif_forge/api/app.py services/api/tests/unit/application/test_export_reads.py services/api/tests/unit/api/test_exports.py services/api/tests/integration/test_postgres_s7_export_reads.py
git commit -m "feat: expose authoritative S7 exports"
```

### Task 2: Export page and delivery state UX

**Files:**
- Create: `apps/web/src/features/exports/exportApi.ts`
- Create: `apps/web/src/features/exports/exportApi.test.ts`
- Create: `apps/web/src/features/exports/ExportPage.tsx`
- Create: `apps/web/src/features/exports/ExportPage.test.tsx`
- Modify: `apps/web/src/app/routes.ts`
- Modify: `apps/web/src/app/routes.test.ts`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/features/studio/StudioPage.tsx`
- Modify: `apps/web/src/features/generate/RunPage.tsx`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Produce route `{ name: "export"; projectId: string; revisionId: string }` at `/projects/:projectId/exports/:revisionId`.
- Produce `readRevisionExport(projectId, revisionId)` and `ExportPage`.
- Consume generated `RevisionExportProjection` and existing `requestJson`, `readData`, `navigate`, and Artifact rehydration helpers.

- [ ] **Step 1: Write RED route/API tests**

```typescript
expect(parseRoute(`/projects/${PROJECT_ID}/exports/${REVISION_ID}`)).toEqual({
  name: "export", projectId: PROJECT_ID, revisionId: REVISION_ID,
});
expect(await readRevisionExport(PROJECT_ID, REVISION_ID)).toEqual(READY_EXPORT);
```

- [ ] **Step 2: Write RED page states**

```tsx
it("renders seven steps and only authoritative download links", async () => {
  render(<ExportPage projectId={PROJECT_ID} revisionId={REVISION_ID} />);
  expect(await screen.findAllByTestId("export-step")).toHaveLength(7);
  expect(screen.getByRole("link", { name: /Master WAV/ })).toHaveAttribute(
    "href", `/api/v1/audio-artifacts/${MASTER_ID}/content`,
  );
});

it("keeps safe partial files visible and labels the failed step", async () => {
  serverProjection = PARTIAL_EXPORT;
  render(<ExportPage projectId={PROJECT_ID} revisionId={REVISION_ID} />);
  expect(await screen.findByText("导出部分完成")).toBeInTheDocument();
  expect(screen.getByText("RENDER_FAILED")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run RED**

Run: `npm run test:web -- apps/web/src/app/routes.test.ts apps/web/src/features/exports/exportApi.test.ts apps/web/src/features/exports/ExportPage.test.tsx`

Expected: missing route/module failures.

- [ ] **Step 4: Implement route, API, and page**

Render a header with Revision/Run links, a seven-step ordered list, grouped delivery files, availability/status text, and download links supplied by the API. Unavailable audio shows the existing rehydrate action. A missing Bundle never removes completed safe audio. Add small `查看导出` and `检查 Run` links to Studio/Run only when their identities exist.

- [ ] **Step 5: Add responsive layout**

Use wrapping action rows, `min-width: 0`, and horizontal overflow on the step evidence region. At `max-width: 540px`, stack file metadata and keep labels visible. Do not set a fixed content height.

- [ ] **Step 6: Run GREEN and combined Task 1–2 regression**

Run: `npm run test:web -- apps/web/src/app/routes.test.ts apps/web/src/features/exports/exportApi.test.ts apps/web/src/features/exports/ExportPage.test.tsx apps/web/src/features/studio/StudioPage.test.tsx apps/web/src/features/generate/RunPage.test.tsx`

Run: `npm run build:web`

Run: `npm run generate:openapi && npm run build:web`

- [ ] **Step 7: Commit Task 2**

```bash
git add apps/web/src
git commit -m "feat: add S7 Export workspace"
```

### Task 3: Safe Run Inspector projection and API

**Files:**
- Create: `services/api/src/motif_forge/application/run_inspection.py`
- Create: `services/api/src/motif_forge/infrastructure/persistence/run_inspection.py`
- Create: `services/api/src/motif_forge/api/run_inspection.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Test: `services/api/tests/unit/application/test_run_inspection.py`
- Test: `services/api/tests/unit/api/test_run_inspection.py`
- Test: `services/api/tests/integration/test_postgres_s7_run_inspection.py`

**Interfaces:**
- Produce `RunInspectionStore`, `InspectionEvent`, `DecisionSummary`, `InspectionJob`, `InspectionArtifact`, `RecoverySummary`, `RunVersionSummary`, `AIRunInspection`, and `ReadAIRunInspection`.
- Produce `safe_event_summary(event_type, payload) -> dict[str, str | int | bool | None]`.
- Produce `PostgresRunInspectionStore(SessionFactory)` and `build_run_inspection_router(store, ai_run_uow)`.
- Reuse existing `ReadAIRun`, `ReadAIRunProjection`, and `run_data`; do not duplicate authoritative Run projection rules.

- [ ] **Step 1: Write RED redaction and ordering tests**

```python
def test_safe_event_summary_drops_secret_assertion_path_and_unknown_keys() -> None:
    assert safe_event_summary("approval.recorded", {
        "decision": "approve", "actor_id": "local-user",
        "approval_assertion": "secret", "storage_key": "/private/data",
        "unknown": "drop-me",
    }) == {"decision": "approve", "actor_id": "local-user"}

async def test_inspection_orders_events_and_caps_timeline() -> None:
    result = await ReadAIRunInspection(store, read_run)(RUN_ID)
    assert [item.sequence for item in result.timeline] == list(range(51, 251))
    assert result.timeline_truncated is True
```

- [ ] **Step 2: Write RED read-only PostgreSQL facts test**

Capture counts of Runs, events, Jobs, Artifacts, approvals, and usage before and after two identical Inspector reads. Assert the response is identical and every count is unchanged. Include one replay event, one approval, one selection, seven Jobs, six audio Artifacts, and one Bundle.

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_run_inspection.py services/api/tests/unit/api/test_run_inspection.py -q`

Expected: missing Inspector modules.

- [ ] **Step 4: Implement safe models, allowlist summarizer, and projection**

```python
SAFE_EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    "run.created": ("run_type", "max_model_requests", "max_total_tokens"),
    "plan.persisted": ("plan_id", "provider", "model", "fallback_reason"),
    "approval.recorded": ("decision", "actor_id"),
    "candidate.selected": ("candidate_id", "preview_id", "actor_id"),
    "graph.progress": ("phase", "completed_step", "error_code"),
}

def safe_event_summary(event_type: str, payload: Mapping[str, object]) -> dict[str, SafeValue]:
    return {
        key: cast(SafeValue, payload[key])
        for key in SAFE_EVENT_FIELDS.get(event_type, ())
        if key in payload and isinstance(payload[key], (str, int, bool, type(None)))
    }
```

Load at most 200 newest persisted events, return them in ascending sequence, and set `timeline_truncated`. Derive recovery counts only from known event types. Load Jobs/Artifacts through exact Run/Media Run/Revision lineage and exclude storage keys.

- [ ] **Step 5: Mount GET route and reuse authoritative AIRunData**

The route first reads `AIRunData` using the existing service/UoW, then adds the Inspector projection. A missing Run returns the existing stable `AI_RUN_NOT_FOUND` error. The endpoint performs no audit write.

- [ ] **Step 6: Run GREEN, PostgreSQL, Ruff, and mypy**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_run_inspection.py services/api/tests/unit/api/test_run_inspection.py -q`

Run: `MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge .venv/bin/pytest services/api/tests/integration/test_postgres_s7_run_inspection.py -q`

Run: `.venv/bin/ruff check services/api/src/motif_forge/application/run_inspection.py services/api/src/motif_forge/infrastructure/persistence/run_inspection.py services/api/src/motif_forge/api/run_inspection.py services/api/tests/unit/application/test_run_inspection.py services/api/tests/unit/api/test_run_inspection.py services/api/tests/integration/test_postgres_s7_run_inspection.py`

Run: `.venv/bin/mypy services/api/src/motif_forge/application/run_inspection.py services/api/src/motif_forge/infrastructure/persistence/run_inspection.py services/api/src/motif_forge/api/run_inspection.py`

- [ ] **Step 7: Commit Task 3**

```bash
git add services/api/src/motif_forge/application/run_inspection.py services/api/src/motif_forge/infrastructure/persistence/run_inspection.py services/api/src/motif_forge/api/run_inspection.py services/api/src/motif_forge/api/app.py services/api/tests/unit/application/test_run_inspection.py services/api/tests/unit/api/test_run_inspection.py services/api/tests/integration/test_postgres_s7_run_inspection.py
git commit -m "feat: expose safe Parent Graph inspection"
```

### Task 4: Run Inspector page

**Files:**
- Create: `apps/web/src/features/inspection/inspectionApi.ts`
- Create: `apps/web/src/features/inspection/inspectionApi.test.ts`
- Create: `apps/web/src/features/inspection/RunInspectorPage.tsx`
- Create: `apps/web/src/features/inspection/RunInspectorPage.test.tsx`
- Modify: `apps/web/src/app/routes.ts`
- Modify: `apps/web/src/app/routes.test.ts`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/features/generate/RunPage.tsx`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Produce route `{ name: "inspect"; runId: string }` at `/runs/:runId/inspect`.
- Produce `readRunInspection(runId)` and `RunInspectorPage`.
- Consume generated `AIRunInspection`, existing status vocabulary, and navigation helpers.

- [ ] **Step 1: Write RED route/API/page tests**

```tsx
it("shows graph versions, usage budget, decisions, and ordered timeline", async () => {
  render(<RunInspectorPage runId={RUN_ID} />);
  expect(await screen.findByText("motif-forge-parent.v2")).toBeInTheDocument();
  expect(screen.getByText("0 / 3 model requests")).toBeInTheDocument();
  expect(screen.getAllByTestId("inspection-event").map(node => node.dataset.sequence))
    .toEqual(["1", "2", "3"]);
});

it("renders terminal failure and preserved outputs together", async () => {
  inspection = FAILED_WITH_SAFE_MASTER;
  render(<RunInspectorPage runId={RUN_ID} />);
  expect(await screen.findByText("RENDER_FAILED")).toBeInTheDocument();
  expect(screen.getByText("canonical-master.v1")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run RED**

Run: `npm run test:web -- apps/web/src/app/routes.test.ts apps/web/src/features/inspection/inspectionApi.test.ts apps/web/src/features/inspection/RunInspectorPage.test.tsx`

- [ ] **Step 3: Implement Inspector route, query, and view**

Use semantic sections rather than a canvas: Overview, Graph Timeline, Decisions, Usage/Budget, Recovery, and Outputs. Present event sequences and safe summaries in a horizontally scrollable table. Show `timeline_truncated` as explicit copy. Provide links to the Run page, Studio, and Export only when identities exist.

- [ ] **Step 4: Implement responsive and error states**

At 390 px, sections stack, evidence tables scroll, and status/error labels remain textual. A read failure offers a retry button and never falls back to raw event JSON.

- [ ] **Step 5: Run GREEN and combined Task 3–4 regression**

Run: `npm run generate:openapi`

Run: `npm run test:web -- apps/web/src/app/routes.test.ts apps/web/src/features/inspection/inspectionApi.test.ts apps/web/src/features/inspection/RunInspectorPage.test.tsx apps/web/src/features/generate/RunPage.test.tsx`

Run: `.venv/bin/pytest services/api/tests/unit/api/test_run_inspection.py services/api/tests/unit/application/test_run_inspection.py -q`

Run: `npm run build:web`

- [ ] **Step 6: Commit Task 4**

```bash
git add apps/web/src
git commit -m "feat: add S7 Run Inspector"
```

### Task 5: Versioned 96+ Eval inventory and truthful public report

**Files:**
- Create: `evals/s7-portfolio-release-v1.json`
- Create: `services/api/tests/eval/test_s7_portfolio_eval.py`
- Create: `scripts/run_s7_eval_report.py`
- Create: `tests/test_s7_eval_report_contract.py`
- Create: `apps/web/public/evals/s7-report.v1.json`
- Create: `docs/evals/S7_EVAL_REPORT.md`
- Modify: `package.json`

**Interfaces:**
- Produce exactly 24 S7 cases: 8 export, 6 inspection, 6 recovery/budget/HITL, and 4 portfolio navigation/error cases.
- Produce `build_report() -> dict[str, object]` and CLI `python scripts/run_s7_eval_report.py`.
- Produce deterministic JSON and Markdown without timestamps or machine paths.

- [ ] **Step 1: Write RED inventory semantics tests**

```python
def test_s7_inventory_reaches_internal_and_public_contracts() -> None:
    report = build_report()
    assert report["internal_case_count"] >= 96
    assert report["public_measured_case_count"] >= 50
    assert report["s7_case_count"] == 24

def test_expected_reject_and_not_measured_do_not_enter_denominators() -> None:
    report = build_report()
    measured = report["summary"]["measured"]
    assert measured["denominator"] == measured["passed"] + measured["failed"]
    assert measured["denominator"] < report["internal_case_count"]
```

- [ ] **Step 2: Write RED deterministic output and redaction contracts**

Generate twice and compare bytes. Assert output contains no absolute path, API key name/value, approval assertion, raw prompt, or `generated_at`. Assert perceptual qualities are `not_measured` unless backed by an actual evaluator.

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/eval/test_s7_portfolio_eval.py tests/test_s7_eval_report_contract.py -q`

Expected: missing fixture and runner.

- [ ] **Step 4: Add 24 bounded cases and runner**

```python
def classify(result: CaseResult) -> Literal[
    "measured_pass", "measured_fail", "expected_reject", "not_measured"
]:
    if result.measurement == "runtime_only":
        return "not_measured"
    if result.expected_reject:
        return "expected_reject"
    return "measured_pass" if result.passed else "measured_fail"
```

Inventory the versioned S1–S7 assets explicitly. Do not infer case counts from pytest collection. Execute pure domain/API serializers for S7 measured cases; report historical live provider evidence in a separate `historical_live_acceptance` object.

- [ ] **Step 5: Generate bounded artifacts and run GREEN**

Run: `.venv/bin/python scripts/run_s7_eval_report.py`

Run: `.venv/bin/pytest services/api/tests/eval/test_s1_deterministic_eval.py services/api/tests/eval/test_s2_generate_eval.py services/api/tests/eval/test_s3_replan_eval.py services/api/tests/eval/test_s4_style_pack_eval.py services/api/tests/eval/test_s5_candidate_eval.py services/api/tests/eval/test_s6_edit_eval.py services/api/tests/eval/test_s7_portfolio_eval.py tests/test_s7_eval_report_contract.py -q`

Run: `.venv/bin/ruff check scripts/run_s7_eval_report.py services/api/tests/eval/test_s7_portfolio_eval.py tests/test_s7_eval_report_contract.py`

- [ ] **Step 6: Commit Task 5**

```bash
git add evals/s7-portfolio-release-v1.json services/api/tests/eval/test_s7_portfolio_eval.py scripts/run_s7_eval_report.py tests/test_s7_eval_report_contract.py apps/web/public/evals/s7-report.v1.json docs/evals/S7_EVAL_REPORT.md package.json
git commit -m "feat: publish truthful S7 evaluation report"
```

### Task 6: Portfolio entry, Eval Lab, and guided navigation

**Files:**
- Create: `apps/web/src/features/portfolio/PortfolioPage.tsx`
- Create: `apps/web/src/features/portfolio/PortfolioPage.test.tsx`
- Create: `apps/web/src/features/evaluation/EvaluationPage.tsx`
- Create: `apps/web/src/features/evaluation/EvaluationPage.test.tsx`
- Create: `apps/web/src/features/evaluation/evaluationApi.ts`
- Modify: `apps/web/src/app/routes.ts`
- Modify: `apps/web/src/app/routes.test.ts`
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/app/AppShell.tsx`
- Modify: `apps/web/src/features/projects/ProjectHomePage.tsx`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Produce `/about` and `/evaluation` routes.
- Produce `readEvaluationReport()` from `/evals/s7-report.v1.json`.
- Consume Project Home navigation and the committed report; no backend mutation is added.

- [ ] **Step 1: Write RED portfolio and report UI tests**

```tsx
it("explains the finite Agent loop and links to the evidence surfaces", () => {
  render(<PortfolioPage />);
  expect(screen.getByText(/Plan Approval/)).toBeInTheDocument();
  expect(screen.getByText(/Critic.*Repair/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看 Eval Lab" })).toHaveAttribute("href", "/evaluation");
});

it("shows honest measured denominators and not-measured categories", async () => {
  render(<EvaluationPage />);
  expect(await screen.findByText("96+ internal cases")).toBeInTheDocument();
  expect(screen.getByText(/not measured/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run RED**

Run: `npm run test:web -- apps/web/src/features/portfolio/PortfolioPage.test.tsx apps/web/src/features/evaluation/EvaluationPage.test.tsx apps/web/src/app/routes.test.ts`

- [ ] **Step 3: Implement pages and navigation**

Portfolio content covers Product Loop, Why LangGraph, Human Gates, Deterministic Music Core, Recovery/Cost, and Evidence. Eval Lab shows inventory, measured metrics, style/behavior breakdowns, latency samples, known failure labels, and historical live acceptance as distinct evidence. Add unobtrusive About/Eval navigation to `AppShell`; preserve Project Home as the primary working entry.

- [ ] **Step 4: Add mobile/empty/error coverage and run GREEN**

Run: `npm run test:web -- apps/web/src/features/portfolio/PortfolioPage.test.tsx apps/web/src/features/evaluation/EvaluationPage.test.tsx apps/web/src/app/routes.test.ts apps/web/src/features/projects/ProjectHomePage.test.tsx`

Run: `npm run build:web`

- [ ] **Step 5: Commit Task 6**

```bash
git add apps/web/src
git commit -m "feat: add Motif Forge portfolio evidence pages"
```

### Task 7: Deterministic portfolio smoke, risk gate, and S7 closure

**Files:**
- Create: `scripts/run_s7_portfolio_smoke.py`
- Create: `scripts/run_s7_browser_smoke.mjs`
- Create: `scripts/check_s7.sh`
- Create: `tests/test_s7_script_contract.py`
- Modify: `package.json`
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/NEXT_DEVELOPMENT_ROADMAP.md`
- Modify: `docs/TECH_EVOLUTION.md`
- Modify: `docs/DECISION_LOG.md`
- Modify: `docs/superpowers/plans/2026-08-25-s7-portfolio-release.md`

**Interfaces:**
- Produce no-key `run_s7_portfolio_smoke.py` using public HTTP and queue-produced facts only.
- Produce browser smoke covering `/about`, `/evaluation`, one `/runs/:id/inspect`, one Export page, and 390 px review.
- Produce `scripts/check_s7.sh` as the exact stage gate.

- [ ] **Step 1: Write RED smoke and gate contract tests**

```python
def test_s7_smoke_uses_public_actions_and_attests_no_paid_usage() -> None:
    source = SMOKE.read_text()
    assert "execute_media_job" not in source
    assert '"submitted_model_requests": 0' in source
    assert '"total_tokens": 0' in source
    assert "/inspect" in source and "/exports" in source

def test_s7_gate_runs_eval_web_static_and_postgres_boundaries() -> None:
    source = GATE.read_text()
    for required in ("test_s7_portfolio_eval.py", "test:web", "ruff", "mypy", "test_postgres_s7"):
        assert required in source
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/test_s7_script_contract.py -q`

- [ ] **Step 3: Implement fail-closed deterministic smoke**

Before creating a Project/Run, attest the live container has no DeepSeek key and deterministic fallback is active. Use stable smoke idempotency keys to reuse the same Project/Run after interruption. Drive Plan approval and Candidate selection through HTTP, poll terminal Run, then read Inspector/Export and download one audio plus one manifest. Query PostgreSQL read-only for exact Run usage and lineage; print a bounded JSON summary.

- [ ] **Step 4: Implement browser smoke and exact stage gate**

Browser smoke uses the public UI and visible text; it does not inspect React internals. `check_s7.sh` runs the focused S7 suite, all backend unit tests, all Eval tests, Web tests/build, deterministic OpenAPI regeneration, Ruff, mypy, and the three representative PostgreSQL S7 files when `MOTIF_FORGE_TEST_POSTGRES_DSN` is present.

- [ ] **Step 5: Run host GREEN and combined regression**

Run: `.venv/bin/pytest tests/test_s7_script_contract.py services/api/tests/eval/test_s7_portfolio_eval.py tests/test_s7_eval_report_contract.py -q`

Run: `MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge scripts/check_s7.sh`

- [ ] **Step 6: Run representative Compose and browser acceptance**

Run: `docker compose up -d --build api worker render-worker web postgres redis`

Run: `.venv/bin/python scripts/run_s7_portfolio_smoke.py`

Run: `node scripts/run_s7_browser_smoke.mjs`

Expected deterministic facts: terminal succeeded; one selected Revision; seven Jobs; six audio Artifacts; one Bundle; Inspector/Export/Eval reads succeed; provider requests/tokens are 0/0.

- [ ] **Step 7: Synchronize stage documentation**

Update the five project memory documents with actual evidence only. `PROJECT_GUIDE.md` must state S1–S7 complete. `IMPLEMENTATION_STATUS.md` records exact commands/counts and remaining limitations. `NEXT_DEVELOPMENT_ROADMAP.md` closes S7 and moves deferred production hardening to an optional post-portfolio release section. `TECH_EVOLUTION.md` records implementation and runtime findings. `DECISION_LOG.md` adds a concise S7 portfolio-release ADR without changing earlier history.

- [ ] **Step 8: Re-run final stage gate and diff checks**

Run: `MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge scripts/check_s7.sh`

Run: `git diff --check`

Run: `git status --short`

- [ ] **Step 9: Commit Task 7**

```bash
git add scripts/run_s7_portfolio_smoke.py scripts/run_s7_browser_smoke.mjs scripts/check_s7.sh tests/test_s7_script_contract.py package.json docs
git commit -m "feat: complete S7 portfolio release"
```

## Plan self-review checklist

- Every requirement in the S7 design maps to Tasks 1–7.
- New backend files separate Export and Inspector responsibilities; no existing large API module absorbs both.
- All public response fields and route names are consistent across backend, OpenAPI, and frontend tasks.
- Every behavior-changing Task captures RED before production implementation.
- PostgreSQL evidence is representative and authoritative, not an in-memory counter substitute.
- Eval denominators distinguish measured, expected reject, and not measured.
- No step requires a paid provider call or a new dependency.
- Stage closure includes exact documentation correction and fresh verification.
