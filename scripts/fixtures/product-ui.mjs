/** Illustrative, local-only data for UI smoke/screenshots. Never used by the application. */
export const projectId = "11111111-1111-4111-8111-111111111111";
export const revisionId = "22222222-2222-4222-8222-222222222222";
export const runId = "33333333-3333-4333-8333-333333333333";
const branchId = "44444444-4444-4444-8444-444444444444";
const artifactId = "55555555-5555-4555-8555-555555555555";
const time = "2026-09-24T03:00:00Z";
export const project = { project_id: projectId, name: "雨后的漫步", status: "active", updated_at: time, active_branch_id: branchId, head_revision_id: revisionId, revisions: [], runs: [], recoverable_run: null, storage_root_status: "ready" };
export const projects = ["雨后的漫步", "玻璃温室 / Glasshouse", "夜行列车"].map((name, index) => ({ ...project, project_id: `11111111-1111-4111-8111-11111111111${index + 1}`, name, latest_run: { run_id: runId, status: index === 1 ? "waiting_approval" : "succeeded", updated_at: time }, has_playable_revision: index !== 1 }));
const sections = [
  { section_id: "opening", name: "序 · 雨声渐远", start_bar: 0, end_bar: 8, function: "用舒展的和声铺开空间，让旋律缓缓进入。", energy: .25 },
  { section_id: "development", name: "行 · 城市苏醒", start_bar: 8, end_bar: 24, function: "加入轻盈脉冲，重复并发展主要动机。", energy: .65 },
  { section_id: "resolution", name: "归 · 留下余韵", start_bar: 24, end_bar: 32, function: "逐渐减少声部，让尾音自然收束。", energy: .3 },
];
const instruments = ["Warm Pad", "Soft Lead", "Deep Bass", "Gentle Pulse"];
export const plan = {
  plan_id: "66666666-6666-4666-8666-666666666666", content_hash: "a".repeat(64), hash_version: "composition-plan-hash.lossless-v2", provider: "deterministic", model: "fallback", fallback_reason: "No provider key — illustrative demo",
  plan: { schema_version: "composition-plan.v1", genre: "synth_ambient", era_influences: ["modern ambient"], purpose: "城市雨后漫步的短片配乐", moods: ["温暖", "轻盈", "好奇"], duration_bars: 32, bpm: 84, meter: "4/4", key: { tonic: "D", mode: "dorian" }, sections,
    instrumentation: instruments.map((name, index) => ({ instrument_id: `instrument-${index}`, name, role: ["和声底色", "旋律动机", "低频支撑", "节奏推进"][index], pitch_range: "48–84", entry_section_id: "opening", exit_section_id: "resolution" })),
    harmonic_language: "开放五度与 D 多利亚色彩，保留明亮而安静的空间。", rhythmic_language: "稀疏的八分音符脉冲，从轻到重，再回到平静。", texture: "柔和铺底、短句旋律和克制的低频，留出叙事的呼吸。",
    hard_constraints: ["避免削波"], soft_preferences: ["为画面留白"], negative_constraints: ["无突然的强烈转折"], knowledge_references: [{ reference_id: "style:synth-ambient:v1", summary: "缓慢的音色变化与克制的声部密度，保持段落之间的连续感。", confidence: .9 }], confidence: .88 },
};
export const candidates = ["a", "b"].map((label, index) => ({ label, candidate_id: `candidate-${label}`, candidate_snapshot_id: `snapshot-${label}`, candidate_content_hash: label.repeat(64), preview_id: `preview-${label}`, preview_artifact_id: artifactId, preview_availability: "available", parent_candidate_snapshot_id: null, repair_status: index ? "improved" : "not_requested" }));
export const critique = { schema_version: "candidate-critique.v1", evidence: [], findings: [], assessments: candidates.map((c, index) => ({ candidate_id: c.candidate_id, label: c.label, score: index ? 84 : 78, evidence_refs: [] })), repair_proposal: null, recommended_candidate_id: "candidate-b", rationale: "B 的段落过渡更平稳，旋律与和声的衔接更连贯。规则评估不替代你的听感。" };
export function run(mode = "approval") {
  const done = mode === "done";
  return { run_id: runId, parent_run_id: null, project_id: projectId, branch_id: branchId, base_revision_id: revisionId, thread_id: "demo-generate", status: done ? "succeeded" : mode === "approval" ? "waiting_approval" : "waiting_worker", version: 3, pending_action: done ? null : mode === "approval" ? "approve_plan" : "select_candidate", pending_plan_id: plan.plan_id, pending_plan_hash: plan.content_hash, submitted_model_requests: 0, max_model_requests: 1, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, model_usage_status: "known", cost_status: "known", cost_amount_microusd: 0, cost_pricing_version: null, revision_id: done ? revisionId : null, bundle_id: done ? "demo-bundle" : null, fallback_reason: plan.fallback_reason, error_code: null, plan, candidates: mode === "candidates" ? candidates : [], critique: mode === "candidates" ? critique : null, selected_candidate_id: null, selected_preview_id: null, progress: { phase: done ? "succeeded" : mode === "approval" ? "waiting_approval" : "waiting_candidate_selection", completed_export_steps: done ? ["master", "stem:pad", "stem:lead", "stem:bass", "stem:pulse", "mp3", "bundle"] : [], total_export_steps: 7, latest_event_sequence: done ? 32 : 8, error_code: null } };
}
export const studio = {
  project_id: projectId, revision_id: revisionId, parent_revision_id: null, source_run_id: runId, reason_code: "generated", author_kind: "agent", created_by: "parent-graph", created_at: time, bundle_id: "demo-bundle",
  delivery_assets: [{ artifact_id: artifactId, availability: "available", quality_profile: "delivery-mp3.v1", media_type: "audio/mpeg", byte_size: 1200000, duration_milliseconds: 91429 }],
  arrangement_ir: { schema_version: "arrangement-ir.v1", project_id: projectId, ppq: 480, sample_rate: 48000, tempo_map: [{ tick: 0, bpm: 84 }], time_signature_map: [{ tick: 0, numerator: 4, denominator: 4 }], key_map: [], markers: [], provenance: [],
    sections: sections.map((s) => ({ section_id: s.section_id, label: s.name, start_tick: s.start_bar * 1920, end_tick: s.end_bar * 1920, energy: s.energy, function: s.function })),
    tracks: instruments.map((name, index) => ({ track_id: `track-${index}`, name, track_type: "instrument", role: ["harmony", "melody", "bass", "rhythm"][index], instrument_ref: "warm-pad.v1", gain_db: [-6, -4, -8, -12][index], pan: 0, mute: false, solo: false, locked_ranges: [], clips: Array.from({ length: 8 }, (_, c) => ({ clip_id: `clip-${index}-${c}`, clip_type: "note", start_tick: c * 7680 + index * 480, duration_tick: 6720 - index * 480, loop: false, gain_db: 0, pan: 0, fade_in_tick: 0, fade_out_tick: 0, notes: Array.from({ length: 8 }, (_, n) => ({ note_id: `note-${index}-${c}-${n}`, pitch: [60, 64, 67, 69, 67, 64, 62, 60][n], start_tick: n * 240, duration_tick: 180, velocity: 80 })) })) })),
  },
};
export const exportData = { project_id: projectId, revision_id: revisionId, source_run_id: runId, status: "ready", error_code: null, bundle: { bundle_id: "demo-bundle", project_id: projectId, revision_id: revisionId, availability: "available", content_hash: "a".repeat(64), byte_size: 14000000, file_count: 9 },
  steps: ["master", "stem:pad", "stem:lead", "stem:bass", "stem:pulse", "mp3", "bundle"].map((step, index) => ({ step, job_id: `demo-job-${index}`, status: "succeeded", artifact_id: artifactId, error_code: null })),
  files: [["master", "master.wav", "audio/wav", 17554000], ["delivery", "composition.mp3", "audio/mpeg", 1200000], ["midi", "composition.mid", "audio/midi", 16400], ["project", "project.json", "application/json", 42100], ["stem", "warm-pad.wav", "audio/wav", 17554000], ["stem", "soft-lead.wav", "audio/wav", 17554000]].map(([category, filename, media_type, byte_size], index) => ({ file_id: `demo-file-${index}`, filename, category, media_type, byte_size, availability: "available", checksum: "b".repeat(64), content_url: `/api/v1/audio-artifacts/${artifactId}/content`, artifact_id: artifactId })) };
const groups = [
  ["planning", "理解与规划", [["校验生成请求", "ValidateRequest", "deterministic"], ["规划音乐方向", "PlanningSubgraph", "agent"]]],
  ["approval", "计划确认", [["等待你的确认", "PlanApproval", "human"]]],
  ["candidates", "候选生成", [["生成候选 A", "CreateCandidateBranch", "deterministic"], ["生成候选 B", "CreateCandidateBranch", "deterministic"], ["汇合候选", "CandidateFanIn", "deterministic"]]],
  ["critique", "评估与选择", [["比较候选证据", "Critic", "agent"], ["确认采用的方向", "CandidateSelection", "human"]]],
  ["export", "完整导出", [["推进完整导出", "EnqueueCompleteExportStep", "worker"], ["等待音频任务", "WaitForGenerateJobEvent", "worker"], ["完成整曲生成", "CompleteGenerate", "deterministic"]]],
];
export const graph = { schema_version: "run-graph-view.v1", run_id: runId, graph_version: "motif-forge-parent.v2", graph_kind: "generate", run_status: "succeeded", evidence_status: "available", current_phase_id: null,
  phases: groups.map(([id, label, nodes]) => ({ id, label, status: "completed", summary: `已确认 ${nodes.length} 个节点`, node_ids: nodes.map((_, i) => `${id}:${i}`), collapsed_by_default: false, iteration_count: id === "export" ? 7 : 1 })),
  nodes: groups.flatMap(([phase_id, , nodes]) => nodes.map(([label, technical_name, kind], index) => ({ id: `${phase_id}:${index}`, phase_id, label, technical_name, kind, evidence: phase_id === "candidates" && index < 2 ? "grouped_parallel" : "checkpoint_confirmed", status: "completed", occurred_at: time, iteration_count: phase_id === "export" ? 7 : 1, default_visible: true }))), edges: [], evidence_summary: { checkpoint_count: 44, task_count: 28, event_count: 32, human_decision_count: 2, job_count: 7, unmapped_task_count: 0, truncated: false, schema_compatible: true } };
export const inspection = {
  run: { run_id: runId, project_id: projectId, thread_id: "demo-generate", run_type: "generate", status: "succeeded", version: 5, revision_id: revisionId, bundle_id: "demo-bundle", error_code: null },
  versions: { graph_topology_version: "motif-forge-parent.v2", state_schema_version: "parent-state.v2" }, usage: { submitted_model_requests: 0, max_model_requests: 1, max_total_tokens: 12000, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, usage_status: "known", cost_status: "known", cost_amount_microusd: 0 },
  timeline: [1,2,3].map((sequence) => ({ sequence, event_type: "graph.progress", phase: sequence === 3 ? "succeeded" : "planning", created_at: time, summary: { phase: sequence === 3 ? "succeeded" : "planning" } })), timeline_truncated: false,
  decisions: [{ kind: "plan", decision: "approve", actor_id: "demo-creator", decided_at: time }], jobs: exportData.steps.map((s) => ({ job_id: s.job_id, job_type: s.step === "mp3" ? "transcode_mp3" : s.step === "bundle" ? "export_bundle" : "render_canonical", status: "succeeded", attempts: 1, error_code: null })), artifacts: [{ artifact_id: artifactId, source_job_id: "demo-job-0", quality_profile: "canonical-master.v1", availability: "available", byte_size: 17554000 }], recovery: { resume_events: 2, replay_events: 1, retry_events: 0, cancel_events: 0, terminal_outcome: "succeeded" },
};
