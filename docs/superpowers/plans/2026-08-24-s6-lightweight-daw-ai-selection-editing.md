# S6 Lightweight DAW and AI Selection Editing Implementation Plan

> Completion note (2026-08-25): Tasks 1–8 are implemented and stage-accepted. The optional paid Edit-planner acceptance was not needed; S6 closed on deterministic no-key and existing paid Generate-provider evidence. Portfolio Engineering Mode kept browser coverage on the representative save/edit/refresh/mobile journey while reducer/component tests cover the broader manual-control matrix.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the read-only Studio into a lightweight command-based DAW and add bounded AI selection editing under the existing Parent Graph, with L0/L1 atomic Revision commits and L2/L3 Preview/HITL.

**Architecture:** Manual gestures and AI proposals converge on the existing `EditorCommand` domain. The browser retains only Base Revision plus ordered Draft commands, while the Parent Graph edit branch builds a bounded `EditPatchProposal`, runs pure simulation and deterministic ChangeImpact policy, then routes to an immutable Revision or CandidateSnapshot/Preview. PostgreSQL remains authoritative; render and persistence stay outside model tools.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, FastAPI/OpenAPI, SQLAlchemy/PostgreSQL, PostgreSQL checkpointer, Celery/Redis Outbox, React 19, TypeScript 5.9, Canvas, TanStack Query, Vitest, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-s6-lightweight-daw-ai-selection-editing-design.md`

## Global Constraints

- Covered requirements are `MF-P05`, `MF-P06`, `MF-P10`, `MF-P11`, `MF-P13`, `MF-P18`, `MF-P20`, and `MF-P21`; do not change unlisted product requirements as cleanup.
- Preserve exactly one production Parent Graph (`motif-forge-parent.v2`); one AI edit creates one finite `parent.edit.v1` Run/thread.
- Manual editor actions do not create Graph Runs. AI edits do not bypass the Parent Graph.
- Browser Draft, immutable Revision, PreviewCandidate, and Audio Runtime remain four distinct states.
- Models emit only strict `edit-patch-proposal.v1`; they cannot persist, enqueue, render, download, access paths, or lower deterministic ChangeImpact.
- L0/L1 creates one immutable Revision plus Undo. L2/L3 creates a CandidateSnapshot/Preview and cannot advance Branch head before approval.
- Locked-range contact and non-target changes fail closed. They do not become an acceptable high-impact Preview.
- Local reviewed Style Pack presets are the only S6 sound catalog. External search/download remains closed.
- No new frontend dependency is required; use React reducer/context and existing TanStack Query/OpenAPI conventions.
- Use Portfolio Engineering Mode: focused RED/GREEN and one representative PostgreSQL boundary per persisted slice; combined regression every 2–3 Tasks and at the S6 gate. Leave exhaustive fault/load/multi-tenant work to S7.
- No paid call is required during Tasks 1–7. Task 8 may run one explicitly budgeted DeepSeek edit request only if the runtime guard proves one request and no retry.
- Never commit Secrets, `.env`, user audio, Artifact bytes, caches, or machine-specific product paths.
- Do not compute repository, source-file, document, cache, or incidental output hashes. Existing Revision/Candidate/Artifact/idempotency/non-target hashes remain protocol-required facts.

---

### Task 1: EditorCommand completion, EditPatchProposal, simulation, and locality policy

**Files:**
- Create: `services/api/src/motif_forge/domain/editing.py`
- Modify: `services/api/src/motif_forge/domain/commands.py`
- Modify: `services/api/src/motif_forge/domain/policies.py`
- Test: `services/api/tests/unit/domain/test_editing.py`
- Test: `services/api/tests/unit/domain/test_commands.py`
- Test: `services/api/tests/unit/domain/test_policies.py`

**Interfaces:**
- Produces `EDIT_PATCH_SCHEMA_VERSION = "edit-patch-proposal.v1"`.
- Produces `LockedRangeRef`, `EditVersionRefs`, `EditPatchProposal`, `AffectedRange`, `EditSimulationResult`, and `simulate_edit_patch(base: ArrangementIR, proposal: EditPatchProposal) -> EditSimulationResult`.
- Produces `DuplicateClipCommand` and extends `set_track_param` with `eq_low_db`, `eq_mid_db`, and `eq_high_db`.
- Produces `compute_actual_edit_impact(proposal: EditPatchProposal, base: ArrangementIR, candidate: ArrangementIR, affected: tuple[AffectedRange, ...]) -> ChangeImpact` and `assert_edit_locality(base: ArrangementIR, candidate: ArrangementIR, selection: Selection, locked_ranges: tuple[LockedRangeRef, ...], affected: tuple[AffectedRange, ...]) -> None`.
- Consumes existing `Selection`, `EditorCommand`, `apply_commands`, `ArrangementIR`, `StructuralDiffEntry`, and `ChangeImpact`.

- [ ] **Step 1: Write RED tests for the missing manual commands**

```python
def test_duplicate_clip_creates_the_requested_stable_copy() -> None:
    base = arrangement_with_note_clip()
    command = DuplicateClipCommand(
        command_id=uid(90), actor_kind="human", client_sequence=0,
        selection=Selection(track_ids=(TRACK_ID,), start_tick=0, end_tick=1920),
        payload=DuplicateClipPayload(
            track_id=TRACK_ID, clip_id=CLIP_ID,
            duplicate_clip_id=uid(91), start_tick=1920,
        ),
    )
    result = apply_command(base, command)
    assert [clip.clip_id for clip in result.tracks[0].clips] == [CLIP_ID, uid(91)]
    assert result.tracks[0].clips[1].start_tick == 1920

@pytest.mark.parametrize("parameter", ["eq_low_db", "eq_mid_db", "eq_high_db"])
def test_track_eq_is_changed_only_through_allowlisted_parameters(parameter: str) -> None:
    result = apply_command(arrangement_with_note_clip(), set_track_float(parameter, -2.5))
    assert getattr(result.tracks[0].eq, parameter.removeprefix("eq_")) == -2.5
```

- [ ] **Step 2: Write RED proposal, scope, and impact tests**

```python
def test_simple_agent_gain_patch_simulates_as_l0_and_preserves_non_target_material() -> None:
    result = simulate_edit_patch(base_arrangement(), gain_proposal(selection=(0, 1920)))
    assert result.actual_change_impact is ChangeImpact.L0
    assert result.affected_ranges == (AffectedRange(track_id=TARGET, start_tick=0, end_tick=1920),)
    assert result.non_target_preserved is True

def test_agent_melody_rewrite_is_l2_even_when_predicted_l1() -> None:
    result = simulate_edit_patch(base_arrangement(), melody_rewrite(predicted=ChangeImpact.L1))
    assert result.actual_change_impact is ChangeImpact.L2

def test_scope_or_lock_violation_fails_before_any_candidate_is_accepted() -> None:
    with pytest.raises(DomainValidationError) as captured:
        simulate_edit_patch(locked_arrangement(), proposal_that_changes_outside_selection())
    assert {item.code for item in captured.value.issues} == {"EDIT_SCOPE_VIOLATION"}
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/domain/test_editing.py services/api/tests/unit/domain/test_commands.py services/api/tests/unit/domain/test_policies.py -q`  
Expected: collection fails for missing `motif_forge.domain.editing` and `DuplicateClipCommand`.

- [ ] **Step 4: Implement command completion and strict proposal models**

```python
class DuplicateClipPayload(ClipTargetPayload):
    duplicate_clip_id: UUID
    start_tick: int = Field(ge=0)

class DuplicateClipCommand(CommandEnvelope):
    command_type: Literal["duplicate_clip"] = "duplicate_clip"
    payload: DuplicateClipPayload

class EditPatchProposal(DomainModel):
    schema_version: Literal["edit-patch-proposal.v1"] = "edit-patch-proposal.v1"
    proposal_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    selection: Selection
    locked_ranges: tuple[LockedRangeRef, ...] = ()
    commands: tuple[EditorCommand, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=800)
    evidence_refs: tuple[str, ...] = ()
    expected_effect: str = Field(min_length=1, max_length=400)
    predicted_change_impact: ChangeImpact
    confidence: float = Field(ge=0.0, le=1.0)
    versions: EditVersionRefs
```

Validate that every proposal command has `actor_kind="agent"`, sequences are stable, Project/Base identity is complete, and command selections are within the proposal selection. Implement duplicate ID collision checks and update the existing discriminated `EditorCommand` union.

- [ ] **Step 5: Implement pure simulation, structural comparison, and actual impact escalation**

```python
def simulate_edit_patch(base: ArrangementIR, proposal: EditPatchProposal) -> EditSimulationResult:
    candidate = apply_commands(base, proposal.commands)
    affected = actual_affected_ranges(base, candidate)
    assert_edit_locality(base, candidate, proposal.selection, proposal.locked_ranges, affected)
    actual = compute_actual_edit_impact(proposal, base, candidate, affected)
    return EditSimulationResult(
        candidate_ir=candidate,
        candidate_content_hash=arrangement_content_hash(candidate),
        structural_diff=structural_diff(base, candidate),
        affected_ranges=affected,
        non_target_preserved=True,
        non_target_preservation_hash=non_target_projection_hash(base, proposal.selection),
        actual_change_impact=max(proposal.predicted_change_impact, actual),
        render_recommendation=render_recommendation(actual),
    )
```

Use structural equality for locality decisions; the non-target hash is only the existing protocol evidence after equality succeeds. New creative tracks and agent melody/harmony rewrites are at least L2. Locked overlap raises `LOCKED_RANGE_VIOLATION`; any changed pre-existing object outside selection raises `EDIT_SCOPE_VIOLATION`.

- [ ] **Step 6: Run GREEN and static checks**

Run: `.venv/bin/pytest services/api/tests/unit/domain/test_editing.py services/api/tests/unit/domain/test_commands.py services/api/tests/unit/domain/test_policies.py -q`  
Run: `.venv/bin/ruff check services/api/src/motif_forge/domain services/api/tests/unit/domain/test_editing.py`  
Run: `.venv/bin/mypy services/api/src/motif_forge/domain/editing.py services/api/src/motif_forge/domain/commands.py services/api/src/motif_forge/domain/policies.py`

- [ ] **Step 7: Commit Task 1**

```bash
git add services/api/src/motif_forge/domain services/api/tests/unit/domain
git commit -m "feat: add bounded S6 edit simulation"
```

### Task 2: Manual Revision commit, inverse Revision Undo, and public write API

**Files:**
- Create: `services/api/src/motif_forge/application/undo.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/database.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Test: `services/api/tests/unit/application/test_undo.py`
- Test: `services/api/tests/unit/api/test_project_writes.py`
- Test: `services/api/tests/integration/test_postgres_s6_manual_edits.py`

**Interfaces:**
- Produces `build_inverse_commands(parent: ArrangementIR, committed: ArrangementIR, commands: tuple[EditorCommand, ...], *, actor_id: str) -> tuple[EditorCommand, ...]` as pure logic in `application/undo.py`.
- Produces `UndoCommittedRevisionRequest`, `UndoCommittedRevisionResult`, and `UndoCommittedRevision`.
- Adds `ProjectTransaction.list_revision_commands(revision_id) -> tuple[EditorCommand, ...]`.
- Uses `target.parent_revision_id` with the existing `ProjectTransaction.get_revision(revision_id)` to load the authoritative parent.
- Adds `POST /api/v1/projects/{project_id}/undo`.

- [ ] **Step 1: Write RED inverse-command and conflict tests**

```python
async def test_undo_move_creates_a_new_inverse_revision() -> None:
    committed = await commit(move_clip(start_tick=1920))
    undone = await UndoCommittedRevision(uow)(undo_request(committed.revision_id))
    assert undone.revision_id != committed.revision_id
    assert uow.branch_head == undone.revision_id
    assert uow.revisions[undone.revision_id].arrangement_ir == root_ir()

async def test_undo_refuses_a_stale_branch_head_and_preserves_history() -> None:
    with pytest.raises(RevisionConflictError):
        await UndoCommittedRevision(uow)(undo_request(TARGET_REVISION, base_revision_id=STALE))
    assert uow.revision_count == 3
```

Cover inverse behavior for move, trim, split, duplicate, track/clip parameters, and note add/update/delete. When a command cannot be safely inverted from authoritative before/after facts, return `UNDO_NOT_AVAILABLE` without mutation.

- [ ] **Step 2: Write RED HTTP and real PostgreSQL tests**

```python
response = client.post(
    f"/api/v1/projects/{project_id}/undo",
    headers={"Idempotency-Key": "undo-revision-0001"},
    json={
        "branch_id": str(branch_id),
        "base_revision_id": str(committed_revision_id),
        "target_revision_id": str(committed_revision_id),
    },
)
assert response.status_code == 201
assert response.json()["data"]["replayed"] is False
```

The PostgreSQL test commits one multi-command batch, replays its idempotency key, undoes it once, replays Undo, and asserts exact Branch/Revision/command-batch counts.

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_undo.py services/api/tests/unit/api/test_project_writes.py services/api/tests/integration/test_postgres_s6_manual_edits.py -q`  
Expected: failures for missing Undo service, transaction reader, and route.

- [ ] **Step 4: Implement authoritative inverse Revision creation**

```python
class UndoCommittedRevisionRequest(DomainModel):
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    target_revision_id: UUID
    actor_id: str
    idempotency_key: str = Field(min_length=8, max_length=160)

class UndoCommittedRevision:
    async def __call__(self, request: UndoCommittedRevisionRequest) -> UndoCommittedRevisionResult:
        fingerprint = request_hash({
            "schema": "revision.undo.v1",
            **request.model_dump(mode="json", exclude={"idempotency_key"}),
        })
        async with self._uow_factory() as transaction:
            hit = await transaction.get_idempotency(
                operation="revision.undo.v1",
                key=request.idempotency_key,
                request_hash=fingerprint,
            )
            if hit is not None:
                return replay_undo_result(hit, fingerprint)
            branch = await transaction.lock_branch(
                project_id=request.project_id, branch_id=request.branch_id
            )
            require_exact_head(branch, request.base_revision_id)
            target = require_revision(
                await transaction.get_revision(request.target_revision_id), request.project_id
            )
            parent = require_revision(
                await transaction.get_revision(require_parent_id(target)), request.project_id
            )
            commands = await transaction.list_revision_commands(target.revision_id)
            inverse = build_inverse_commands(
                parent.arrangement_ir, target.arrangement_ir, commands, actor_id=request.actor_id
            )
            result = await insert_inverse_revision(
                transaction, request=request, target=target, commands=inverse
            )
            await transaction.save_idempotency(
                operation="revision.undo.v1", key=request.idempotency_key,
                request_hash=fingerprint, resource_id=result.revision_id,
                result_payload=result.model_dump(mode="json", exclude={"replayed"}),
            )
            return result
```

Do not move Branch head backward. Generate stable inverse commands once per Undo request, record reason `HUMAN_UNDO`, and save the idempotency result in the same transaction. Keep the public command-batch route human-only and L0/L1-only.

- [ ] **Step 5: Implement and validate the public route**

Use existing `SuccessEnvelope`, Problem Detail mapping, `LOCAL_ACTOR_ID`, and idempotency header. Return the same Revision summary shape as command-batch commit plus `undone_revision_id`.

- [ ] **Step 6: Run GREEN with PostgreSQL**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_undo.py services/api/tests/unit/api/test_project_writes.py -q`  
Run: `MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" .venv/bin/pytest services/api/tests/integration/test_postgres_s6_manual_edits.py -q`  
Run: `.venv/bin/ruff check services/api/src/motif_forge/application/undo.py services/api/src/motif_forge/api/app.py services/api/tests/unit/application/test_undo.py services/api/tests/integration/test_postgres_s6_manual_edits.py`  
Run: `.venv/bin/mypy services/api/src/motif_forge/application/undo.py services/api/src/motif_forge/infrastructure/persistence/database.py`

- [ ] **Step 7: Commit Task 2**

```bash
git add services/api/src/motif_forge/application services/api/src/motif_forge/infrastructure/persistence/database.py services/api/src/motif_forge/api/app.py services/api/tests
git commit -m "feat: add immutable revision undo"
```

### Task 3: Browser Draft store and editable Timeline vertical slice

**Files:**
- Create: `apps/web/src/features/studio/editorState.ts`
- Create: `apps/web/src/features/studio/editorState.test.ts`
- Create: `apps/web/src/features/studio/studioApi.ts`
- Create: `apps/web/src/features/studio/studioApi.test.ts`
- Create: `apps/web/src/features/studio/StudioToolbar.tsx`
- Modify: `apps/web/src/features/studio/ArrangementTimeline.tsx`
- Modify: `apps/web/src/features/studio/timelineProjection.ts`
- Modify: `apps/web/src/features/studio/StudioPage.tsx`
- Modify: `apps/web/src/features/studio/StudioPage.test.tsx`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Produces `EditorState`, `EditorAction`, `editorReducer`, `projectDraft(baseIr, commands)`, and `canSaveDraft`.
- Produces `commitCommandBatch(request: CommitCommandBatchInput) -> Promise<CommandBatchData>` and `undoCommittedRevision(request: UndoCommittedRevisionInput) -> Promise<UndoRevisionData>` API functions generated against existing OpenAPI DTOs.
- Produces Timeline interaction callbacks for select, move, trim, split, duplicate, delete, and loop.
- Consumes Task 1 command schemas and Task 2 public routes through generated types; no hand-written competing API model.

- [ ] **Step 1: Write RED reducer tests for Draft/Base separation**

```typescript
it("keeps base revision immutable while local undo and redo move the history cursor", () => {
  const initial = createEditorState(BASE_REVISION, arrangement);
  const moved = editorReducer(initial, { type: "append", command: moveClipCommand(1920) });
  expect(moved.base.arrangement_ir).toEqual(arrangement);
  expect(projectDraft(moved).tracks[0].clips[0].start_tick).toBe(1920);
  expect(projectDraft(editorReducer(moved, { type: "undo" }))).toEqual(arrangement);
  expect(projectDraft(editorReducer(editorReducer(moved, { type: "undo" }), { type: "redo" })))
    .toEqual(projectDraft(moved));
});

it("retains draft commands when the server reports a revision conflict", () => {
  const state = editorReducer(withDraft(), { type: "conflict", serverRevisionId: NEW_HEAD });
  expect(state.commands).toHaveLength(1);
  expect(state.conflict?.serverRevisionId).toBe(NEW_HEAD);
});
```

- [ ] **Step 2: Write RED Timeline and Studio behavior tests**

```typescript
fireEvent.pointerDown(screen.getByLabelText("Clip Warm Pad 1"), { clientX: 100 });
fireEvent.pointerMove(screen.getByLabelText("时间线画布"), { clientX: 212 });
fireEvent.pointerUp(screen.getByLabelText("时间线画布"), { clientX: 212 });
expect(screen.getByText("1 个未保存修改")).toBeInTheDocument();
expect(commitSpy).not.toHaveBeenCalled();
fireEvent.click(screen.getByRole("button", { name: "保存 Revision" }));
expect(commitSpy).toHaveBeenCalledTimes(1);
```

Also cover snap, keyboard split/delete/duplicate, horizontal overflow, empty track state, API failure retaining Draft, and successful commit rebasing onto the returned Revision.

- [ ] **Step 3: Run RED**

Run: `./node_modules/.bin/vitest run --config apps/web/vitest.config.ts apps/web/src/features/studio/editorState.test.ts apps/web/src/features/studio/studioApi.test.ts apps/web/src/features/studio/StudioPage.test.tsx`  
Expected: missing Draft modules and editable interaction props.

- [ ] **Step 4: Implement the reducer without adding Zustand**

```typescript
export interface EditorState {
  base: { branchId: string; revisionId: string; arrangement: ArrangementIR };
  commands: EditorCommand[];
  historyCursor: number;
  selection: EditorSelection | null;
  dragPreview: DragPreview | null;
  saveState: "clean" | "dirty" | "saving" | "error" | "conflict";
  conflict: { serverRevisionId: string } | null;
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  // append truncates redo history; undo/redo only move historyCursor
  // commitSuccess installs authoritative Base and removes only committed commands
  // conflict preserves commands
}
```

Mirror only the command operations needed for immediate Draft projection. Fail visibly on an unknown command instead of accepting server/browser semantic drift.

- [ ] **Step 5: Add one-command-on-pointer-up Timeline interactions**

Keep the Canvas for drawing. Add bounded hit testing and an adjacent DOM selection/focus layer for accessible names and keyboard actions. Pointer move updates `dragPreview`; pointer up creates one snapped command. Do not issue an API call per pointer move.

- [ ] **Step 6: Run GREEN, OpenAPI generation, and web build**

Run the Vitest command from Step 3.  
Run: `npm run generate:openapi`  
Run: `npm run build:web`  
Run: `git diff --check`

- [ ] **Step 7: Combined checkpoint after Tasks 1–3**

Run: `.venv/bin/pytest services/api/tests/unit/domain/test_editing.py services/api/tests/unit/application/test_revisions.py services/api/tests/unit/application/test_undo.py services/api/tests/unit/api/test_project_writes.py -q`  
Run: `npm run test:web`  
Expected: existing read-only Studio and Project/Generate journeys remain green while editing tests are included.

- [ ] **Step 8: Commit Task 3**

```bash
git add apps/web/src apps/web/src/generated/api-schema.d.ts
git commit -m "feat: add timeline draft editing"
```

### Task 4: Piano Roll, Mixer, Inspector, and reviewed local Catalog

**Files:**
- Create: `services/api/src/motif_forge/application/sound_catalog.py`
- Create: `services/api/src/motif_forge/api/sound_catalog.py`
- Create: `services/api/tests/unit/application/test_sound_catalog.py`
- Create: `services/api/tests/unit/api/test_sound_catalog.py`
- Create: `apps/web/src/features/studio/PianoRoll.tsx`
- Create: `apps/web/src/features/studio/PianoRoll.test.tsx`
- Create: `apps/web/src/features/studio/MixerPanel.tsx`
- Create: `apps/web/src/features/studio/MixerPanel.test.tsx`
- Create: `apps/web/src/features/studio/ClipInspector.tsx`
- Create: `apps/web/src/features/studio/SampleLibrary.tsx`
- Create: `apps/web/src/features/studio/SampleLibrary.test.tsx`
- Create: `apps/web/src/features/studio/StudioDock.tsx`
- Modify: `services/api/src/motif_forge/api/app.py`
- Modify: `apps/web/src/features/studio/StudioPage.tsx`
- Modify: `apps/web/src/features/studio/editorState.ts`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Produces `SoundCatalogEntry`, `ListLocalSoundCatalog`, and `GET /api/v1/sound-catalog?style=&role=&query=`.
- Produces UI components that emit existing `add_notes`, `update_notes`, `delete_notes`, `set_track_param`, and `set_clip_param` Draft commands.
- Local Catalog is derived only from `builtin_style_pack_registry()`; no network Provider or file mutation is added.

- [ ] **Step 1: Write RED local Catalog contract tests**

```python
def test_local_catalog_returns_only_reviewed_builtin_entries() -> None:
    entries = ListLocalSoundCatalog(builtin_style_pack_registry())(
        style=StyleId.JAZZ, role=TrackRole.BASS, query="upright"
    )
    assert entries
    assert all(item.preset_id.startswith("builtin:") for item in entries)
    assert all(item.reviewed and item.license_id in ALLOWED_LICENSES for item in entries)

def test_catalog_query_never_accepts_external_provider_or_url() -> None:
    with pytest.raises(ValueError):
        SoundCatalogQuery.model_validate({"external": True, "url": "https://example.test"})
```

- [ ] **Step 2: Write RED Piano Roll, Mixer, and empty-library tests**

```typescript
fireEvent.change(screen.getByLabelText("音高"), { target: { value: "67" } });
fireEvent.blur(screen.getByLabelText("音高"));
expect(onCommand).toHaveBeenCalledWith(expect.objectContaining({ command_type: "update_notes" }));

fireEvent.change(screen.getByLabelText("Warm Pad gain"), { target: { value: "-4" } });
fireEvent.pointerUp(screen.getByLabelText("Warm Pad gain"));
expect(onCommand).toHaveBeenCalledTimes(1);

expect(renderLibrary([]).getByText("本地审核音色库为空")).toBeInTheDocument();
expect(screen.queryByRole("button", { name: /联网搜索/ })).not.toBeInTheDocument();
```

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_sound_catalog.py services/api/tests/unit/api/test_sound_catalog.py -q`  
Run: `./node_modules/.bin/vitest run --config apps/web/vitest.config.ts apps/web/src/features/studio/PianoRoll.test.tsx apps/web/src/features/studio/MixerPanel.test.tsx apps/web/src/features/studio/SampleLibrary.test.tsx`  
Expected: missing service, route, and Studio dock components.

- [ ] **Step 4: Implement a compact read-only local Catalog projection**

```python
class SoundCatalogEntry(ApiModel):
    preset_id: str
    style: StyleId
    instrument_family: str
    role: str
    low_midi: int
    high_midi: int
    reviewed: Literal[True]
    license_id: str
    attribution_required: bool
```

Filter normalized text across instrument family and role. Return stable order by Style Pack then preset ID. Never accept URL, Provider, path, or external-search flags.

- [ ] **Step 5: Implement Canvas Piano Roll and DOM controls**

Use Canvas for grid/notes and DOM controls/focus proxies for precise editing. Mixer and Inspector controls append one command on interaction end. Explicitly separate EQ, pitch, fades, and loop. The Dock is collapsible and avoids a fixed page height.

- [ ] **Step 6: Run GREEN and integration checks**

Run the Python and Vitest commands from Step 3.  
Run: `npm run generate:openapi`  
Run: `npm run build:web`  
Run: `.venv/bin/ruff check services/api/src/motif_forge/application/sound_catalog.py services/api/src/motif_forge/api/sound_catalog.py services/api/tests/unit/application/test_sound_catalog.py services/api/tests/unit/api/test_sound_catalog.py`

- [ ] **Step 7: Commit Task 4**

```bash
git add services/api/src/motif_forge/application/sound_catalog.py services/api/src/motif_forge/api services/api/tests/unit apps/web/src
git commit -m "feat: add lightweight studio editing panels"
```

### Task 5: Persistent Edit Run and Parent Graph edit branch through impact routing

**Files:**
- Create: `infra/migrations/versions/20260824_0020_s6_edit_runs.py`
- Create: `services/api/src/motif_forge/agent/edit.py`
- Create: `services/api/src/motif_forge/application/edit_runs.py`
- Create: `services/api/tests/unit/agent/test_edit_graph.py`
- Create: `services/api/tests/unit/application/test_edit_runs.py`
- Create: `services/api/tests/integration/test_postgres_s6_edit_runs.py`
- Modify: `services/api/src/motif_forge/domain/ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/tables.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/ai_runs.py`
- Modify: `services/api/src/motif_forge/api/ai_runs.py`
- Modify: `services/api/src/motif_forge/agent/parent_graph.py`
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/worker/resume_dispatcher.py`

**Interfaces:**
- Adds `AIRunType = generate | edit`, `EditRunRequest`, and `EDIT_RUN_STATE_SCHEMA_VERSION = "edit-run-state.v1"`.
- Migration adds `ai_runs.run_type` with generated rows backfilled to `generate`, and nullable strict `edit_request` JSONB.
- Produces `CreateEditAIRun`, `ReadEditContext`, `EditPlanner`, `FallbackEditPlanner`, `EditPreviewDecision`, `initial_edit_state`, and `build_edit_subgraph(dependencies: EditGraphDependencies) -> CompiledStateGraph`.
- Extends `GraphActionPayload.run_type` to `parent.generate.v1 | parent.edit.v1` and dispatches by authoritative `AIRun.run_type`.
- Task stops after deterministic simulation yields `auto_commit` or `preview_required`; Task 6 owns persistence/render/HITL after that route.

- [ ] **Step 1: Write migration and persistent Run RED tests**

```python
async def test_edit_run_persists_strict_request_and_canonical_start_outbox(pg_uow) -> None:
    run = await CreateEditAIRun(pg_uow)(edit_run_request())
    loaded = await ReadAIRun(pg_uow)(run.run_id)
    assert loaded.run_type is AIRunType.EDIT
    assert loaded.edit_request.selection.start_tick == 0
    assert await outbox_payload(run.run_id) == {
        "schema_version": "graph-action.v1", "action": "start",
        "run_id": str(run.run_id), "thread_id": run.thread_id,
        "run_type": "parent.edit.v1", "decision": None,
    }
```

Add migration forward/read tests. The downgrade must fail closed if populated edit Runs exist; no full historical downgrade matrix is required.

- [ ] **Step 2: Write Graph RED tests for bounded context and routes**

```python
async def test_edit_graph_sends_only_selection_and_adjacent_summary_to_planner() -> None:
    result = await graph.ainvoke(
        initial_edit_state(thread_id=THREAD_ID, request=edit_request()), config
    )
    assert planner.context.track_ids == (TARGET_TRACK,)
    assert planner.context.start_tick == 0
    assert planner.context.end_tick == 3840
    assert planner.context.contains_full_arrangement is False
    assert result["edit_route"] == "auto_commit"

async def test_actual_l2_routes_to_preview_without_committing_revision() -> None:
    result = await graph.ainvoke(initial_edit_state(proposal=melody_rewrite()), config)
    assert result["edit_route"] == "preview_required"
    assert commit.count == 0
```

Also cover locked rejection, unsupported no-key intent, one stable fallback motif, cancellation before planner, and provider budget rejection before HTTP.

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/agent/test_edit_graph.py services/api/tests/unit/application/test_edit_runs.py services/api/tests/integration/test_postgres_s6_edit_runs.py -q`  
Expected: missing edit contracts, migration, Parent route, and action publisher support.

- [ ] **Step 4: Implement strict persisted Edit Run identity**

```python
class AIRunType(StrEnum):
    GENERATE = "generate"
    EDIT = "edit"

class EditRunRequest(DomainModel):
    intent: str = Field(min_length=1, max_length=800)
    selection: Selection
    locked_ranges: tuple[LockedRangeRef, ...] = ()
    allow_local_catalog: Literal[True] = True
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
```

Keep `brief` valid only for Generate and `edit_request` valid only for Edit. Update row mapping, request fingerprinting, public create-body validation, OpenAPI projection, and Graph start outbox. Default/backfill existing rows to Generate.

- [ ] **Step 5: Implement bounded context, fallback, and simulation route**

```python
class FallbackEditPlanner:
    async def __call__(self, context: BoundedEditContext) -> EditPatchProposal:
        if parsed := parse_explicit_parameter_edit(context.intent):
            return explicit_parameter_proposal(context, parsed)
        if parsed := parse_supported_local_motif_request(context.intent):
            return deterministic_motif_proposal(context, parsed)
        raise ApplicationError("EDIT_FALLBACK_UNSUPPORTED", "edit is outside fallback allowlist")
```

The DeepSeek planner protocol is strict but tests use a fake. Build context from the exact Base Revision with target tracks, 1–2 adjacent bars, key/chord/rhythm facts, locks, and matching local catalog summaries only. Do not add render or persistence tools to the model.

- [ ] **Step 6: Mount the edit route and authoritative action dispatch**

Extend `ParentGraphState.operation` and top-level routing with `edit`; preserve all existing Import/Generate/Export routes. `ParentGraphActionPublisher` builds `initial_edit_state` only from the authoritative persisted `EditRunRequest`, never from untrusted outbox duplicates.

- [ ] **Step 7: Run GREEN with restart boundary**

Run: `.venv/bin/pytest services/api/tests/unit/agent/test_edit_graph.py services/api/tests/unit/application/test_edit_runs.py services/api/tests/unit/agent/test_parent_graph.py services/api/tests/unit/worker/test_outbox.py -q`  
Run: `MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" .venv/bin/pytest services/api/tests/integration/test_postgres_s6_edit_runs.py services/api/tests/integration/test_generate_dispatcher.py -q`  
Run: `.venv/bin/ruff check services/api/src/motif_forge/agent/edit.py services/api/src/motif_forge/application/edit_runs.py services/api/src/motif_forge/domain/ai_runs.py services/api/src/motif_forge/worker/outbox.py`  
Run: `.venv/bin/mypy services/api/src/motif_forge/agent/edit.py services/api/src/motif_forge/application/edit_runs.py services/api/src/motif_forge/agent/parent_graph.py services/api/src/motif_forge/worker/outbox.py`

- [ ] **Step 8: Commit Task 5**

```bash
git add infra/migrations/versions/20260824_0020_s6_edit_runs.py services/api/src services/api/tests
git commit -m "feat: mount persistent edit runs"
```

### Task 6: L0/L1 atomic commit and L2/L3 Preview render/HITL

**Files:**
- Create: `infra/migrations/versions/20260824_0021_s6_edit_preview_decisions.py`
- Create: `services/api/src/motif_forge/application/edit_decisions.py`
- Create: `services/api/tests/unit/application/test_edit_decisions.py`
- Create: `services/api/tests/integration/test_postgres_s6_edit_human_loop.py`
- Modify: `services/api/src/motif_forge/domain/ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/application/previews.py`
- Modify: `services/api/src/motif_forge/application/candidate_previews.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/tables.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/ai_runs.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/database.py`
- Modify: `services/api/src/motif_forge/agent/edit.py`
- Modify: `services/api/src/motif_forge/agent/parent_graph.py`
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/api/ai_runs.py`

**Interfaces:**
- Adds `AIRunStatus.WAITING_EDIT_APPROVAL`, nullable `ai_runs.pending_preview_id`, and durable `ai_run_edit_decisions` keyed by Run.
- Produces `RecordEditPreviewDecision`, `ReadEditPreviewDecision`, and strict `EditPreviewDecision{approve|reject|cancel}`.
- L0/L1 consumes `CommitCommandBatch(author_kind=agent)` with a stable Graph operation key.
- L2/L3 consumes existing `CreateCommandPreview`, Candidate Preview enqueue/collect, and `DecidePreview` materialization.
- Approval outbox carries the raw assertion only to the same checkpoint; the database decision keeps its hash and safe fields.

- [ ] **Step 1: Write RED auto-commit tests**

```python
async def test_l0_edit_commits_once_across_duplicate_graph_delivery() -> None:
    first = await run_edit(explicit_gain_request())
    second = await replay_same_start_and_resume(first.run_id)
    assert first.revision_id == second.revision_id
    assert await revision_count(project_id) == 2  # root/generated base + one edit
    assert await model_request_count(first.run_id) == 0

async def test_actual_l2_never_calls_auto_commit() -> None:
    result = await run_until_preview(melody_rewrite_request())
    assert result.phase == "waiting_edit_approval"
    assert await branch_head() == BASE_REVISION_ID
```

- [ ] **Step 2: Write RED Preview/approval PostgreSQL tests**

```python
async def test_preview_requires_real_artifact_then_approve_materializes_once() -> None:
    waiting = await run_until_preview_ready()
    assert waiting.preview.preview_artifact_ids == (PREVIEW_ARTIFACT_ID,)
    assert await branch_head() == BASE_REVISION_ID
    approved = await record_and_dispatch_decision(waiting.run_id, "approve")
    replay = await record_and_dispatch_decision(waiting.run_id, "approve")
    assert approved.revision_id == replay.revision_id
    assert await revision_count(PROJECT_ID) == 2

@pytest.mark.parametrize("decision", ["reject", "cancel"])
async def test_reject_or_cancel_leaves_branch_unchanged(decision: str) -> None:
    result = await record_and_dispatch_decision(RUN_ID, decision)
    assert result.terminal_status in {"rejected", "cancelled"}
    assert await branch_head() == BASE_REVISION_ID
```

Cover approval before Preview Artifact ready, stale Branch head, wrong Preview/Run identity, changed idempotency body, duplicate Worker completion, and restart at `waiting_edit_approval`.

- [ ] **Step 3: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_edit_decisions.py services/api/tests/unit/agent/test_edit_graph.py services/api/tests/unit/worker/test_outbox.py services/api/tests/integration/test_postgres_s6_edit_human_loop.py -q`  
Expected: missing waiting status, decision persistence, Preview attachment, and resume decision type.

- [ ] **Step 4: Implement run-aware decision persistence and migration**

```python
class EditPreviewDecision(DomainModel):
    action: Literal["approve", "reject", "cancel"]
    preview_id: UUID
    expected_candidate_content_hash: str
    actor_id: str
    approval_assertion: str = Field(min_length=16, max_length=500)
    note: str = Field(default="", max_length=500)
```

The migration changes the AI Run waiting-state constraint so Generate waits with Plan identity and Edit waits with Preview identity. `RecordEditPreviewDecision` checks persistent idempotency before current state, validates exact Preview/Run/Base identity, stores the assertion hash and decision, and writes canonical `graph.resume.requested` in the same transaction.

- [ ] **Step 5: Wire auto-commit and high-impact Preview nodes**

For L0/L1, call `CommitCommandBatch` with stable key `edit-run:{run_id}:commit:{proposal_id}` and project/branch/base from authoritative state. For L2/L3:

1. call `CreateCommandPreview` with the exact simulated commands and structural diff;
2. enqueue one `candidate-preview.v1` Job for the CandidateSnapshot;
3. wait for the authoritative completion event;
4. attach the returned Artifact to the same Preview;
5. set Run status/checkpoint to `waiting_edit_approval` and interrupt.

On approve, call `DecidePreview` with a stable Graph idempotency key. On reject/cancel, terminate without Branch movement. Never render or approve by client-supplied paths/IR.

- [ ] **Step 6: Extend strict Graph action decisions and dispatcher restart**

`GraphActionPayload.decision` becomes the discriminated union of Plan, CandidateSelection, and EditPreview decisions. `ParentGraphActionPublisher` checks phase/run type before resume, reloads authoritative decision when raw outbox delivery is unavailable, and uses `ainvoke(None)` only for already-approved nonterminal checkpoints as established in S2.

- [ ] **Step 7: Run GREEN with real PostgreSQL and existing Preview regressions**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_edit_decisions.py services/api/tests/unit/application/test_previews.py services/api/tests/unit/application/test_candidate_previews.py services/api/tests/unit/agent/test_edit_graph.py services/api/tests/unit/worker/test_outbox.py -q`  
Run: `MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" .venv/bin/pytest services/api/tests/integration/test_postgres_s6_edit_human_loop.py services/api/tests/integration/test_postgres_s5_candidate_preview_jobs.py services/api/tests/integration/test_generate_dispatcher.py -q`  
Run: `.venv/bin/ruff check services/api/src/motif_forge/application/edit_decisions.py services/api/src/motif_forge/agent/edit.py services/api/src/motif_forge/worker/outbox.py`  
Run: `.venv/bin/mypy services/api/src/motif_forge/application/edit_decisions.py services/api/src/motif_forge/agent/edit.py services/api/src/motif_forge/worker/outbox.py`

- [ ] **Step 8: Combined checkpoint after Tasks 4–6**

Run: `.venv/bin/pytest services/api/tests/unit services/api/tests/eval/test_s5_candidate_eval.py -q --ignore-glob='**/._*'`  
Run: `npm run test:web`  
Run: `npm run build:web`  
Expected: existing Generate CandidateSelection and new Edit PreviewApproval remain distinct and green.

- [ ] **Step 9: Commit Task 6**

```bash
git add infra/migrations/versions/20260824_0021_s6_edit_preview_decisions.py services/api/src services/api/tests
git commit -m "feat: route AI edits through revision or preview"
```

### Task 7: AI selection panel, edit Run recovery, Preview diff, and conflict UX

**Files:**
- Create: `apps/web/src/features/studio/EditPanel.tsx`
- Create: `apps/web/src/features/studio/EditPanel.test.tsx`
- Create: `apps/web/src/features/studio/editRunApi.ts`
- Create: `apps/web/src/features/studio/editRunApi.test.ts`
- Create: `apps/web/src/features/studio/editRunState.ts`
- Create: `apps/web/src/features/studio/editRunState.test.ts`
- Create: `apps/web/src/features/studio/EditPreviewCard.tsx`
- Create: `apps/web/src/features/studio/EditPreviewCard.test.tsx`
- Modify: `apps/web/src/features/studio/StudioPage.tsx`
- Modify: `apps/web/src/features/studio/editorState.ts`
- Modify: `apps/web/src/features/generate/runEvents.ts`
- Modify: `apps/web/src/shared/openapi.ts`
- Modify: `apps/web/src/styles.css`
- Modify: `apps/web/src/app/AppShell.tsx`

**Interfaces:**
- Produces create/read/SSE/resume/cancel API functions for `run_type=edit` using generated OpenAPI types.
- Produces `EditRunViewState` reducer for planning, simulation, auto-commit, preview render, waiting approval, terminal, disconnected, and conflict states.
- Produces `EditPanel` bound to the current selection and `EditPreviewCard` bound to authoritative Preview identity.

- [ ] **Step 1: Write RED AI panel context and approval tests**

```typescript
it("submits only the visible selection, locks, intent, and current base identity", async () => {
  renderPanel(selectionFixture());
  fireEvent.change(screen.getByLabelText("AI 编辑要求"), { target: { value: "把这里的 Pad 降低 2 dB" } });
  fireEvent.click(screen.getByRole("button", { name: "运行选区编辑" }));
  expect(createEditRun).toHaveBeenCalledWith(expect.objectContaining({
    branch_id: BRANCH_ID,
    base_revision_id: REVISION_ID,
    run_type: "edit",
    edit_request: expect.objectContaining({ selection: { track_ids: [TRACK_ID], start_tick: 0, end_tick: 1920 } }),
  }));
});

it("does not call approve until a real preview artifact is available", () => {
  renderPreview({ availability: "rehydrating" });
  expect(screen.getByRole("button", { name: "批准 Preview" })).toBeDisabled();
});
```

- [ ] **Step 2: Write RED auto-commit, conflict, and SSE replay tests**

```typescript
applyEditRunEvent(state, revisionCommittedEvent(REVISION_2));
expect(state.mode).toBe("committed");
expect(queryInvalidation).toContainEqual(["revision-studio", PROJECT_ID, REVISION_2]);

const conflicted = applyEditRunEvent(withPendingDraft(), editConflictEvent(REVISION_3));
expect(conflicted.draftCommands).toHaveLength(1);
expect(conflicted.mode).toBe("conflict");
```

Cover Last-Event-ID reconnect, refresh using Run ID in URL/query state, reject/cancel, empty selection, local fallback unsupported, provider error, root unavailable, and mobile review-only behavior.

- [ ] **Step 3: Run RED**

Run: `./node_modules/.bin/vitest run --config apps/web/vitest.config.ts apps/web/src/features/studio/EditPanel.test.tsx apps/web/src/features/studio/editRunApi.test.ts apps/web/src/features/studio/editRunState.test.ts apps/web/src/features/studio/EditPreviewCard.test.tsx apps/web/src/features/studio/StudioPage.test.tsx`  
Expected: missing edit UI modules and edit Run projections.

- [ ] **Step 4: Implement API/reducer with authoritative terminal behavior**

Reuse the existing SSE parser and persistent event IDs. Edit events update Run view state or invalidate queries; they never patch committed IR directly. Auto-commit switches Base only after the committed Revision is readable. Preview approval waits for `revision.committed` and never treats Preview ID as Revision ID.

- [ ] **Step 5: Implement selection-bound panel and Preview diff UI**

Display selected tracks/bars, locks, predicted approval behavior, actual impact, affected ranges, rationale/evidence, Preview availability, and usage summary. Do not show chain-of-thought. Disable render/Preview-producing actions when the Artifact Root is unavailable; allow safe local Draft work to continue.

- [ ] **Step 6: Implement layout, accessibility, and narrow behavior**

Use the existing graphite/cyan/purple/magenta tokens. Add non-color status text, reduced-motion behavior, DOM focus proxies, keyboard labels, long-track-name overflow, and Inspector/Dock mutual exclusion below desktop width. Mobile renders playback and approval, not Canvas edit controls.

- [ ] **Step 7: Run GREEN, deterministic OpenAPI generation, and web build**

Run the Vitest command from Step 3.  
Run: `npm run generate:openapi`  
Run: `npm run build:web`  
Run: `git diff --check`

- [ ] **Step 8: Commit Task 7**

```bash
git add apps/web/src
git commit -m "feat: add AI selection editing workspace"
```

### Task 8: Representative S6 Eval, no-key browser journey, stage evidence, and hygiene

**Files:**
- Create: `services/api/tests/eval/fixtures/s6_edit_cases.v1.json`
- Create: `services/api/tests/eval/test_s6_edit_eval.py`
- Create: `scripts/run_s6_deterministic_smoke.py`
- Create: `scripts/run_s6_browser_smoke.mjs`
- Create: `tests/test_s6_script_contract.py`
- Create: `scripts/check_s6.sh`
- Modify: `package.json`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/TECH_EVOLUTION.md`
- Modify: `docs/NEXT_DEVELOPMENT_ROADMAP.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Produces a versioned representative S6 Eval with success and failure labels.
- Produces `npm run smoke:s6` and `npm run smoke:s6:browser`.
- Produces a fail-closed host/stage gate in `scripts/check_s6.sh`.
- Updates current-fact docs only after runtime evidence exists; does not rewrite `PROJECT_GUIDE.md` unless an approved contract changed.

- [ ] **Step 1: Write RED Eval and smoke contract tests**

The fixture contains at least 12 cases:

```json
[
  {"id":"s6-l0-gain","expected_route":"auto_commit","expected_impact":"L0"},
  {"id":"s6-l1-note","expected_route":"auto_commit","expected_impact":"L1"},
  {"id":"s6-l1-to-l2","expected_route":"preview","expected_impact":"L2"},
  {"id":"s6-l2-melody","expected_route":"preview","expected_impact":"L2"},
  {"id":"s6-catalog-timbre","expected_route":"preview","expected_impact":"L2"},
  {"id":"s6-new-accompaniment","expected_route":"preview","expected_impact":"L2"},
  {"id":"s6-locked","expected_error":"LOCKED_RANGE_VIOLATION"},
  {"id":"s6-non-target","expected_error":"EDIT_SCOPE_VIOLATION"},
  {"id":"s6-conflict","expected_error":"REVISION_CONFLICT"},
  {"id":"s6-duplicate-resume","expected_duplicate_spend":0},
  {"id":"s6-fallback-supported","expected_model_requests":0},
  {"id":"s6-fallback-unsupported","expected_error":"EDIT_FALLBACK_UNSUPPORTED"}
]
```

Contract tests assert the browser smoke uses public HTTP/UI plus read-only PostgreSQL facts, never imports or calls Revision/Graph internals, never directly executes media jobs, and checks zero provider request/token facts for no-key mode.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/eval/test_s6_edit_eval.py tests/test_s6_script_contract.py -q`  
Expected: missing fixture, Eval, smoke scripts, and stage gate.

- [ ] **Step 3: Implement honest Eval metrics and deterministic baseline comparison**

Record separate denominators for schema validity, measured locality, impact routing, Preview gate, idempotency, and runtime-only audio checks. Compare direct human commands/no-key fallback against Parent edit cases; do not count reject/conflict cases as successful playable edits. Mark any unmeasured audio judgment as `not_measured` instead of passing it from prose.

- [ ] **Step 4: Implement no-key deterministic smoke**

The host smoke creates or uses one project, commits a manual Timeline/Mixer/Piano Roll batch, undoes it, creates an L0 Edit Run, then creates an L2 Edit Run and approves its real Preview. It asserts exact Branch lineage, one Revision per accepted edit, unchanged Branch on reject/cancel, real Preview Artifact linkage, zero provider requests/tokens, and no external catalog network action.

- [ ] **Step 5: Implement browser smoke**

The browser journey opens Studio, drags/trims a Clip, changes Mixer and Piano Roll values, performs local Undo/Redo, saves, runs a simple AI parameter edit, runs a melody rewrite, waits for Preview, approves it, refreshes, and confirms the new immutable Revision. It also checks narrow overflow and mobile review-only controls.

- [ ] **Step 6: Add optional one-call paid acceptance guard**

If explicitly run, the paid path must verify before any mutation or HTTP call:

- nonempty backend-only key;
- exact `deepseek-v4-flash` model;
- `max_model_requests=1` and transport attempts exactly 1;
- a new fixed paid-test idempotency identity;
- token budget at most 12,000;
- no successful prior paid Run for that identity.

It validates one strict `EditPatchProposal`, Usage Ledger truth, and route only. Do not include the key, raw response, reasoning, or prompt in output. Skip this step by default.

- [ ] **Step 7: Run focused and full stage gates**

Run: `.venv/bin/pytest services/api/tests/eval/test_s6_edit_eval.py tests/test_s6_script_contract.py -q`  
Run: `.venv/bin/pytest services/api/tests/unit services/api/tests/eval -q --ignore-glob='**/._*'`  
Run: `MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" .venv/bin/pytest services/api/tests/integration/test_postgres_s6_manual_edits.py services/api/tests/integration/test_postgres_s6_edit_runs.py services/api/tests/integration/test_postgres_s6_edit_human_loop.py services/api/tests/integration/test_generate_dispatcher.py services/api/tests/integration/test_ai_run_sse.py -q`  
Run: `npm run test:web`  
Run: `npm run build:web`  
Run: `npm run generate:openapi`  
Run: `git diff --exit-code -- apps/web/src/generated/api-schema.d.ts`  
Run: `.venv/bin/ruff check . --exclude '._*'`  
Run: `.venv/bin/mypy`  
Run: `git diff --check`

- [ ] **Step 8: Run one no-key Compose/browser stage acceptance**

Run the existing Compose profile with `DEEPSEEK_API_KEY` absent, then:

```bash
.venv/bin/python scripts/run_s6_deterministic_smoke.py
npm run smoke:s6:browser
```

Expected facts: manual edit and Undo each create one immutable Revision; AI L0 creates one Revision; AI L2 creates one Preview and no Revision before approval; approval creates exactly one Revision; reject/cancel leaves Branch unchanged; restart/duplicate delivery does not change counts; provider requests/tokens remain `0/0`.

- [ ] **Step 9: Update current-fact documentation**

Only after Step 8 passes:

- mark S6 complete and S7 active in `AGENTS.md`, `IMPLEMENTATION_STATUS.md`, and `NEXT_DEVELOPMENT_ROADMAP.md`;
- append dated Task/runtime evidence and honest limitations to `TECH_EVOLUTION.md`;
- leave external catalog search, professional DAW features, exhaustive failure matrices, load/P95, and public-release hardening in S7/deferred scope;
- do not modify `PROJECT_GUIDE.md` unless the approved final contract itself changed.

- [ ] **Step 10: Run the scoped stage-end storage hygiene gate**

Freeze the keep set, inventory exact project-owned images/caches/test outputs, and remove only exact obsolete/rebuildable project artifacts. Do not use global Docker prune, delete database volumes, or touch other worktrees/projects. Re-run readiness plus the no-rebuild S6 smoke after cleanup and append before/after evidence to `TECH_EVOLUTION.md`.

- [ ] **Step 11: Commit the S6 stage checkpoint**

```bash
git add AGENTS.md package.json scripts services/api/tests/eval tests docs/IMPLEMENTATION_STATUS.md docs/TECH_EVOLUTION.md docs/NEXT_DEVELOPMENT_ROADMAP.md apps/web/src/generated/api-schema.d.ts
git commit -m "feat: complete S6 selection editing workflow"
```

## Plan completion gate

Before merging S6:

1. Confirm `PROJECT_GUIDE.md` has no unintended diff from the task-start Git blob.
2. Confirm the working tree contains no Secrets, `.env`, user audio, Artifact bytes, caches, AppleDouble Python/migration sidecars, or incidental dependency symlinks.
3. Run one bounded independent review of the complete S6 diff. Allow at most one repair re-review under Portfolio Engineering Mode; Critical and current-path Important findings block.
4. Merge only after all eight Task checkpoints and the stage gate pass. Push only when explicitly requested or when continuing the previously authorized GitHub workflow.
