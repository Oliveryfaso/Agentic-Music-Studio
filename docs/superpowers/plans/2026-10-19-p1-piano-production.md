# P1 B/C/D/E：真实钢琴的可保存、可预览、可撤销纵切

Stage P1-B/C2/D/E；MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。BASE a099cc50893b1ee0fe714bade595af25c11a170b，Guide e3d9438/无diff，工作区clean。Spec：ADR-019、已批准p1-minimal-piano及C1审核包合同；用户明确继续，手动Sol/xhigh保留，无付费/大包/新语言/公共push。不重复已验A1/A2/C1长压力。

## Task 1：一次完整钢琴生产纵切

1. 先RED：v1 canonical/AudioGraph golden不变；v2显式双读roundtrip、profile/performance参与hash、悬空/重复note/负起音/过长gate/未知schema/pedal拒绝。GREEN：独立ArrangementIRV2+render-profile.v1/performance-plan.v1；scope固定单钢琴、PPQ480/globalBPM、审核CC0小包pin，32voice/2000note/30s gate/release上限沿用C1。谱面不由随机humanize改写。
2. 持久消费者同时接：Revision/Candidate/Studio DTO/DB readers、保持版本的命令重建、不可变hash/VersionRefs。新增仅human可用的显式set_piano_profile命令，payload有profile与performance；v1→v2不改旧aliases。动作L2经Preview/HITL；v2常规合法编辑保持表达，悬空引用明确拒绝。Undo以逆命令恢复已批准父快照，严格验证apply(inverse)==parent，仅为当前钢琴命令提供受限恢复，不放宽任意L2。
3. RED/GREEN真实独立PG保存/读回/审批/命令/Undo，新增JSON版本前向CHECK和downgrade guard；旧v1 reader/golden保持。先所有reader后新writer，不能用JSONB当作无需迁移策略。
4. 声音接同一共享compiler：独立audio-graph-spec.v2/engine.v2，canonical/candidate Job显式双读，recipe/lineage/profile/version固定。v2发音按时间和track/clip/note ID稳定排序；v1投影不重排。复用C1multisample安全adapter及本地审核catalog，server仅Root+Pin配置、nonce sampleID；缺包/错pin无fallback。真正Bundle写入确切CC0/来源/manifest pin，不再builtin-only空许可。
5. 同一Parent有限人工钢琴预览流程复用现有CandidateSnapshot/PreviewCandidate/Job/Outbox/HITL/审批；无需模型/AI Run，不增加生产Graph或旁路Project truth。人工来源不能伪装LLM输出，恢复dispatcher显式支持此线程。审批绑定不可变候选hash及已完成预览Artifact；刷新可恢复待批，取消不多付出副作用。
6. 最小UI：给自制短钢琴谱一个明确入口、已保存版本的profile状态、选择力度/起音/gate后预览，同位置原声/表达音频、确认/拒绝、Undo及导出。useAudioTransport仍只播放已交付Artifact，Draft不宣称已发声。缺包阻止应用、旧声可用；踏板/release-trigger明确不支持。新入口不删除legacy StylePack IDs/作品/路由，不做P2–P5。
7. 唯一短真实链：自制单轨v1→钢琴表达Preview→确认保存v2→新连接读回→canonical导出→Undo恢复v1 hash/声音→重开/重复请求，必要代表性取消/重试边界。实际Chromium+PG+文件SHA、0模型成本、PIANO_EXPRESSION_AUDIBLE/INSTRUMENT_PACK_UNAVAILABLE标签；试听是否更好由听者判断。避免重复5分钟/多轮压力。
8. 阶段末相关跨服务回归、生成OpenAPI/TS/build、一次新上下文独立审查/最多一次修复复核、本地checkpoint。必要Compose/live验证仅本任务资源，不碰旧DB/其他项目/共享VM；若容器证据确实需要则只构建变更target。精确清理自身PG/生成凭据和可重建中间物，保留样本原档/CC0/pin/accepted音频及证据；Library交付中文报告与代表试听。

## 接口预检与裁决

- A2.2已验导出plan动态文件与持久恢复；下一版本必须沿它的plan/hash而不是给旧v1字段补钢琴default。
- 目前domain Revision/Candidate、5处命令重建、3个DB reader、Studio DTO仍硬编码v1；同时切换，否则保存后丢profile/表达。
- Compile/Job/recipe的v1 Literal不能直接替换。C1adapter已证明声音但无生产接线；先双读才能新写。credits/license目前builtin-only必须同步修改。
- CreateCommandPreview/DecidePreview已有锁Branch与不可变snapshot；人工新钢琴命令将明确允许，经同一Parent预览/审批，旧agent限制仍保留。
- Undo现有已验证inverse恢复父快照；钢琴高影响回退仅对当前版本、确定性已批准父快照、专用命令开放，未触及的其他L2仍拒绝。
- 单琴最小范围不引入踏板近似：现有小包/adapter的合同均unsupported，未知参数不默认声称生效。需要支持时另立可验证版本。
- 风险分层测试优先；文档/ledger不触发重复全suite，短生产链一次，独立审查一次+唯一修复。执行中接口偏差记入ledger并继续授权范围。
