# Motif Forge 领域与 Revision 模型

> 状态：首版合同
> 权威实现：后端 Pydantic Domain Schema
> 时间坐标：PPQ tick，首版 `ppq = 480`

## 1. 事实源与对象分类

系统区分四类状态：

| 类型 | 权威位置 | 生命周期 | 示例 |
|---|---|---|---|
| 项目事实 | PostgreSQL Revision | 不可变、可分支 | ArrangementIR、命令、审批 |
| 流程状态 | LangGraph checkpoint | 单个有限 Run | phase、pending action、refs |
| 大型产物 | Artifact Store + DB metadata | 内容寻址、不可变 bytes、生命周期可治理 | WAV、MIDI、peaks、analysis |
| 页面运行时 | 浏览器内存 | 可丢弃、可重建 | selection、zoom、Tone nodes |

任何页面或 Graph 状态都必须能通过 `project_id + revision_id + artifact refs` 重建。

## 2. 标识与版本

所有实体使用服务端生成的 UUID；客户端临时对象使用 `client_temp_id`，提交成功后由映射表替换。每个公共对象包含：

- `schema_version`：对象结构版本。
- `created_at`、`created_by`。
- 可选 `source_run_id`、`trace_id`。

`ArrangementIR` canonical serialization 要求：字段排序稳定、集合按稳定 ID 排序、禁止 NaN/Infinity、浮点参数按 Schema 精度归一化。`content_hash` 基于 canonical bytes 计算。

## 3. ArrangementIR

### 3.1 顶层字段

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `schema_version` | string | IR 版本 |
| `project_id` | UUID | 所属项目 |
| `sample_rate` | enum | 首版默认 48000 |
| `ppq` | integer | 首版固定 480 |
| `tempo_map` | TempoPoint[] | 首版只允许 tick 0 一个全局 BPM |
| `time_signature_map` | MeterPoint[] | 首版 4/4，可选 3/4；只允许全局值 |
| `key_map` | KeyPoint[] | 可按 Section 变化，但必须有置信度/来源 |
| `sections` | Section[] | 不重叠、覆盖目标曲式范围 |
| `tracks` | Track[] | 首版最多 12 条用户轨；Master 不计入 |
| `markers` | Marker[] | 用户/系统标记 |
| `routing` | RoutingSpec | 首版固定 Track → Master，允许基础 send |
| `provenance` | ProvenanceRef[] | 模型、知识、素材与引擎引用 |

### 3.2 Track

| 字段 | 约束 |
|---|---|
| `track_id` | 稳定 UUID |
| `type` | `instrument | audio | bus` |
| `name` | 1–80 字符 |
| `role` | `melody | harmony | bass | rhythm | texture | fx | other` |
| `mute/solo` | boolean |
| `gain_db` | Render Policy 范围内 |
| `pan` | -1.0–1.0 |
| `eq` | 三段 EQ Schema |
| `effects` | Allowlist effect chain |
| `instrument_ref` | Instrument/Preset/Asset 引用 |
| `clips` | NoteClip/AudioClip 列表 |
| `locked_ranges` | Agent 不可修改的 tick 范围 |

Track 颜色属于 UI metadata，不影响渲染 hash；Track role、instrument 和效果影响渲染 hash。

### 3.3 NoteClip 与 NoteEvent

`NoteClip` 保存 `start_tick`、`duration_tick`、`loop`、`notes` 和 clip automation。`NoteEvent` 保存：

- `note_id`
- MIDI `pitch` 0–127
- `start_tick >= 0`
- `duration_tick > 0`
- `velocity` 1–127
- articulation enum
- 可选 `cents`，首版范围由 Instrument capability 决定

NoteEvent 使用 Clip 本地 tick；编译时转换为项目绝对 tick。跨 Clip 的 note 不允许隐式存在，必须拆分或使用 tie metadata。

### 3.4 AudioClip

统一 `AudioClip` 类型覆盖导入、样本与未来生成音频：

- `source_kind = imported | sample | generated`
- `artifact_id`
- `start_tick`、`duration_tick`
- `source_offset_seconds`、`source_duration_seconds`
- `source_bpm`、`target_bpm`、analysis confidence
- `transpose_semitones`
- `time_stretch_ref`，其中 `preserve_pitch=true`
- gain、pan、fade、loop
- provenance/license refs

`transpose_semitones`、`time_stretch_ref` 和 EQ 是独立字段，UI 不得复用同一控制器。

### 3.5 Automation

Automation Point 使用项目 tick，字段为 `parameter_path`、`tick`、`value`、`curve`。`parameter_path` 必须来自 AudioGraph 参数 Allowlist，禁止任意字符串访问运行时对象。

## 4. Revision、Branch 与 PreviewCandidate

### 4.1 不可变 Revision

`Revision` 只表示已经正式提交的项目历史版本。Revision 创建后不可改变状态、内容或父节点；待审批、拒绝和过期属于 `PreviewCandidate` 生命周期，不是 Revision 状态。

Revision 至少包含：

- `revision_id`、`project_id`、`parent_revision_id`
- `created_on_branch_id`
- 完整 `arrangement_ir` JSONB、`content_hash`
- `command_batch_id`
- `change_impact_predicted/actual`
- `author_kind = human | agent | system`
- `source_run_id`、`reason_code`
- `schema/policy/audio_engine` versions
- `created_at`

`Project` 保存 `active_branch_id`；每个 `ProjectBranch` 保存唯一权威的 `head_revision_id`。API 中的 `current_revision_id` 是“active branch 的 head”的读取投影，不作为第二个可独立更新的事实源。所有推进 Branch head 或从其派生候选的写入必须携带 `branch_id + base_revision_id`。

创建 Project 时，同一事务创建空的 Root Revision、`main` Branch，将其 head 指向 Root，并设置 `active_branch_id`；因此首版不存在“Project 已创建但没有可写 Base”的中间状态。Revision 的 `created_on_branch_id` 仅记录它最初在哪条 Branch 上提交；已有 Revision 可以作为多个 Branch 的共同基点。

### 4.2 CandidateSnapshot 与 PreviewCandidate

`CandidateSnapshot` 保存生成或模拟后的不可变候选内容，可同时服务 A/B Compare、音频 Preview、审批和最终物化：

- `candidate_snapshot_id`、`project_id`、`base_revision_id`、`source_run_id`、`candidate_id`
- 完整 `candidate_ir` JSONB、`candidate_content_hash`
- command batch/materialization metadata、structural diff、non-target preservation hash
- Graph/Prompt/Schema/Policy/knowledge/asset versions、created_at

CandidateSnapshot 创建后不允许原地修改；修复会创建新的 Snapshot，并通过 lineage 指向前一个候选。

`PreviewCandidate` 是待审创作结果，不是 Revision，包含：

- `preview_id`、`project_id`、`branch_id`、`base_revision_id`
- `candidate_snapshot_id` 与其 `candidate_content_hash`
- `command_batch_id` 或 `materialization_command_ref`
- structural diff、实际 ChangeImpact、non-target preservation hash
- Preview/分析 Artifact refs、依据与来源 Run
- `status = pending | approved | rejected | superseded | expired`
- `created_at`、`expires_at`、审批记录引用

只有 Preview 的生命周期元数据可以改变；CandidateSnapshot、hash、base 和 diff 创建后不可改。批准不会把 Preview “转成 Revision”，而是基于该不可变 CandidateSnapshot 创建一个新的 Revision。拒绝、过期或 Base 变化只更新 Preview 状态。

### 4.3 提交事务

`CommitRevisionUseCase` 的原子步骤：

1. 锁定目标 Branch 行并读取 `head_revision_id`；同时确认它属于 Project。
2. 校验请求的 `branch_id + base_revision_id` 与目标 Branch head。
3. 校验命令 Schema、权限、locked range、Asset/license 和预算。
4. 在内存中执行命令并得到候选 IR。
5. 计算 canonical hash、结构 diff 和实际 ChangeImpact。
6. L0/L1 插入新的不可变 Revision；L2/L3 先插入不可变 CandidateSnapshot，再创建引用它的 PreviewCandidate，不允许降级。
7. 插入 command batch、audit event、run event/outbox。
8. 若已提交 Revision，更新目标 Branch head；active branch 的 `current_revision_id` 读取投影随之变化。
9. 提交事务。

任何步骤失败都不产生半个 Revision。

### 4.4 Preview 批准

批准 Preview 时再次检查其 `branch_id + base_revision_id` 是否仍匹配目标 Branch head：

- 相同：从不可变 Candidate Snapshot 创建新的 Revision，并更新 Branch head；Preview 标记为 approved 并引用新 Revision。
- 不同：返回 `REVISION_CONFLICT`；不自动把创意 Patch rebase 到新版本。
- 用户可以要求重新模拟 Patch，产生新的 Preview。

“创建分支”审批会新建 `ProjectBranch`，以 Preview 的 Base 为基点创建新的 Revision 并把新 Branch head 指向它；默认不静默切换 `active_branch_id`，除非请求明确要求切换。

## 5. EditorCommand

公共 Command Envelope：

- `command_id`
- `command_type`
- `schema_version`
- `selection`
- `payload`
- `actor_kind`
- `client_sequence`

首版用户/Agent Proposal 可使用的编辑命令：

| 命令 | 关键前置条件 | 影响 |
|---|---|---|
| `add_track` | 轨数未超限、instrument/role 合法 | 至少 L1；AI 新增创意轨通常 L2 |
| `delete_track` | Track 存在且非 Master；引用/锁定合法 | 人工 L1；AI 通常 L2 |
| `add_clip` | Track 类型匹配、Asset 可用 | 范围相关 |
| `duplicate_clip` | Source Clip 存在、生成新稳定 ID | L0/L1 |
| `delete_clip` | Clip 存在、锁定范围合法 | L0/L1；主素材可升级 |
| `move_clip` | 目标 tick 合法 | 人工通常 L0 |
| `trim_clip` | 非破坏性、source range 合法 | L0 |
| `split_clip` | split tick 位于 Clip 内 | L0 |
| `set_clip_param` | gain/fade/loop/transpose Allowlist | L0/L1 |
| `time_stretch_clip` | AudioClip、Derived Artifact 已就绪 | L1；失败不改原 Clip |
| `set_track_param` | parameter Allowlist 和范围 | L0/L1 |
| `set_project_tempo` | 全局 BPM 合法；AudioClip 对齐计划明确 | 人工/AI 至少 L2 |
| `add_notes` | NoteClip、音域/范围合法 | L1/L2 |
| `update_notes` | note IDs 存在 | L1/L2 |
| `delete_notes` | 不越过锁定材料 | L1/L2 |
| `set_automation` | parameter path 合法 | L1/L2 |

批量复制、删除和移动仍展开为稳定有序的 Command Batch；不能用直接替换 `tracks/clips` 数组或隐藏字段绕过 diff、locked range 和 ChangeImpact。

### 5.1 Graph/Application 专用系统命令

以下命令不出现在 DeepSeek Tool Schema，也不允许普通浏览器命令批次直接提交：

| 命令 | 用途 | 约束 |
|---|---|---|
| `materialize_candidate` | 将已验证的完整生成候选提交为 Revision | 只能引用不可变 Candidate Snapshot ID + hash；仅用于空白生成或经过 L3 审批的完整候选 |
| `set_sections` | 写入或替换结构化 Section 计划 | 必须检查覆盖、重叠、小节边界与对应 Preview/审批范围 |
| `set_markers` | 物化系统/用户 Marker | 稳定 ID、tick 合法、不得隐式修改 Section |
| `set_project_key` | 写入全局或 Section KeyMap | 必须保留来源/置信度并触发和声兼容性校验 |

`materialize_candidate` 解决完整候选无法用少量局部命令可靠重放的问题，但不能成为任意“替换整个 IR”的后门。其 Command Log 必须记录 Candidate Snapshot 引用、content hash、Graph/Prompt/Schema/Policy 版本和审批引用；提交时重新验证 hash、Project、Branch、Base 与实际 ChangeImpact。

命令类型固定为 `materialize_candidate`，应用层处理入口命名为 `MaterializeCandidateRevisionUseCase`（代码函数可用 `materialize_candidate_revision`），避免与领域 Command Handler 混为同一函数。

## 6. EditPatchProposal

模型只生成 Proposal：

- `proposal_id`
- `branch_id`
- `base_revision_id`
- `selection`、`locked_ranges`
- `commands`
- `rationale`
- `evidence_refs`
- `expected_effect`
- `predicted_change_impact`
- `confidence`
- `prompt/model/schema versions`

`simulate_edit_patch` 接收 Proposal，在纯领域层执行并返回：

- candidate IR/content hash
- structural diff
- validation issues
- actual affected ranges/tracks
- non-target preservation hash
- actual ChangeImpact
- render request recommendation

该函数无数据库、文件、队列和音频副作用。

## 7. ChangeImpact

最终等级为 `max(predicted, actual, policy_escalation)`：

| 等级 | 自动提交 | 典型条件 |
|---|---:|---|
| L0 | 是 | 参数、移动、裁切、fade、mute/solo |
| L1 | 是 | 有界音符/量化/转调，小范围且不触及主结构 |
| L2 | 否 | 新增创意轨、重写旋律/和声、主要音色变化 |
| L3 | 否 | 从零生成、曲风/曲式/主题和大比例替换 |

规则输入包括影响 tick 比例、Track 比例、主旋律/和声/Section 修改、Style Pack 变化、锁定范围、渲染成本和资产许可证。模型只能建议，不能降低等级。

## 8. Asset 与 Artifact

`Asset` 是可被项目引用的音乐资源及其许可信息；`Artifact` 是不可变文件或大型结果。

### Asset

- catalog metadata、tags、instrument family、root note/BPM
- creator/source/license/version/attribution
- review status、usage allowlist
- 主 Artifact 引用和 preview Artifact 引用

### Artifact

- `artifact_id`、`sha256`、media type、byte size
- content-addressed storage key；API 永不返回服务器绝对路径
- producer/job/engine/schema versions
- parent Artifact lineage、recipe ref/hash 和全部输入 Artifact hash
- `lifecycle_class = durable | protected | rebuildable | ephemeral`
- `availability = available | evicted | missing | rehydrating`
- 与可用性独立的 `ingest_status = quarantine | ready | rejected | corrupt`

Artifact 领域对象分为两个独立合同：

- `AudioArtifact`：保存媒体 profile、container/codec、采样率、声道、时长、编码器与音频 lineage。
- `FeatureArtifact`：保存 `source_audio_artifact_id/hash`、`feature_profile/schema_version` 与紧凑 JSON bytes 的 checksum；首版仅有 waveform peaks 和导入分析。Feature 永远是 `rebuildable`，不得塞入 Revision、Redis 消息或 Graph State。

Import AudioArtifact 中的基础 analysis JSONB 暂时只是向后兼容的读取投影；独立 `FeatureArtifact` 才是 Studio 波形/分析生命周期、驱逐和恢复的事实源。

`lifecycle_class` 定义可以由策略升级，但不能为了自动清理而降级保护：

| 分类 | 内容 | 自动清理 |
|---|---|---|
| `protected` | 用户原始导入、当前 Revision 引用、待审批候选依赖的非可重建输入 | 禁止 |
| `durable` | 最终选中 Master、导出 manifest、license/provenance 和长期非可重建素材 | 禁止，除非用户显式删除/归档 |
| `rebuildable` | waveform/analysis、normalized/time-stretch 派生文件、旧 Revision 渲染缓存、按需 Stem | 只有 recipe 可验证且输入可用时才可驱逐 |
| `ephemeral` | Job scratch、中断残留、已拒绝/未选候选压缩试听 | 按 TTL 和 Job 终态清理 |

`available` 表示 bytes 存在且通过最近的存在性/checksum 校验；`evicted` 表示按策略删除 bytes，metadata、recipe 和 lineage 仍保留并可重建；`rehydrating` 表示幂等重建 Job 已创建，该 Artifact 在完成校验前仍不可读；`missing` 表示非预期丢失或校验失败。外置 Artifact Root 暂时不可用时，不批量把记录改成 `missing`，而是返回 Root 级错误并等待恢复。

### RebuildRecipe

只有完整配方才能让 Artifact 标记为 `rebuildable`，至少包含：

- `recipe_id`、`recipe_kind`、`recipe_schema_version`、`recipe_hash`
- ordered input Artifact refs/checksums 和所在 Revision/Candidate Snapshot ref
- 规范化参数、seed、output role/range/format
- engine/audio graph/Tone/Chromium/FFmpeg/Render Policy 版本
- 预期媒体属性、资源上限和校验规则

重建会创建新 Job，不修改原 recipe/lineage。如果某个输入为 `missing`、引擎版本不可得或许可不允许，不得将 Artifact 宣称为可重建。

Artifact 先写临时文件、校验 checksum，再原子移动到内容寻址位置并注册 metadata。失败或事务中断产生的孤儿由安全清理任务按 retention policy 处理。

## 9. 领域错误

领域层返回稳定 issue/error code，而不是依赖异常文本：

- `REVISION_CONFLICT`
- `SCHEMA_INVALID`
- `LOCKED_RANGE_VIOLATION`
- `IR_RANGE_INVALID`
- `TRACK_LIMIT_EXCEEDED`
- `ASSET_NOT_FOUND`
- `LICENSE_NOT_ALLOWED`
- `TIME_STRETCH_NOT_READY`
- `CHANGE_IMPACT_ESCALATED`
- `RENDER_POLICY_REJECTED`
- `ARTIFACT_ROOT_UNAVAILABLE`
- `ARTIFACT_MISSING`
- `STORAGE_QUOTA_EXCEEDED`

Application 层将其映射为 HTTP Problem Detail、Graph route 和 Run Event。

## 10. 迁移规则

- 读取旧 IR 时先迁移到当前内存 Schema，再允许编辑。
- Revision 原始 JSONB 不原地改写；迁移产生新的 system Revision。
- 导出 Manifest 同时包含源 Revision Schema 和导出时迁移版本。
- 不兼容迁移必须可 dry-run、可回滚 Project pointer，并有固定 fixture 测试。
- 引入 `lifecycle_class`、`availability` 和 RebuildRecipe 时必须通过 Alembic 迁移；旧的 `ready` 记录只能在 bytes/checksum 探测后标记为 `available`，不能仅根据旧状态推断。
