# Motif Forge Agent Graph 规范

> 状态：首版 Graph 合同
> Graph 名称：`MotifForgeGraph`
> 基础模型：`deepseek-v4-flash`

## 1. Graph 的边界

系统编译一个版本化 Parent Graph 拓扑，但每个用户任务创建新的有限 `run_id + thread_id`：

- `import`
- `generate`
- `edit`
- `export`
- `artifact_rehydrate`：仅由显式 Artifact rehydrate API 创建，不通过 AI Run 接口伪造
- `recovery` 不是独立用户类型，而是上述 Run 的统一错误路径

项目状态通过 `project_id + base_revision_id` 载入，不依赖上一个 Run 的 checkpoint。Run 之间用 `parent_run_id` 和 Revision lineage 关联。

一个 Run 内，策略子图、Segment fan-out、Worker 等待、HITL 与异常处理都属于同一 thread；不能另起隐藏 Graph 处理失败或审批。

## 2. Graph State

State 只保存 JSON 可序列化的小对象和引用。

### 2.1 State 分组

| 分组 | 字段 |
|---|---|
| `identity` | run/project/thread/parent_run、actor、graph/state schema versions |
| `request` | run_type、intent、selection、locked ranges、brief refs |
| `project_context` | active/target branch、base/head revision refs、IR summary、import/analysis refs |
| `strategy` | primary strategy、secondary influences、style/knowledge refs |
| `composition` | plan ref/status、motif/harmony summaries |
| `work` | candidates、segments、jobs、artifact/analysis refs、artifact lifecycle summaries |
| `change` | predicted/actual impact、proposal/candidate snapshot/preview refs、non-target hash |
| `approval` | pending interrupt、decision、checkpoint ref |
| `control` | phase、next route、cancel flag、partial outcome、last successful node |
| `budget` | profile ref、usage ledger ref、remaining model/render/deadline/storage budget |
| `failure` | current error ref、retry decision、attempt keys、unresolved issue refs |
| `outcome` | selected candidate、committed revision、export refs、terminal status |

完整 `ArrangementIR`、WAV、波形、文件系统路径、长知识文本、完整 Event history、完整 model messages 不进入 Graph State。Artifact lifecycle 只保存 `artifact_id + state + rehydratable + metadata ref`，物理位置只由 Artifact Repository 解析。

当前已实现的最小计划纵切使用 `motif-forge-plan.v3 / motif-forge-plan-state.v3`：State 只保存 Brief/Plan JSON、小型 validation issue codes、provider/version、累计 usage、`max_model_calls/max_total_tokens`、repair 次数、审批和安全 ErrorEnvelope。主路径为 `ValidateBrief → CompositionPlanner → ValidatePlan → [最多一次 RepairPlan → ValidatePlan] → PlanApproval`；每个失败出口进入统一 `ErrorRouter`，再确定性路由到 repair、approval-required fallback、人工决定或终止。这是完整 Parent Graph 的先行纵切，不另建第二套生产编排器。

截至 2026-08-12，计划纵切仍只由测试直接编译，生产 API lifespan 实际只装载含 Import/Recovery 的 Parent Graph。该状态属于明确的临时技术债，不代表允许两套长期生产 Graph。`NEXT_DEVELOPMENT_ROADMAP.md` 的 S2 必须通过显式 ParentState ↔ PlanState Adapter 将这些节点并入 `generate` 子图；在此之前禁止复制 Planner 节点或创建第三个编排入口。

DeepSeek Adapter 会在 provider JSON 已可解析但不满足严格 Schema 时内部执行最多一次完整对象修复，并合并两次 usage/model-call 计数；仅当 Graph 传入的剩余 model-call budget 至少为 2 时启用该修复。Graph 对任何 Planner 返回的领域无效 Plan 再执行显式、最多一次的 `RepairPlan` Edge。二者不是叠加两轮：原生 Adapter 成功修复后 Graph 只看到合法 Plan；Adapter 失败则交给 `ErrorRouter`。Thinking tool-call 续轮时，Adapter 仅在本次调用的局部消息缓冲中回传 DeepSeek 要求的 `reasoning_content`，不会把它写入 Graph State、Trace 或公共结果；工具名、参数 Schema 和轮数均受 allowlist/预算限制。

PostgreSQL Trace/Span/Usage Ledger 已由 Alembic `20260811_0003` 落地，使用 provider `operation_id` 幂等去重；v3 State counter 仍只是 planning-only 硬停止器和即时路由输入，不是成本事实源。后续 Parent Graph 的 BudgetGate 必须读取 Ledger 投影，不得把 State 累加器扩展成计费事实。

### 2.2 Reducer 规则

| Channel | Reducer | 冲突规则 |
|---|---|---|
| `work.candidates` | 按 `candidate_id` 合并 map | 同 ID 不同 hash → error |
| `work.segments` | 按 `segment_id` 合并 map | 状态只能按状态机前进 |
| `work.jobs` | 按 `job_id` 合并 map | 重复完成按 event ID 去重 |
| `failure.unresolved_issue_refs` | 稳定 ID 去重集合 | 严重度可升不可降 |
| `approval` | 单值覆盖 | 仅当前 checkpoint 可写 |
| `control` | 单值覆盖 | 节点只能更新声明字段 |
| `budget` | 从 Usage Ledger 投影 | 禁止简单整数累加导致 replay 重复计费 |

模型调用和 Worker 使用量写入 PostgreSQL Usage Ledger，键为稳定 `operation_id`。BudgetGate 读取去重后的投影；不得依赖 `operator.add` 在 checkpoint 重放中累计费用。

## 3. NodeResult

每个 Node 返回：

- `status = success | partial | waiting | failed | cancelled`
- `state_update`
- `event_specs[]`
- `artifact_refs[]`
- `warnings[]`
- 可选 `error_ref`

Node 不返回任意异常文本控制 Edge。未捕获异常由 Node boundary 转成 `ErrorEnvelope` 并进入统一 Error Router。

## 4. 顶层拓扑

```mermaid
flowchart TD
    START --> LOAD["LoadProjectContext"]
    LOAD --> POLICY["EntryPolicyGate"]
    POLICY --> STORAGE["StoragePressureGate"]
    STORAGE --> ROUTE{"RunTypeRouter"}

    ROUTE -->|import| IMPORT["ImportSubgraph"]
    ROUTE -->|generate| GENERATE["GenerationSubgraph"]
    ROUTE -->|edit| EDIT["EditSubgraph"]
    ROUTE -->|export| EXPORT["ExportSubgraph"]
    ROUTE -->|artifact_rehydrate| REHYDRATE["ArtifactRehydrateSubgraph"]

    IMPORT --> FINAL["FinalizeRun"]
    GENERATE --> FINAL
    EDIT --> FINAL
    EXPORT --> FINAL
    REHYDRATE --> FINAL

    LOAD -. error .-> ERR["ErrorRouter"]
    POLICY -. error .-> ERR
    STORAGE -. error .-> ERR
    IMPORT -. error .-> ERR
    GENERATE -. error .-> ERR
    EDIT -. error .-> ERR
    EXPORT -. error .-> ERR
    REHYDRATE -. error .-> ERR
    ERR -->|retry failed node| ROUTE_BACK["ResumeFromCheckpoint"]
    ERR -->|repair| REPAIR["Domain/Strategy Repair"]
    ERR -->|fallback| FALLBACK["Graceful Partial Result"]
    ERR -->|human| INTERRUPT["Interrupt"]
    ERR -->|terminal| FINAL
```

顶层 Router 只根据已验证 `run_type` 路由，不调用模型。

### 4.1 StoragePressureGate 合同

`StoragePressureGate` 是 Parent Graph 内的确定性规则节点，不是第二个清理 Graph，也不调用 DeepSeek。Entry 时做预检；Candidate fan-out、Preview render、time-stretch、rehydrate 和 Export render 前以同一 policy 再评估预计增量，防止长 Run 使用过期容量事实。

输入必须来自 Application/Repository 的已验证摘要：

- Artifact Root health（`ready | disconnected | read_only | corrupt`）与挂载身份是否匹配。
- `free_bytes`、`estimated_output_bytes`、全局/项目配额和临时区占用。
- 目标 Revision/Candidate/Job 的受保护 Artifact refs。
- 可回收 Artifact 的状态、大小、last access、rehydratable 和 retention class。
- versioned `storage_policy_ref`；绝不包含物理路径。

节点只能输出 `proceed | gc_then_retry | rehydrate_then_resume | wait_for_storage | fail`：不读取或写入 Artifact 的操作即使 Root 断开也可以 `proceed`；GC 仅由 Application use case 删除 Allowlist 中可重建且未受保护的二进制，完成后以原 operation ID 重算一次；`evicted` 依赖必须通过显式 Rehydrate Job 恢复；外置盘断开/read-only 且当前操作需要 Artifact I/O 时进入同 thread 的可恢复 Interrupt；`missing` 或重算后仍不足进入失败/partial 路径。禁止自动改写 Artifact Root 到内置盘，禁止把容量判断交给模型。

稳定错误码为 `ARTIFACT_ROOT_UNAVAILABLE`、`STORAGE_QUOTA_EXCEEDED`、`ARTIFACT_EVICTED`、`ARTIFACT_REHYDRATING`、`ARTIFACT_MISSING`、`ARTIFACT_REHYDRATION_FAILED`。Node span 和持久事件记录 policy version、health 枚举、free/estimated/reclaimed bytes、quota scope、保护/回收数量、route 和 operation ID，不记录路径。Eval 指标至少包含条件 Edge 准确率、受保护 Artifact 误删率（目标 0）、重建成功率、断盘后同 checkpoint 恢复率、回收后完整导出成功率和新增 P95 延迟。

## 5. ImportSubgraph

```text
ValidateUploadRefs
→ ImportPolicyNode
→ EnqueueIngestJob
→ WaitForJobEvent
→ IngestResultGate
→ AnalyzeConfidenceGate
→ [low confidence] AnalysisConfirmationInterrupt
→ AlignmentDecision
→ [needed] EnqueueTimeStretchJob
→ WaitForJobEvent
→ TimeStretchQualityGate
→ BuildImportCommands
→ CommitImportRevision
```

- Upload、格式、大小、许可、置信度、time-stretch quality 都由规则节点决定。
- DeepSeek 不参与解码、BPM/key 数值判断或保持音高算法。
- Worker 失败只恢复对应 Job，不重做成功的 Upload/Ingest Artifact。

当前 `motif-forge-parent.v1` 已将 Import 的分析与自动对齐主路径落地：
`ValidateRequest → EnqueueInitialMediaJob → WaitForJobEvent → LoadImportAnalysis → AnalysisConfidencePolicy → [low confidence] AnalysisConfirmationInterrupt → [needed] EnqueueTimeStretchJob → WaitForJobEvent → SelectTimeStretchArtifact → MaterializeImportRevision`。轻量 `import-analysis.v1` 在 Worker 内对标准化 PCM 的有界前 120 秒计算 BPM/key 与置信度；`import-analysis-policy.v1` 以 BPM 0.65、key 0.25 为基线阈值，低于任一阈值即在同一 checkpoint 等待用户 `confirm | override | skip_alignment | cancel`。key 阈值较低是为了匹配当前保守基线的分数尺度，并不表示同等的现实准确率，必须由后续 Eval 重新校准。高可信且与项目 BPM 差异超过 1% 时，同一个 PostgreSQL Run 原子追加第二个 `time_stretch` Job；它不创建隐藏 Run 或 Graph，且始终 `preserve_pitch=true`。最终 L1 Revision 的 AudioClip 引用实际选中的 Artifact；执行过对齐时还保存原 normalized Artifact、source/target BPM、ratio 和 engine version，失败则不提交 Revision。DeepSeek 不参与这些数值或基础设施判断。

## 6. GenerationSubgraph

```mermaid
flowchart TD
    B["ValidateBrief"] --> K["RetrieveStyleKnowledge"]
    K --> S["MusicStrategyRouter"]
    S --> P["CompositionPlanner"]
    P --> PV["ValidatePlan"]
    PV -->|repairable| PR["PlanRepair"]
    PR --> PV
    PV -->|needs user| PA["PlanApproval Interrupt"]
    PA --> F["Candidate Fan-out"]
    F --> C1["Candidate A Strategy Subgraph"]
    F --> C2["Candidate B Strategy Subgraph"]
    C1 --> AGG["Candidate Aggregate"]
    C2 --> AGG
    AGG --> R["Request Canonical Preview Jobs"]
    R --> W["Wait For Job Events"]
    W --> V["Deterministic + Audio Validation"]
    V --> CRITIC["EvidenceCritic"]
    CRITIC --> Q{"QualityBudgetGate"}
    Q -->|improving + repairable| REPAIR["Bounded Repair"]
    REPAIR --> R
    Q -->|ready| AB["A/B Approval Interrupt"]
    Q -->|budget exhausted| PARTIAL["Best Playable Partial"]
    AB --> MAT["Materialize Approved Candidate"]
    MAT --> COMMIT["Commit New Revision + Advance Branch Head"]
```

`Candidate Aggregate` 必须先持久化每个候选的完整 Candidate Snapshot/IR、seed、依赖 checksum 和渲染配方；`Request Canonical Preview Jobs` 只生成完整时长的压缩试听，不预生成无损 Master 或全量 Stem。试听可按生命周期回收并 rehydrate，候选批准始终从不可变 Snapshot 物化；最终无损 Master/Stem 在 ExportSubgraph 中按需产生。

### 6.1 Candidate/Segment 并发

- 两个 Candidate 使用不同 `candidate_id`、seed 和局部 state。
- Candidate 内按 Section/Track 建立 Segment DAG；依赖骨架先于旋律/纹理。
- fan-in 结果按稳定 ID 排序后进入 reducer，不能使用返回顺序。
- 结构生成可以并发；完整 Chromium 渲染默认并发 1，由 Render Policy 决定。

## 7. 策略子图

四个子图共享 `StrategyInput/StrategyResult`，但节点和 Loop 不同。

| 策略 | 主要 Node | 改善指标 |
|---|---|---|
| Synth Ambient | Palette → Envelope/Filter → Texture → Spatial | 密度、频谱、尾音、削波 |
| Minimal Electronic | Groove → Drum/Bass Lock → Energy → Transition | onset grid、低频冲突、段落对比 |
| Classical Chamber | Form → Harmony → Voice Assignment → Phrase | voice leading、终止式、音域、可演奏性 |
| Jazz | Changes → Voicing → Rhythm Section → Melody/Improvisation | guide tone、tension、swing、动机连续性 |

`MusicStrategyRouter` 可以使用 DeepSeek thinking 模式理解混合风格，但输出必须是 Allowlist strategy ID。规则验证不允许模型生成任意节点名或 Edge。

## 8. EditSubgraph

```text
ParseEditIntent
→ PredictChangeImpact
→ EditPlanner
→ simulate_edit_patch
→ ValidatePatchAndLocks
→ ComputeActualDiffAndImpact
→ route max(predicted, actual, policy)
   ├─ L0/L1 → CommitRevision → RequestAffectedRangeRender
   └─ L2/L3 → PersistCandidateSnapshot → CreatePreviewCandidate
              → RequestPreviewRender → PreviewApprovalInterrupt
                    ├─ approve → MaterializeCandidateAsRevision → AdvanceTargetBranchHead
                    ├─ reject → RejectPreviewCandidate
                    └─ branch → CreateBranch → MaterializeCandidateAsRevision
```

`simulate_edit_patch` 是纯函数/只读 Tool。PreviewCandidate 不是 Revision；批准时从其不可变 Candidate Snapshot 创建新的 Revision。`CommitRevision`、`MaterializeCandidateAsRevision`、`RequestPreviewRender` 和审批 Node 不在模型工具列表中。

## 9. ExportSubgraph

```text
PinRequestedRevision
→ ValidateExportAssetsAndLicenses
→ StoragePressureGate
→ [evicted dependency] EnqueueRehydrateJobs → WaitForJobEvents
→ BuildAudioGraphSpec
→ EnqueueRequestedMaster/Stem Render Jobs
→ WaitForJobEvents
→ RenderQualityGate
→ EnqueueTranscode/Manifest Jobs
→ ExportCompletenessGate
→ FinalizeExport
```

导出期间固定 Revision；active branch 或任意 Branch head 变化不会改变正在导出的内容。

Master WAV、用户选择的 Stem、MIDI 和 manifest 都是完整产出能力；Lean Profile 只把无损 Master/Stem 改为按需生成。外置 Artifact Root 断开时 Run 在原 checkpoint 等待，恢复后重新通过 StoragePressureGate，不在内置盘建立隐式副本。

## 10. Worker 等待与恢复

显式 `POST /artifacts/{artifact_id}/rehydrate` 创建同一 Parent Graph 的有限 `artifact_rehydrate` Run：

```text
LoadArtifactMetadata
→ ValidateRehydrationRecipeAndDependencies
→ StoragePressureGate
→ EnqueueRehydrateJob
→ WaitForJobEvent
→ VerifyChecksumAndMediaContract
→ MarkArtifactAvailable
```

目标 Artifact 的 `evicted` 状态是本 Run 的合法输入，不被误判为需要递归创建另一个 rehydrate Run；其依赖若 `evicted`，按依赖 DAG 和稳定 Artifact ID 顺序恢复。`missing` 或不可验证的 recipe 不调用 Worker。该流程仍使用当前 `run_id + thread_id`、checkpoint、事件与统一 Error Router，没有第二套恢复编排。

该有限分支按持久 recipe 类型路由执行器，而不是为 waveform/analysis 新建第二套 Graph：time-stretch 恢复 Audio Artifact；analysis recipe 恢复一个指定 Profile 的 Feature Artifact。两者使用相同 `LoadArtifactMetadata → StoragePressureGate → EnqueueRehydrateJob → WaitForJobEvent` 拓扑、同一 Artifact ID 和相同 checksum 验证。Graph State 只保存目标 ID/profile/ref，不保存 Feature JSON payload。

Graph 不在节点中轮询长 Job：

1. `Enqueue*Job` 通过 Application Service 原子写 Job + Outbox。
2. Node 保存 `job_id` 后进入可恢复等待状态并结束当前执行。
3. Worker 写持久 `job.completed/failed` 事件。
4. Resume Dispatcher 对事件执行 inbox 去重，读取 Run 当前 checkpoint。
5. 以同一个 `thread_id` 和 `job_event_ref` 恢复 Graph。
6. `IngestJobEvent` 校验 job/run/checkpoint 匹配，再路由下一节点。

迟到事件、重复事件或已取消 Run 的事件只更新审计，不重新推进 Graph。

当前代码已建立 `motif-forge-parent.v1` 的首个 Import/Arrangement 分支：
`ValidateTimeStretchRequest → EnqueueTimeStretchJob → WaitForJobEvent →
ValidatePersistedArtifactRef → terminal`。它复用同一个 PostgreSQL checkpoint 和
`Command(resume=worker-resume.v1)`，不创建第二套 Worker Graph；`run_id + thread_id + job_id`
必须同时匹配。Resume payload 额外携带 `run_type` 与 `resume_event_id`，专用 Dispatcher 只领取
`parent.*` Run，先检查 checkpoint 中的 `last_resume_event_id`，同一事件重放直接确认而不重复推进。
当前验证止于持久 Artifact ref/UUID 合同；bytes/checksum、codec、duration、pitch 与 lineage 的完整
`IngestJobEvent` 校验，以及 CompositionPlan/Import/Arrangement/Edit/Export 全部分支汇入该 Parent
Graph，仍按后续纵切完成。

## 11. DeepSeek Node 合同

| Node | 模式 | 输出 | 工具 |
|---|---|---|---|
| Intent/简单编辑解析 | non-thinking | `EditIntent` | 无或只读 catalog |
| MusicStrategyRouter | thinking high | `StrategySelection` | 只读 style metadata |
| CompositionPlanner | thinking high | `CompositionPlan` | `search_style_knowledge` |
| ArrangementPlanner | thinking high | `PatternSpec[]/SynthPatchSpec[]` | 只读 catalog + 确定性 composer tools |
| RepairPlanner | thinking high/受限 | `EditPatchProposal` | `simulate_edit_patch` 前置工具 |
| EvidenceCritic | thinking high | `Critique` | 只读 analysis/version evidence |
| 用户摘要 | non-thinking | 短结构化摘要 | 无 |

共同规则：

- 显式指定 `deepseek-v4-flash` 和 thinking 模式。
- JSON Output + Pydantic 二次校验；只接受 `finish_reason=stop` 的最终对象。
- Tool turn 必须在 Provider Adapter 内完整保存并回传 `reasoning_content`；UI、普通 log、trace 不记录该内容。
- 每个 Node 固定 prompt/schema/toolset/max output/timeout/budget version。
- `length` 结果丢弃并缩小 Segment；不得拼接半截 JSON。
- HITL 只能发生在 Provider Turn 完成后。

## 12. Agent Tool Allowlist

### 12.1 只读/纯函数工具

- `search_style_knowledge`
- `search_sound_catalog`
- `validate_synth_patch`
- `realize_chords`
- `generate_motif`：确定性、需要 seed
- `voice_lead`
- `compile_pattern`
- `simulate_edit_patch`
- `analyze_audio_summary`
- `compare_versions`

### 12.2 Graph/Application 专用命令

- `commit_revision`
- `persist_candidate_snapshot`
- `create_preview_candidate`
- `materialize_candidate`
- `set_sections/set_markers/set_project_key`
- `request_preview_render`
- `enqueue_worker_job`
- `schedule_retry`
- `resume_run`
- `approve/reject_preview_candidate`
- `download_external_asset`

这些命令不出现在 DeepSeek Tool Schema 中。

## 13. Error Router 与重试所有权

| 错误 | 所有者 | 路由 |
|---|---|---|
| DeepSeek connect/read timeout、429、5xx | Provider Client | bounded backoff，最多策略次数 |
| DeepSeek schema/length | Graph | 一次 repair 或缩小 Segment |
| 401/402/403 | Human | interrupt 修复配置 |
| Domain validation | Domain/Strategy Repair | 结构化 issue，不做 HTTP retry |
| Celery process crash | Celery/Job Reconciler | 同 idempotency key 重投 |
| Artifact checksum/codec/license | Rule/Human | 隔离、替代或终止 |
| Artifact evicted | Graph/Application | 显式 rehydrate Job，完成后恢复原 checkpoint |
| Artifact missing/rehydration failed | Rule/Human | 替代来源、重建失败或 partial/终止 |
| Artifact Root 断开/read-only | Graph/Human | `wait_for_storage` Interrupt；恢复后重检 |
| Storage quota exceeded | Graph/Rule | 有界 GC 后重算；仍不足则人工/partial |
| Revision conflict | User/Application | 409，重新模拟；不自动覆盖 |
| Budget exhausted | Graph | 保留最佳可播放结果 |

同一错误不能同时由 Provider、Celery 和 Graph 各重试 3 次。`ErrorEnvelope.retry_owner` 必须唯一。

## 14. Checkpoint 与 HITL

必须 checkpoint：

- Plan Approval 前。
- Candidate/Segment fan-out 前。
- Job 入队后、等待事件前。
- StoragePressureGate 进入 GC、rehydrate 或 `wait_for_storage` 前。
- 每批 Segment 聚合后。
- 每轮 Critic/Repair 后。
- A/B、Preview、低置信度分析和超预算审批前。
- 最终提交/导出前。

Interrupt payload 只含 JSON 摘要、引用、选项、截止时间；不含音频、完整 IR 或 Secret。Resume 必须携带 `interrupt_id + expected_checkpoint_id`。

## 15. 终止条件

Run 在以下条件之一结束：

- 用户批准并完成提交/导出。
- 用户取消或拒绝且不保留分支。
- 达到模型、token、成本、render seconds、deadline 或 Revision 预算。
- 连续两轮可比较指标无改善。
- 资源、许可、Schema 迁移或安全问题不可恢复。

LangGraph recursion limit 只是最后保护，不能替代业务终止条件。

## 16. Graph 版本兼容

- Run 创建时固定 `graph_topology_version` 和 `state_schema_version`。
- 部署新 Graph 时列出 in-flight Run；重命名/删除 checkpoint 下一节点前必须提供迁移。
- Resume Dispatcher 发现版本不兼容时进入 `GRAPH_VERSION_INCOMPATIBLE` 人工/终止路径。
- 新版本不得静默重放已产生外部副作用的 Node。

## 17. Graph 测试矩阵

- 每个条件 Edge 的路由单测。
- Candidate/Segment reducer 顺序独立性。
- checkpoint/resume 与 duplicate job event。
- HITL 重复批准、过期 checkpoint、Branch head/Revision conflict。
- Provider timeout、length、坏 JSON、missing reasoning_content。
- Worker crash、部分候选成功、取消、预算耗尽。
- StoragePressureGate 五种路由、外置盘断开/恢复、四态 Artifact 和幂等 rehydrate。
- 自动 GC 的受保护 Artifact 误删率为 0；回收试听后仍能重建并按需导出完整无损 Master/Stem。
- L0/L1 自动提交与 L2/L3 漏拦截目标为 0。
- Graph 版本升级的 in-flight fixture。
