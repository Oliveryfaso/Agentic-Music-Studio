# Motif Forge 下一阶段开发路线

> **For agentic workers:** 实施本路线中的具体纵切前，必须先为该纵切建立 `docs/superpowers/plans/YYYY-MM-DD-<slice>.md`，再使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐项执行。
> 状态：已批准的主路线；S2 Task 6 起采用 ADR-016 作品集工程模式
> 起点：受控 Upload → Import → 分析 HITL → 保持音高对齐 → Web Preview 已完成
> 执行断点（2026-08-21）：G0、S1、S2、S3、S4、S5 已验收。浏览器已完成 Project → 四风格 Brief → PlanApproval → 两个候选 → Critic/至多一次 Repair → 显式 A/B 选择 → 七步完整导出 → 只读 Studio/MP3，以及同一 Project 顺序双 Stem；S5 no-key 旅程为 0 request/0 token。S6 是唯一活动门，S7 仍关闭。

**目标：** 从当前可靠的导入底座，按最短依赖路径完成“可生成、可听、可编辑、可恢复、可评测”的 Agentic Music Studio。

**架构：** 先用确定性模板打通完整创作和渲染事实链，再把已有 CompositionPlan 节点并入唯一 Parent Graph，最后逐层增加 Web Studio、四个 Style Pack、候选/修复和 AI 编辑。优化采用“短前置收口门 + 纵切内局部优化 + 功能接近完整后的重点硬化”，不设独立的大重构阶段。

**技术栈：** Python 3.12、FastAPI、Pydantic、SQLAlchemy/PostgreSQL、LangChain Core、LangGraph/PostgreSQL Checkpoint、DeepSeek V4 Flash、Celery/Redis、TypeScript、Tone.js/Web Audio、Chromium Render Worker、React/Vite。

## 1. 路线决策：先收口，随后边开发边优化

### 1.1 为什么不先做一次全面优化

全面优化会推迟第一首完整作品，而且当前大部分技术债只有在 Pattern、Render 和 Generate 接线出现后才能判断正确边界。提前拆分所有大文件、重写 API Client 或搭建完整 OTel 看板，容易形成第二轮基础设施超前。

### 1.2 为什么也不能直接继续堆功能

G0 前曾存在 48 个修改项、65 个未跟踪项、目标/状态文档漂移和两条暂时独立的 Graph。如果当时完全不收口，下一条生成链路会放大回退、审查和状态兼容风险；这些基线问题现已关闭。

### 1.3 采用的方式

只设置一个短的 `G0 开发前收口门`。通过后不再暂停做通用重构；每条功能纵切在触达的模块内完成主路径所需优化。S2 Task 6 起使用作品集工程模式：先交付完整 Agent 产品闭环，用代表性测试证明关键风险，再把准生产平台硬化集中到 S7/封版门。

优化分类如下：

| 类型 | 处理时机 | 内容 |
|---|---|---|
| 阻塞性收口 | 新业务代码之前 | 状态文档、路线、Git checkpoint、基线复验、单一 Graph 方向冻结 |
| 纵切内优化 | 功能经过模块时 | Graph 合并、Router 拆分、DTO 生成、SSE、Trace 接线、局部文件拆分 |
| 延后优化 | 有真实数据或产品路径后 | 全量 OTel 看板、性能重写、通用 RAG 平台、完整 UI 组件库、外部音乐模型 |
| 后置硬化 | 主功能接近完整或触发重大风险后 | 极端并发/故障矩阵、历史迁移兼容、负载/P95、多租户、发布级安全与灾备 |

## 2. 全局执行规则

每个纵切都必须遵守：

1. 先读取 `DECISION_LOG.md`、`PROJECT_GUIDE.md`、`IMPLEMENTATION_STATUS.md`、本路线和项目 Skill。
2. 记录 `PROJECT_GUIDE.md` 哈希；结束前复核没有被并发修改。
3. 写出单独实施计划，包含精确文件、接口、当前主路径失败边、代表性测试、Eval/Trace 影响和验收命令；不为未触发的准生产场景穷举矩阵。
4. 测试先行；每个 Task 先跑窄测试和一个真实边界，每 2–3 个 Task 或跨服务接线点跑组合回归，阶段末跑完整门。
5. LLM 只负责审美语义；节拍、音域、Pattern 展开、渲染、存储、错误和预算由确定性代码负责。
6. 不创建第二套 Project truth、第二套 Render semantics 或第三个生产 Graph。
7. 新增公共 API 时建立 OpenAPI → TypeScript DTO 生成边界；不继续扩大手写 DTO。
8. 长任务进度进入持久事件；新增生成进度 UI 时使用带 replay ID 的 SSE，不新增轮询型长期协议。
9. 每个创作阶段建立代表性 Eval；工程 Task 可先用窄回归覆盖，到阶段 Eval 门集中入库，不能让 Eval 数量要求阻塞主链路。
10. 日常使用 host-first 测试。只有 Dockerfile/系统依赖、容器 lockfile、迁移/运行时接线或阶段验收才构建受影响 target。
11. 小阶段验收后执行 Storage Hygiene Gate；不删除数据库卷、原始导入、当前 Revision 依赖或其他项目资源。
12. 每个可独立验收的纵切形成 Git checkpoint；默认一次独立审查、最多一次修复复审。Critical 与影响当前主路径/数据/Secrets/费用/HITL/幂等/恢复的 Important 必须关闭，其余进入后置硬化登记。
13. S2 剩余阶段每个 Task 使用一个新 Session，从 clean checkpoint 和精简 handoff 开始；实现/审查 subagent 只接收活动 Task、必要合同和当前 diff，不携带全部历史审查文本。
14. 一次修复复审后若仍有阻塞级问题，停止并记录精确 blocker，等待决策；不能为了遵守次数上限而降级问题，也不能自动进入无限审查循环。

### 2.1 作品集工程模式的质量下限

以下内容任何阶段都不能用“先做 Demo”为理由删除：单一 Parent Graph、结构化模型输出、确定性编译与 Fallback、真实 HITL、不可变 Revision、持久 Run/checkpoint/event、硬预算、Secret 隔离、一次恢复不重复副作用、完整音乐导出、代表性 Eval/Trace 和真实 DeepSeek 验收。

当前可以延后的是证明广度，不是架构正确性：只覆盖一个代表性取消/恢复/重复投递和一个真实 PostgreSQL/Compose 主路径；全崩溃点、全并发交错、全部历史 populated downgrade、长时间负载/P95、多租户和全量 OTel 在 S7/封版前按风险回补。

## 3. G0：开发前收口门

这是唯一需要在新业务功能前独立完成的优化阶段，目标是建立安全起点，不改产品行为。

### G0.1 文档事实收口

- 建立 `IMPLEMENTATION_STATUS.md` 与本路线。
- 修正 `PROJECT_GUIDE.md` 顶部当前阶段、README 当前能力和文档地图。
- 在 Decision Log 冻结“短收口门 + 纵切内优化”。
- 在项目 Skill 中要求模型先读取状态和路线。

### G0.2 版本控制 checkpoint

- 盘点 48 个修改项和 65 个未跟踪项。
- 排除 Secret、`.env`、Artifact、cache、构建产物和本机路径。
- 复跑 Python、PostgreSQL、Audio、Web、Ruff、Mypy、迁移和 readiness 基线。
- 形成可恢复的 Import/Analysis/Alignment/Web Preview 里程碑 commit 并推送。

### G0.3 通过条件

- 工作区中的业务变更已进入明确 checkpoint；剩余 dirty 项均有解释。
- 文档不再把已完成 Upload UI 写成下一步。
- 当前测试基线可复现。
- 下一条纵切只有一个入口：`S1 确定性完整成曲 Walking Skeleton`。

G0 不包含：重写 API、拆分所有大文件、Graph 代码合并、引入新依赖、接 DeepSeek live key 或重新设计页面。

## 4. 原始产品需求追踪矩阵

下表把最初批准的功能目标绑定到具体阶段。后续模型不得因为当前纵切较小而删除最终需求，也不得把尚未到达的阶段伪报为完成。任何范围变化必须先修改 Decision Log、Project Guide 和本矩阵，并取得用户确认。

| ID | 原始需求 | 首个实现阶段 | 最终验收阶段 | 不得偏离的边界 |
|---|---|---|---|---|
| MF-P01 | 网页形态、本地优先、纯器乐音乐工作台 | S3 | S7 | 不把项目降成 CLI 或一次 MP3 API 调用 |
| MF-P02 | 从空白 Brief 生成完整作品 | S1 确定性基线、S2 Agent 化 | S7 | 首版最终支持 1–5 分钟、最多 12 轨、完整开端—发展—收束 |
| MF-P03 | 导入 WAV/MP3/FLAC 和多个 Stem | 已完成单文件 Import、S3 多 Stem | S3 | 原始文件不可变；首版不做自动 stem separation |
| MF-P04 | DeepSeek V4 Flash 理解审美、规划曲式和编配 | S2 | S5 | 模型生成结构化 Plan/Pattern/Patch，不生成 PCM、不控制音乐时钟 |
| MF-P05 | 生成整曲、指定音轨和已有区域上的新轨道 | S2 整曲、S6 局部 | S6 | 选区操作只传有限上下文并输出 delta，不能静默重写全曲 |
| MF-P06 | 简单 AI 修改直接落地，旋律/曲风/曲式/大范围变化人工确认 | S6 | S6 | L0/L1 自动 Revision + Undo；L2/L3 Preview/HITL；实际影响只可升级 |
| MF-P07 | 生成前审阅并调整结构、BPM、Key、配器和能量曲线 | S2 Graph、S3 UI | S3 | PlanApproval 是 checkpoint/interrupt，Fallback 也不能绕过 |
| MF-P08 | 音乐史、美学、和声、古典、爵士知识 | S4 | S4/S5 | RAG 只注入来源明确的 StyleConstraints；硬音乐规则由 Theory Engine 执行 |
| MF-P09 | Synth Ambient、Minimal Electronic、Classical Chamber、Jazz 四包一起交付 | S4 | S7 | 可按依赖顺序提高成熟度，但首版发布时四包都必须可生成完整作品 |
| MF-P10 | 内置常用音色，并支持 AI 生成/寻找音色和旋律 | S1 Seed Palette、S4 Catalog、S6 AI | S6/S7 | 本地许可审核 Catalog 优先；外部搜索需用户显式开启和许可确认 |
| MF-P11 | 多轨、钢琴卷帘、混音、拖动、裁切、拆分、复制和尾音处理 | S6 | S6 | EQ、pitch、fade、reverb/delay tail 是不同参数；不冒充完整专业 DAW |
| MF-P12 | 保持音高不变的 time-stretch | 已完成受限基线 | S3/S7 | 原始 Artifact 不覆盖；首版不承诺实时弹性音频、复杂 tempo map 或极端拉伸 |
| MF-P13 | 一个完整 Graph 覆盖正常流、异常、重试、恢复和 HITL | 已完成 Import 分支、S2 Generate、S5 完整编排 | S7 | 一个版本化 Parent Graph；每次 import/generate/edit/export 是有限 thread |
| MF-P14 | 不同音乐思路匹配不同节点、Edge、Loop | S4 策略知识、S5 策略子图 | S5 | 只为可评测的差异增加子图；简单规则节点不用模型，不做角色聊天式伪多 Agent |
| MF-P15 | 完整输出 Master WAV/MP3、Stem、MIDI、项目和 manifests | S1 | S7 发布复验 | Candidate Preview 可有损；最终 Master/Stem 保持 48 kHz PCM24 合同 |
| MF-P16 | PostgreSQL、Redis、独立 Worker、Docker Compose | 已有 Media 栈、S1 Render 接线 | S7 | PostgreSQL 是事实源，Redis/Celery 只负责至少一次投递 |
| MF-P17 | 外置盘优先和 Lean Storage | 已完成基础合同 | 持续 | 不静默回落内置盘；不因节省空间降低最终交付质量 |
| MF-P18 | Eval、Trace、失败分类、成本/延迟和 Threat Model | S1 起持续积累 | S7 | 每个纵切都有 Eval/Trace；最终至少 96 条内部 Eval 和公开量化结果 |
| MF-P19 | 为未来 Signal Field/端到端音乐模型保留接口 | S7 后可选 | 阶段 9 | 不让未来 Adapter 污染当前 ArrangementIR、Graph 或 Renderer 边界 |
| MF-P20 | 专业 DAW 基础上增加克制的科幻与自由视觉 | 已完成 Import Review 基线、S3/S6 扩展 | S7 | 深石墨高密度为主，青/紫/洋红有语义；不能用霓虹牺牲时间线可读性或只靠颜色传达状态 |
| MF-P21 | Prompt Injection、最小权限、许可证、Secrets、审计与高风险审批 | 已有上传/路径/许可基础、S4/S6 扩展 | S7 | 模型只用纯/只读工具；外部音源、写入和高风险操作受 Allowlist、校验、审计与 HITL 约束 |

### 4.1 需求追踪执行规则

- 每个具体实施计划必须列出覆盖的 `MF-Pxx`，未列出的需求不得顺手修改。
- 每个纵切验收后，只把有运行证据的行同步为“已完成”；Schema、测试或 Spike 单独存在只能记为“内部完成/部分完成”。
- 如果实现选择与原始需求产生质量、成本或范围取舍，先写 ADR 并向用户确认，不能由实现模型自行降低要求。
- S1–S7 任一阶段都不得删除完整导出、四个 Style Pack、HITL、AI 局部编辑、可恢复 Graph、既定视觉语言、安全/版权或 Eval，只能按依赖顺序推迟到已标明阶段。

## 5. 阶段技术交付总表

| 阶段 | 用户可见结果 | 核心 Schema/事实 | Graph/规则 | Worker/Artifact | API/Web | Eval/故障门 |
|---|---|---|---|---|---|---|
| G0 | 无新功能，获得安全开发起点 | 当前能力矩阵、路线、Git checkpoint | 冻结单一 Parent Graph 方向 | 不新增 Job | 修正文档入口 | 全基线复验 |
| S1 | 无模型也能生成并完整导出第一首作品 | `PatternSpec v1`、完整 ArrangementIR Revision、Export Bundle | 确定性模板与 validator | 正式 Chromium Render Job、Master/Stem/MP3/MIDI/manifests | 内部 API/CLI smoke 即可 | 20 条确定性 Eval、崩溃/重复/断盘 |
| S2 | Brief 审批后生成完整作品 | `GenerateRunState`、Plan/Revision/Artifact refs | Plan v3 并入 Parent、Fallback、Budget/Error | 复用 S1 Render | Run/resume/cancel/SSE 合同 | live DeepSeek opt-in、checkpoint replay |
| S3 | 浏览器完成 Brief → 生成 → 试听 | Project/Run read models、生成 DTO | HITL/SSE replay | Preview playback | Home、Brief/Plan、只读 Timeline | 刷新恢复、空/错/窄屏、多 Stem |
| S4 | 四种音乐策略产生不同完整作品 | StylePack/TheoryRule/Exemplar/Catalog versions | Strategy Router 与确定性规则 | Seed Palette → Core Palette | Style/Source 解释 | 四风格约束、引用、许可、注入 |
| S5 | 两候选、局部修复和 A/B | Candidate/Segment DAG、Critique/Analysis refs | fan-out/fan-in、Continuity、Critic/Repair、Budget | Segment render/stitch/preview | Compare/HITL | 重复恢复、部分成功、无改善终止 |
| S6 | 手工编辑与 AI 局部编辑 | Draft、EditPatchProposal、ChangeImpact、Revision | edit subgraph、L0/L1 与 L2/L3 | 局部 Preview/按需重渲 | Timeline/Piano Roll/Mixer/Library | 锁定区域、非目标保持、冲突/Undo |
| S7 | 导出产品化复验和作品集演示 | Export bundle、Eval/Trace/Metric versions | export/release 路由 | WAV/MP3/Stem/MIDI/manifests | Export、Run Inspector、Eval Lab | 96+ Eval、P95、故障注入、CI/CD |

## 6. S1：确定性完整成曲 Walking Skeleton

> 状态：**已完成**。72 秒、80 BPM、4/4、C major、四轨 Synth Ambient 固定作品已经由真实 Outbox/Redis/Celery/Chromium 队列链导出；Revision→AudioGraph 强绑定、Protected 输出不可变、StoragePressureGate、MP3 probe、断连取消及审批/命令审计已通过针对性测试和独立复审。

**用户价值：** 首次证明 Motif Forge 能把结构化音乐计划变成一首完整可交付作品，而不仅能导入音频。

**内部范围：** 60–90 秒、4/4、固定 BPM、4 轨、单候选、Synth Ambient、固定 seed。它是内部里程碑，不降低首版最终的 1–5 分钟、12 轨、2 候选和四风格合同。

### S1.1 PatternSpec v1 与 Composer 基线

- 冻结最小 `PatternSpec v1`：section、track role、chord degrees、rhythm grid、register、density、variation seed。
- 实现确定性的 chord realization、motif、bass、pad 与 pulse/drum pattern。
- Pattern 编译为 tick-based NoteClip/NoteEvent，不把浮点秒写回 Project truth。
- 生成完整 ArrangementIR Revision，并验证段落闭合、音域、复音、速度、时长和无越界事件。

`PatternSpec v1` 至少固定以下技术字段：`pattern_id`、`section_id`、`track_role`、`bar_range`、`chord_degrees`、`rhythm_grid`、`register`、`density`、`syncopation`、`variation_seed` 和 `locked_constraints`。它是高层生成表示，不保存原始 MIDI bytes；编译结果通过现有 Editor/System Command 形成完整 Revision，不能绕过命令审计写入任意 IR JSON。

### S1.2 ArrangementIR → AudioGraphSpec 边界

- 建立唯一编译适配器，把 tick/tempo/track/preset 投影成现有 `AudioGraphSpec`。
- `AudioGraphSpec` 中的 seconds 只允许作为渲染投影，不成为持久化乐曲坐标。
- 扩展最小合成器/鼓音色，但开发用 Seed Palette 控制在 100–250 MiB；最终 `Core Sound Palette Lite` 0.5–1 GiB 合同不变。

### S1.3 正式 Render Job 与完整导出

- 把 30 秒 Spike 泛化为受控 Chromium Render Job，接入现有 Job/Outbox/Worker/Artifact 合同。
- 第一子门先生成 Master WAV、MIDI 和 Project Manifest，验证创作事实链；同一 S1 在进入 S2 前补齐 MP3、四条按需 Stem、credits/license/provenance manifest 和 trace manifest，不能把完整导出长期推迟到发布阶段。
- 写入 engine/schema/seed/input checksum、Artifact lineage、取消、超时、重复事件和失败状态。
- canonical 渲染继续使用共享 Tone.js AudioGraphCompiler，不引入第二套听感不同的渲染器。

正式合同固定为：Python Application 创建 `RenderJobRequest v1`，只包含 run/project/revision、render scope、quality profile、AudioGraph/Artifact ref、engine version、seed、deadline 和 idempotency key；Chromium 页面只接收 `RenderBridgeRequest v1`；Worker 返回 `RenderReceipt v1` 后由 Python 校验 duration、sample rate、channels、peak、silence、checksum 和 lineage，再原子登记 Artifact 与 completion event。WAV bytes 不进入 Redis、Graph State、数据库 JSON 或普通 Playwright 返回值。

### S1.4 验收门

- 无 API key、无 LLM 也能从固定 Brief 产生可听的 60–90 秒完整作品。
- 同 seed 与版本满足已定义的确定性/容差合同。
- Worker 崩溃、重复 completion、容量不足和外置 Root 断开有明确恢复或终止结果。
- Master WAV/MP3、四条 Stem、MIDI、可编辑 Project、credits/license/provenance/trace manifests 均可读取且 checksum/lineage 完整；候选试听可以有损，canonical Master/Stem 使用 48 kHz PCM24。
- Eval 累计至少 20 条，覆盖 Pattern 边界、结构闭合、渲染成功和失败标签。

S1 通过前禁止：接入真实 DeepSeek 生成、开发 Timeline 编辑器、增加第二候选、建设向量数据库、扩展通用 Storage 平台或购买大型音色包。

## 7. S2：统一 Generate Graph 与 DeepSeek 生产接线

**用户价值：** 用户可提交 Brief，审阅计划，并在恢复后得到一首完整作品。

> 当前状态：S2 已完成。Parent Graph v2 已把 Brief、DeepSeek/Fallback Planning、PlanApproval、Revision、七步完整导出和终态收进同一持久 thread；异步 Dispatcher、REST/SSE、重启/重复/取消、16 条代表性 Eval、无付费 Compose smoke 与一次受控真实 DeepSeek acceptance 均有验收证据。S3 已消费这些 API；下一入口是 S4 Style Pack/Theory Engine。

### S2.1 合并 Graph 拓扑

- 将现有 Plan v3 节点作为 Parent Graph 的 `generate` 子图，不复制 CompositionPlanner 逻辑。
- 使用显式 ParentState ↔ PlanState Adapter；大型 IR/音频仍只传 Artifact/Revision ref。
- 同一 generate thread 内依次完成 plan、approval、pattern、render、completion/error。
- 迁移或终止不兼容旧 checkpoint，不静默用新节点解释旧 state。

### S2.2 DeepSeek 与确定性 Fallback

- thinking 模式只用于宏观 CompositionPlan；简单 Pattern 参数补全优先 non-thinking 或确定性工具。
- Live DeepSeek smoke 为 opt-in，记录模型、prompt/schema 版本、tokens、latency 和 usage，不记录 reasoning_content。
- 模型连接失败、Schema 失败或预算耗尽时，确定性模板仍能产生需要确认的基础计划；不能绕过 PlanApproval。

### S2.3 Generate API 与持久事件

- 增加 Project AI Run、Run read/resume/cancel 和 SSE event API。
- 新增公开 DTO 时同时建立 OpenAPI TypeScript 生成流程。
- 接通 PostgresTelemetryRecorder；cost 未能可靠计算时明确为 unknown，不伪造为 0。

最小公开资源固定为：`POST /projects/{id}/ai-runs` 创建 `run_type=generate`，`GET /runs/{id}` 读取投影，`GET /runs/{id}/events` 使用持久 SSE ID，`POST /runs/{id}/resume|cancel|retry` 携带 checkpoint/idempotency 条件。浏览器不能直接提交 Render Job、物理路径、模型参数或任意 Graph node 名称。

`GenerateRunState` 只保存 Brief/Plan 小对象、strategy refs、Revision/Candidate/Job/Artifact refs、approval/control/budget/error/outcome；完整 IR、长 Prompt、模型消息和音频不进 checkpoint。Plan 子图必须返回 Parent State Adapter，而不是让 API 在两个 graph object 间人工串联。

### S2.4 验收门

- `Brief → PlanApproval → Pattern → Render → complete` 在一个 Parent thread 内完成。
- API/Worker 重启后从正确 checkpoint 恢复，不重复模型调用、Revision 或 Artifact。
- DeepSeek 不可用时有可审核的确定性降级结果。
- 至少完成一次真实 DeepSeek V4 Flash opt-in 契约验收后，才宣称模型已接通。
- 代表性重启、重复投递和取消场景不重复模型调用、Revision 或导出；不要求在 S2 穷举每个 checkpoint/Worker 时点。
- S2 Eval 至少 16 条并覆盖有效 Brief、前置拒绝、Fallback、审批、恢复/重复/取消；更大的风格、编辑和故障数据集随 S4–S7 扩展。

## 8. S3：Brief/Plan 与只读 Studio 创作闭环

**用户价值：** 用户不需要调用 API 就能从网页生成并试听第一首作品。

> 当前状态：S3 已完成。Project Home、Brief、Plan Review/Approval、immutable child Replan、持久进度、只读 Timeline/Track Header、MP3 Transport、Artifact 恢复状态、390px 审阅和同 Project 多 Stem 均已接通。确定性 Chromium gate 得到 2 个可读 Plan、1 Revision、7 Jobs、6 Audio、1 Bundle、真实 MP3 播放、两次 head 推进和 0 request/0 token。

- 实现 Project Home、New Composition Brief、Plan Review/Approval。
- 实现基础 Transport、Arrangement 只读 Timeline、Track Header 和候选播放。
- 生成进度使用持久 SSE；刷新后按 event ID replay 并恢复当前 Run。
- 保留当前 Import Review，并允许向既有 Project 添加音频，不再强制每个文件创建新 Project。
- 桌面承担创作；390px 窄屏只保证查看、播放、审批和错误恢复。

验收：浏览器完成 `Brief → 审批 → 生成 → 试听 → 打开 Project`，以及 `导入多个 Stem → 同一 Project` 两条路径。

页面状态必须覆盖：未建 Project、Brief validation error、等待计划、等待审批、生成排队/处理中、部分成功、Worker/模型失败、取消、checkpoint 恢复、Artifact evicted/rehydrating/missing、Revision conflict 和外置 Root 不可用。桌面时间线允许横向滚动；移动端不承诺精细拖拽。

## 9. S4：四个 Style Pack 与 Theory Engine

> 当前状态：**已完成**。四个 reviewed `StylePack v1`、确定性 `TheoryEngine v1`、MusicStrategyRouter、Parent Graph 物化、Web 风格/来源/许可说明、8 条代表性生成 Eval 与四风格完整导出均已有运行证据；S5 已在此基础上完成，下一入口是 S6。

**用户价值：** 同一工作台能产生四种结构上明显不同且有证据来源的音乐策略。

四个 Pack 的 Schema、版本、引用、许可和测试一起交付；内部建设按以下依赖顺序推进，但不能把 Classical/Jazz 永久降为占位符：

1. 冻结通用 StyleCard、FormTemplate、InstrumentationGuide、ProductionRecipe 和 SymbolicExemplar 合同。
2. Synth Ambient、Minimal Electronic 先达到完整可渲染质量。
3. Classical Chamber 加入音域、voice leading、平行五/八度提示和室内乐配器。
4. Jazz 加入 chord-scale、tension/avoid-note、voicing 和基础即兴动机规则。
5. 四个 Pack 统一接入 metadata filter、引用、版本、Preset Palette 和 Prompt Injection/许可测试。

验收：四个 Pack 都能从同一 Brief 合同生成完整作品；规则错误与软审美建议在输出、Trace 和 Eval 中明确分离。

每个 `StylePack v1` 必须携带 `pack_id/version`、genre/era、form templates、instrument roles/ranges、harmony/rhythm/timbre constraints、avoidances、production recipes、symbolic exemplar refs、source citations、license snapshot 和 compatible engine/schema versions。Theory Rule 返回稳定 rule ID、severity、bar/track evidence、explanation code 和 suggested bounded operation；RAG 文本不能直接决定音符合法性或许可证。

## 10. S5：完整候选、Critic 与 Repair Orchestrator

> 当前状态：**已完成**。同一 Parent Graph v2 已实现两个稳定候选、真实候选 Preview Job、结构化证据 Critic、至多一个子 Repair Snapshot、显式 A/B HITL、仅选中候选物化和七步完整导出。无 Key CLI 与真实浏览器验收均得到 `2 candidate families / 3 snapshots / 2 selection previews / 1 Revision / 7 Jobs / 6 Audio / 1 Bundle / 0 request / 0 token`；S6 是下一入口。

- 增加最多两个候选的 fan-out/fan-in，CandidateState 以稳定 ID reducer 合并。
- 实现 Section/Track Segment DAG、Continuity Validator 和只重算失败段落。
- Critic 只能依据结构化 IR、音频指标和版本差异；不能用无证据“听感自评”决定成功。
- Repair Loop 以指标改善、最大轮数、非改善轮数、token/cost/render budget 终止。
- A/B 选择走 PreviewCandidate/HITL；选择后才物化 Revision 和按需 canonical 导出。

验收：重复恢复不会产生重复候选；部分段落成功可保留；预算耗尽返回最佳可播放版本和明确警告。

Candidate fan-out 使用独立 `candidate_id + seed + CandidateState`；fan-in reducer 按稳定 ID 合并并排序，禁止并发分支覆盖共享 Arrangement。Repair 只提交有界操作和目标 Segment，终止条件至少包含 accepted、user_stop、max_revisions、budget_exhausted、non_improving_rounds 和 deadline；LangGraph recursion limit 只作最后保险。

## 11. S6：轻量 DAW 与 AI 选区编辑

### S6.1 手工编辑

- Timeline、Piano Roll、Mixer、Sample Library。
- move/trim/split/copy/loop、gain/pan/fade/EQ、mute/solo。
- 浏览器 Draft、服务端 Revision、PreviewCandidate 和 Audio runtime 保持四种不同状态。
- 所有提交转换为现有 EditorCommand，支持 conflict、undo 和 branch。

### S6.2 AI 编辑

- 只传选区、前后有限小节和结构摘要。
- 支持新增轨道、局部重写、延伸、音色/旋律生成或审核音源检索。
- 实际 diff 计算后：L0/L1 自动 Revision + Undo；L2/L3 Preview/HITL。
- 锁定元素和非目标区域保持度进入自动回归。

验收：简单 AI 参数修改可自动落地；旋律、曲风、曲式或大范围变更必须先试听和确认。

前端始终区分四种状态：服务端不可变 Revision、浏览器可撤销 Draft、待审批 Candidate/Preview、Tone/Web Audio runtime。`EditPatchProposal v1` 必须带 `base_revision_id`、selection、commands、rationale/evidence 和 expected effect；服务端模拟后计算真实 ChangeImpact。模型可调用的工具保持纯函数/只读，`commit_revision`、Render enqueue、外部下载和持久化仍只属于 Application/Graph。

## 12. S7：导出产品化复验、Eval、可观测性与发布演示

- 把 S1 已完成的 Master WAV/MP3、按需 Stem、MIDI、项目文件和 manifests 接入正式 Export 页面、长作品/12 轨性能矩阵、失败恢复和发布兼容性复验，不在 S7 才首次实现格式能力。
- Eval Set 扩展到至少 96 条；对比规则模板、单次 DeepSeek 和完整 Graph。
- 打通 OTel、Run Inspector、失败分类、P50/P95、token/任务成本和恢复率。
- 注入模型中断、429、坏导入、渲染失败、Worker 崩溃、重复事件、版本冲突、存储不足和预算耗尽。
- Web、API、Media Worker、Render Worker、PostgreSQL、Redis 形成完整演示档位；增加 CI/CD 和基础负载测试。
- 执行后置硬化登记：优先关闭已出现两次、影响真实数据/费用/权限/恢复，或准备公开发布时仍存在的 Critical/Important；补代表性的极端并发、迁移、负载和安全测试，而不是机械穷举所有组合。

验收：一条命令启动完整产品；至少 50 条公开作品集 Eval 案例和完整量化报告可复现；最终内部 Eval 资产不少于 96 条。

最终导出包至少包含：canonical Master WAV、MP3、请求的 Stem、MIDI、canonical ArrangementIR/Project、credits/license/provenance manifest、engine/prompt/policy/style-pack versions、必要 trace refs 和每个文件 checksum。Eval 分为确定性 Schema/音乐/渲染、任务级 Brief/编辑/恢复、人工 A/B 三层；报告必须同时给成功率、约束满足、Render success、引用/许可、编辑局部性、P50/P95、token/成本、恢复率和已知失败类别。

## 13. 跨阶段技术不变量

### 13.1 数据与版本

- PostgreSQL Revision JSONB 保存完整 canonical ArrangementIR；大型音频、MIDI、peaks 和分析文件放 Artifact Store。
- PPQ tick 是持久音乐时间；seconds 只用于 Audio source offset 和 Render projection。
- Project、Branch、Revision、Candidate、Preview、Run、Job、Artifact 和 Feature 各自有稳定 UUID/ref，不用文件路径替代身份。
- Prompt、Schema、Graph、Policy、Style Pack、Audio Engine、Quality Profile 和 RebuildRecipe 都必须版本化并进入 Trace/Artifact lineage。

### 13.2 Agent 与规则边界

- DeepSeek 只生成 `CompositionPlan`、`SectionGenerationPlan`、`PatternSpec`、`SynthPatchSpec`、`SampleTriggerSpec`、`Critique` 或有界 `EditPatchProposal`。
- 时间换算、和弦/音阶/音域、Pattern 展开、许可、路径、存储、事务、重试分类、预算硬门和渲染由确定性代码完成。
- 系统错误由版本化 Error Policy 路由；429/timeout/5xx 由 Provider 有界重试，领域校验失败由 Repair，信息不足/高风险由 HITL，不能叠加多个重试所有者。

### 13.3 音频与资产

- Imported original 永不覆盖；Working、Preview、Canonical 是不同 Quality Profile 和 Artifact lineage。
- 浏览器和 Worker 共用 AudioGraphCompiler/Tone semantics；FFmpeg 只负责标准化、time-stretch 和编码。
- 所有 Sample/SoundFont/Preset 保存 source、creator、license/version、attribution、checksum 和 imported_at；禁止抓取受版权保护的经典录音作为样本。
- 外置 Root 不可用时停止 Artifact 写入，不回落内置盘；GC 不删除 protected/durable 或无完整 recipe 的文件。

### 13.4 用户审批

- 从零生成、曲风/旋律/曲式或大范围变化、外部音源导入和高风险操作必须人工确认。
- 简单参数或局部低影响修改只有在 Schema、范围、许可、锁定区域和真实 diff 均通过时自动形成 Revision，并必须可 Undo。
- PreviewCandidate 不等于 Revision；批准后创建新 Revision，拒绝/过期不修改 Branch head。

## 14. 明确延后与后置硬化登记

以下事项不能插入 S1–S3 主路径：

- ACE-Step、MusicGen 或其他端到端音乐模型。
- 实时协作、录音、VST、stem separation、专业 mastering。
- WebGL Timeline、完整组件库重写、移动端精细编辑。
- 通用 RAG 平台、向量数据库或多模型路由。
- 因“大文件看起来不舒服”而进行的全仓重构。
- 不能由现有产品用例和 Eval 证明收益的多 Agent 角色。

以下准生产事项不阻塞 S2–S6 的功能闭环，统一在 S7/公开发布前按风险排序：

- 全 checkpoint 崩溃注入、全取消时点、所有重复投递与并发交错组合。
- 所有历史 Schema 的 populated downgrade；当前只要求前向迁移、版本化读取、关键引用一致和危险降级 fail closed。
- 多租户隔离、水平扩缩、长时间 soak、灾备演练、完整 P50/P95 容量矩阵。
- 全量 OTel/看板、自动告警、生产级 SLO 和 CI/CD 发布治理。
- 对不影响当前主路径的非核心 Important/Minor 做立即多轮修复。

后置项必须包含：来源 Task/审查、风险、触发器、最晚处理门和最小复现。出现数据损坏/越权/Secret 泄露、重复付费或副作用、用户主路径无法恢复、相同缺陷第二次出现，或准备公开发布时，立即升级为阻塞项。

## 15. 计划维护规则

- `PROJECT_GUIDE.md` 只在产品/架构合同变化时更新。
- `IMPLEMENTATION_STATUS.md` 在每个已验收纵切后更新能力矩阵与验证基线。
- 本路线只在依赖顺序、阶段边界或验收门变化时更新。
- `TECH_EVOLUTION.md` 追加实际发生的实现、偏差、测试和存储证据。
- 具体纵切的代码级步骤写入 `docs/superpowers/plans/`，完成后保留作为审计记录，不把临时步骤塞回总指南。
- S2 Task 6–12 及后续计划必须声明使用作品集工程模式，并把延后问题写入本路线第 14 节或对应阶段报告；不能只在审查聊天中留下结论。
- 若执行发现路线与真实代码冲突，停止当前实现，先记录证据和提出最小路线修订，不静默偏航。
- 每个具体计划和验收报告列出覆盖的 `MF-Pxx`；若某个首版需求连续两个阶段没有对应任务或 Eval，视为路线漂移并在继续前复核。
