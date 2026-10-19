# Motif Forge 当前实施状态

> 状态日期：2026-10-19（历史验证按原日期保留）
> 性质：当前代码事实与验收证据，不替代产品合同
> 更新规则：每个被验收的小纵切结束后更新；不要把目标设计写成已实现能力

## 1. 阅读顺序

开发模型开始任务时按以下顺序读取：

1. `DECISION_LOG.md`：不可静默推翻的决定。
2. `PROJECT_GUIDE.md`：最终产品范围和总体架构。
3. 本文件：当前代码到底完成到哪里。
4. `NEXT_DEVELOPMENT_ROADMAP.md`：下一阶段的依赖顺序和验收门。
5. 与当前纵切有关的专项合同和项目 Skill。

若本文件与测试、迁移或运行时证据冲突，以代码和最新可复现证据为准，并在继续开发前修正文档。历史过程只写入 `TECH_EVOLUTION.md`。

## 2. 当前产品形态

### 当前验收：P2.2 自然语言伴奏与局部修改（2026-10-19）

MF-P02/P04/P05/P06/P11/P13/P15/P16/P17/P18/P21。既有DSAPI Flash→有界逐bar计划→音乐约束/可信原和声校验→同Parent候选A/B→hash保留→第二轨1–4bar修改/重开/精确Undo/导出已通。单动作单请求；0027不可变Plan、预算/待回执unknown和Inspector一致；旧人工P2.1兼容，不新增Graph/音源/依赖。真实累计4调用/7228tokens（包括首轮和声反例），高峰保守费用上界¥0.023852，未查询账单。最终2个Run各1次、6Jobs/8文件SHA；747 Python、102 Web、61Audio、6PG/Inspector、Mypy131源/两build/lint通过。独立审查2Important经唯一修复与限定复核关闭；Minor缺失reported-model默认别名延后。原谱/选区外/所选G-Am-D-G和声exact；范围16→4音、力度57→38。仅这一首与两轨，未宣布全P2/P3/多曲/实时混音/审美质量/默认两风格旧宏观LLM完成。见[合同](P2_SEMANTIC_PIANO_CONTRACT.md)、[验收](evidence/2026-10-19-p22-semantic-piano.md)。

### 已验收：P2.1 经典旋律导入与新增伴奏（2026-10-19）

MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。固定Mutopia528公版16小节/62音soprano旋律转写，锁定原轨/独立原分支、单事务导入；用户选择逐小节和弦/织体/八度/力度，在既有同一Parent中比较真实两版，显式hash保留/放弃，保存/重开/精确Undo与v4导出已验。新IR/Graph/engine/Job v3最多两条同审核包钢琴，旧v1/v2不放宽；0026迁移与降级guard保留。

真实新临时PG+built UI+Chromium4Jobs、8导出文件SHA、刷新/同位置播放/错误hash409/重复持久恢复/窄屏/Undo播放/取消通过；模型0。Python679/Web96/Audio61/PG相关4、Mypy127源/两build/Ruff通过。一次初审1Important（导入两事务空项目）经一次作者PG RED→GREEN和限定复核关闭；保留完整原始报告。自己的PG/生成凭据/临时启动器已清理，accepted媒体/许可保留，共享服务不动。不是通用MusicXML/自由自然语言/真实多乐器、整个P2或音乐音质/性能达标；用户库未迁移、无部署。见[验收与边界](evidence/2026-10-19-p2-classical-accompaniment.md)。以下旧段落按各门当时事实保留。

### 已验收：P1-MF-P09 古典/爵士新建入口（2026-10-19）

MF-P09；关联 MF-P10/P13/P15/P16/P18/P21。新建编曲仅提供古典室内乐/爵士和声与即兴，默认古典；首页与乐器示例同步。过滤仅在新建表单，API/后端四 StylePack IDs 与旧 Plan/Candidate/Studio/Export、作品声音保留，不自动把 Brief 升级成真实钢琴或 IR v2。

作者 RED3→目标21/Web93、既有四风格/Eval/渲染19、tsc/Vite build 通过；独立审查无 findings，另跑 UI25/风格渲染14/tsc/diff。built UI + 隔离接口样例浏览器验证两种实际 POST、原预算、旧 v1 播放/七步导出/原 WAV 下载校验与390px布局。未运行真实后台/PG/模型/新渲染，不重复上阶段钢琴长链，未作音乐质量声明。自有 browser/server 已关闭；保留314,668 bytes浏览器证据，无共享资源清理，P2–P5未启动。见[验收报告](evidence/2026-10-19-mf-p09-entry.md)。

### 已验收：P1 B/C2/D/E 单钢琴生产链（2026-10-19）

MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。自制30秒谱入口→同一Parent人工A/B→精确hash审批→v2保存/重开→canonical导出→受限Undo恢复v1，已在真实独立PG/Chromium和built UI/本地HTTP验证。IR/Graph/Job显式v2、Plan/Bundle显式v3；旧v1声音/aliases不改，0024/0025迁移guard保留。单琴/小包/单有效力度层；踏板与release-trigger不支持。

实际8Jobs3Bundles/5次短渲染、所有文件下载SHA、错误审批409/重放/连接恢复；Undo max1LSB，last2s0。模型调用/该项目AI Run0。一次独立审查2Important经一次作者RED→GREEN修复，无剩余阻塞；Python635、Web92、Audio59、Mypy121、Ruff/两个build通过。自有PG/凭据已删、probe已停；accepted音频/CC0/manifest与证据保留，共享服务未动。[完整证据](evidence/2026-10-19-p1-piano-production.md)。

这是有限钢琴生产纵切，未验主观音质、Redis/Celery/Compose重启或本轮RSS上限；未迁移用户库/常驻应用。MF-P09后续入口整理已通过，见上段；P2–P5未启动。以下子门按其验收当时事实保留，不覆盖最新状态。

### 2.0 产品改造 P0 与 P1 准备（2026-10-19）

用户已授权古典/爵士主线和 legacy 兼容（ADR-019）。本轮新增可复现基线工具与计划，未改变音乐、Schema、API、数据库、四个风格入口或旧作品声音。真实历史验收导出包只读完整性检查、v1 JSON/投影与 headless 重新渲染结果见 [P0 实测报告](evidence/2026-10-19-p0-baseline.md)；本轮 provider requests/tokens=0/0。

25 条旧版边界回归通过。独立宿主 Chromium 已生成 30 秒 cold/warm/stem 与旧谱音频并记录 RSS；该证据不等于 pinned Docker Worker/数据库/UI 端到端复验，也没有证明主观钢琴音质、五分钟负载或资源节省。v1 占位音色、表达字段丢失、四 stem 游标、64 MiB 容量冲突与 canonical 事件顺序/hash 漂移已记录。P1 新音源/表达方案仍为待实施；下一最小 Task 是输出容量边界修复，随后 v1/v2 合同。

下文为已发布 v1 的当前能力与历史验收，不把历史四风格设计重新设置成新增主线。

当前可由用户实际操作的主路径是：

```text
Project Home → Brief → Parent Graph Planning → Plan Review/Adjustment
→ 人工审批 → 两个候选 Preview → 证据 Critic/至多一次 Repair → 显式 A/B 选择
→ 仅选中候选物化为不可变 Revision → 七步完整导出
→ 持久 SSE 进度/刷新恢复 → Arrangement Timeline → MP3 播放
→ 轻量 Timeline/Piano Roll/Mixer Draft → EditorCommand → 不可变 Revision/Undo/Redo
→ AI 有界选区 EditSubgraph → L0/L1 自动 Revision 或 L2/L3 Preview/HITL

或：既有 Project → 顺序导入多个 WAV/MP3/FLAC Stem
→ 每个文件独立权利确认/分析 HITL → 每次成功后刷新 Branch head
```

S3 已把 S2 的 API 级闭环变成用户可操作的作品流，S4/S5 加入四个 Style Pack、Theory 证据、双候选、Critic/Repair 和 A/B 人工选择，S6 加入轻量手工编辑与有界 AI 选区编辑，S7 再补齐正式 Export、Run Inspector、About/Eval 证据面和 96 条内部 Eval。当前已经达到个人作品集首版；负载、多租户和发布运维属于按需后置硬化，不再是默认活动阶段。

### 最新补充：测试精简与技术栈审计（2026-10-19）

MF-P15/P16/P17/P18/P21。已在下一生产实施阶段前完成用户要求的最小批次：删除6个门禁自登记/命令别名/过期文档位置测试、1过时UI断言，S7 gate去除重复Eval子集与OpenAPI前重复build。保留密钥隔离、启停/PID安全、缺陷回归、兼容/幂等/恢复/真实文件与PG；Compose测试显式空env文件，不读取真实.env。独立审查无阻塞。

同一root范围before38pass/2过期断言fail、8.81s；after34pass、7.91s；进程总计9.852→8.819s，但保留的慢停止测试自身波动0.69s，不宣称稳定提速。Ruff变更测试/bash语法/diff通过，未为文档重跑全suite。现有Python/TS/SQL分工与实际约束已核；不引入Java/Rust，先版本接线和必要profiling。见[审计及架构评估](evidence/2026-10-19-test-structure-architecture.md)。下一生产Task仍为A2.2，再B；新钢琴持久Undo/UI仍未验。

### 最新断点：P1-A2.2 生产动态导出（2026-10-19）

MF-P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。同一Parent Graph的显式export请求接通Run/Job/Outbox/Worker/权威读模型/API/界面；plan绑定Revision及实际轨道，可选MP3/stem，多次请求独立，旧v1七步保留。迁移0022/0023、请求body pin、sourceJob元数据身份、按物理键计额、manifest数据库pin、取消/恢复均有对应证据。

真实短单轨canonical5Jobs/2Bundles、8/9文件全下载校验、重开应用/checkpoint和重复事件通过；相关107 passed、Web4、Mypy116、Ruff/TS通过；一次审查及唯一修复复核关闭两类Important。见[完整证据](evidence/2026-10-19-p1-a22-production.md)。独立PG为后续B保留，共享服务不动。不是音乐v2/生产新钢琴/持久Undo验收；下一Task为B/C/D。以下旧断点按各自日期/Task保留，不代表当前生产仍未接动态导出。

### 最新断点：P1-C1 真实钢琴内部边界（2026-10-19）

MF-P02/P05/P10/P15/P16/P17/P18/P21。用户明确批准正常共享映像读写重挂与任务内官方7-Zip，均成功；原只读卷/解压/隔离PG资源阻塞已解除，以下2.0.1–2.0.4按各门当时事实保留。CC0/SFZ及26个实际WAV全部核验，固定manifest/样本hash、nonce+sampleId catalog和共享适配器生成4份真实30秒48k stereo PCM24。独立WAV检查通过，旧声音回退最大1LSB，原谱不变；没有音乐审美结论。

启动超限竞态已RED→GREEN修复，一次独立审查与唯一修复复核无剩余阻塞。最终audio/Worker55 passed、tsc/宿主build通过；真实隔离PG两条导出基线2 passed/1.18s，迁移头20260824_0021。进程树RSS采样最大约1.16GiB，非生产硬上限。精确回收44,824,612 logical bytes，删除自有PG/凭据，保留共享VM/历史服务。

真实钢琴仍只供内部probe，不是用户生产v2链路；持久IR/Job/Commands/Undo、API/UI/动态正式导出尚待A2.2/B。踏板/release-trigger未支持。最小测试结构精简已随后完成，见上节；不引入Java/Rust重写。见[证据](evidence/2026-10-19-p1-c1-real-piano.md)。

### 2.0.1 P1-A1 有界渲染容量（2026-10-19）

MF-P02/P15/P16/P17/P18/P21。producer、Worker配额估算、HTTP服务及Python adapter已按时长/采样率/声道/位深推导PCM上界，保留v1零额外tail与旧Job字段范围；显式拒绝超300秒、12轨、20k事件、96MiB输出或320MiB裸媒体预算。流式hash减少整WAV副本，补齐超时/取消/无效回执清理及重叠body单槽限制。

生产HTTP服务与Python校验提升的宿主headless实测：300秒、3轨/880事件、86,400,044 bytes，40.776秒；200ms采样本任务进程树RSS最大约2.15GiB（非物理峰值/生产RSS上限）。低预算400、实际超时504、建页取消/槽位释放/临时音频归零通过。API unit 552、音频TS 30、tsc/Mypy/Ruff通过，独立审查与一次修复复审关闭阻塞；provider=0/0。见[完整证据](evidence/2026-10-19-p1a-render-capacity.md)。

本轮未验DB/UI或pinned Docker，未测试12轨/20k事件最坏负载，也未完成五分钟完整导出Bundle。P1-A2动态导出/v1-v2合同、钢琴音源、表达与音质仍待实施；未下载样本、未改旧作品/声音、未停止共享VM。

### 2.0.2 P1 钢琴包合同与适配准备（2026-10-19）

MF-P02/P05/P10/P15/P16/P17/P18/P21。新增instrument-pack.v1语法/资源/样本hash+PCM格式校验、rootMidi与velocityzone选择、独立BufferSource释放适配；规划和调度均有复音/release硬界。踏板/release-trigger明确拒绝。仅测试和准备probe消费，v1 compiler、版本、aliases和用户作品不改，没有生产新音色入口。

自制builtin click的短OfflineAudioContext实测确认升八度约2.03频率比、力度翻倍能量比4、独立重击和末尾释放；它不是钢琴录音或音质证据。音频TS48条、tsc/宿主构建通过；一次独立审查暴露的非零起点最短gate浮点问题及探针NaN/描述字段问题已RED→GREEN关闭。provider=0/0，无DB/UI/VM。

FreePats KW small WAV归档4,551,289 bytes，26个WAV，已hash/列目录并隔离保留。此准备子门当时尚未读取包内CC0/SFZ；后续2.0.4已用现有bsdtar fast-read完成三文本核验，WAV仍因不支持过滤器阻塞。未放行真实音源、未安装7z。可选macOS7-Zip26.04归档1,861,928 bytes未下载运行，若用其解压WAV仍须明确工具批准；读取文本已不依赖新工具。原阶段[证据](evidence/2026-10-19-p1-piano-pack-contract.md)与最新[资源核查](evidence/2026-10-19-p1-source-storage-audit.md)分别保留。A2生产接线/B持久v2/审核catalog/真实钢琴A-B仍待实施。

### 2.0.3 P1-A2.1 动态导出内部合同（2026-10-19）

MF-P02/P05/P06/P08/P10/P11/P15/P16/P17/P18/P21。新增export-plan.v2、cursor/job/request v2与显式双读helper，按真实轨道请求stem及可选MP3；writer内部v2按plan hash/规范输入集合绑定幂等。仅支持现有builtin NoteClip，拒绝未审核外部音源，未激活Graph/Worker/Outbox/API/UI，音乐IR/Revision仍为v1。

自制PCM+已有FFmpeg真实文件边界为8/9/10逻辑文件，bytes/hash/重复复用/预设取消保留旧包通过；不是钢琴或canonical DSP验收。API unit561、Mypy5源、Ruff7文件通过，一次独立审查无新增Critical/Important；88合法/82错误cursor状态及v1七实体文件bytes对照通过。隔离PG未配置，真实集成2 skipped；迁移源码head=20260824_0021，未连接数据库。A2.2真实持久接线、B音乐v2双读/Undo/迁移与真实钢琴仍待验，7-Zip未批准未运行。见[证据](evidence/2026-10-19-p1-a2-contract.md)。

### 2.0.4 P1 音源许可/SFZ文本与PG真实存储阻塞（2026-10-19）

MF-P05/P10/P15/P16/P17/P18/P21。复用已隔离4,551,289-byte KW small包，系统bsdtar fast-read完整读取cc0/readme/SFZ（退出0、精确bytes和sha）。SFZ26 region覆盖MIDI21–108，12循环/14不循环、release0.6，未声明速度分层；只有文本验证，WAV仍因filter40202不可读，系统3.5.3和已有Conda3.7.7同样失败。没有兼容性manifest、真实钢琴渲染或音质验收；7-Zip未下载运行。

用户终端也复现Colima EROFS，已确认_lima链接到UnityWorkspace；该APFS sparsebundle映像实际以只读附加/挂载，而底层KINGSTON可写，文件flags/归属和空间不是已见原因。纠正先前单一sandbox归因，为什么映像被只读附加仍未知。未重挂共享卷、改权限或再启动VM；A2.2/B仍等隔离PG，普通共享卷弹出/读写重挂方案等待明确确认。见[事实与证据](evidence/2026-10-19-p1-source-storage-audit.md)。

### 2.1 浅色工作台与产品表达升级（2026-09-24）

S7 后呈现层切片，覆盖 MF-P01/P02/P03/P07/P11/P13/P15/P20 的用户可见部分。首页、Brief、计划审批、候选、Studio、导出、运行检查、导入、About 与 Eval 采用统一浅色系统与中文操作说明。主导航保留移动入口、当前页与跳至正文；Studio Dock 支持键盘切换并紧邻时间线，技术详情按需展开，试听明确区分保存版本和草稿。中文逗号/顿号可用于 Brief 列表输入；审批身份、确认说明及原有版本/恢复门未放宽。

README 已按产品、截图、启动、创作流程、Agent 架构、证据和边界重写，开发和 LangSmith 配置分别迁入 `DEVELOPMENT.md` / `LANGSMITH.md`；原深色视觉合同由 ADR-018 替代，不改变最终功能目标。

本轮验证：Web `82 passed`、TypeScript/Vite build、README 一键启停合同 `1 passed`；隔离示例数据浏览器检查通过桌面 1440px / 手机 390px 的 28 个页面与状态，覆盖空/载入/失败/部分可用、长标题、主导航、候选确认门与无页面横向溢出。README 四张截图明确标注示例数据。未修改 API、Graph、数据库、音频引擎、Worker 或依赖；未启动 Docker / Colima，未运行新的真实音乐生成或付费模型验收。

## 3. 能力矩阵

状态定义：

- `可运行`：已接入用户/API/Worker 运行路径，并有可复现验收证据。
- `内部完成`：代码、Schema 或测试已存在，但尚未形成用户可操作的生产路径。
- `部分完成`：只完成合同、Spike 或能力子集。
- `未开始`：仍仅存在于目标文档。

| 能力 | 状态 | 当前证据 | 主要缺口 |
|---|---|---|---|
| ArrangementIR、EditorCommand、Revision、Branch | 可运行 | 严格 Schema、事务写入、乐观锁、Studio draft/save 和不可变 Undo/Redo | 仍是轻量命令集，不冒充专业 DAW |
| CandidateSnapshot、PreviewCandidate、L2/L3 审批事务 | 可运行 | Generate A/B 与 Edit Preview Artifact、Critic/Repair lineage、原子 Revision 和 PostgreSQL 回放 | 广泛并发/故障矩阵按真实风险触发 |
| DeepSeek Provider | 可运行（限定API路径） | 旧宏观synth_ambient付费Plan、四风格Fallback/确定性策略；新P2.2专用钢琴语义真实Flash、持久请求/token预算、严格JSON/未知usage、官方endpoint | 旧宏观付费Planner仍拒绝classical/jazz；不能把默认UI/四策略说成四风格付费全通；真实调用受用户累计预算约束 |
| CompositionPlan Graph | 可运行 | Parent Graph v2、四风格 Fallback/Strategy、PlanApproval/Replan、双候选、Critic/Repair/A-B interrupt、EditSubgraph、PostgreSQL checkpoint | Legacy v3 仅保留回归 |
| Parent Graph Import/Generate/Edit/Recovery | 可运行 | 浏览器 Import/generate/edit、time-stretch、HITL、resume/cancel、持久 SSE 与刷新恢复 | 极端 checkpoint 矩阵按真实风险触发 |
| PostgreSQL/Redis/Celery/Outbox | 可运行 | Generate start/resume/cancel Dispatcher、权威 outbox、Compose readiness、幂等事件和恢复测试 | 长时负载/极端故障矩阵尚未测，按真实风险触发 |
| 受控音频上传与导入 | 可运行 | 单文件 Import 与同一 Project 顺序多 Stem；每项独立权利/错误并刷新 head | 自动 stem separation 明确不做 |
| BPM/key 分析 | 可运行的轻量基线 | FeatureArtifact、置信度与 HITL | 精度阈值尚无规模化 Eval 校准 |
| 保持音高 time-stretch | 可运行的受限基线 | FFmpeg atempo、Artifact lineage、恢复和质量测试 | 尚不是专业弹性音频；复杂 tempo map 不在首版 |
| Artifact 生命周期与 StoragePressureGate | 可运行 | 四态、配额、驱逐/重建、外置 Root | 暂不扩建通用缓存平台，按新 Artifact 类型增量接入 |
| Tone.js AudioGraphCompiler | 可运行 | ArrangementIR 编译/渲染、12 个语义 Preset alias、Web 只读 Timeline/Track projection、真实 MP3 Transport | Lite 音色仍投影到 3 个合成核心与 click sample；HQ 音色不属于 S4 |
| PatternSpec 与确定性 Composer | 可运行 | 四风格 Plan 策略、稳定双 seed Candidate、局部 Repair Snapshot、版本化 Plan hash、Parent Graph、共享 Export cursor 与有界 Edit Patch | 古典/爵士生成质量随 P1/P3 可听基线校准，主观质量未测 |
| 完整成曲与导出 | 可运行 | 四风格 Web Brief→审批→Revision→7 Jobs→Studio；Master/MP3/四 Stem/MIDI/Project/逻辑 Bundle | 用户路径仍固定四stem；A1已验5分钟WAV，A2.1动态合同仅内部；12轨/完整长曲Bundle未实测 |
| 四个 Style Pack 与 Theory Engine | 可运行 | 四个严格 `StylePack v1`、reviewed source/license snapshot、symbolic exemplar、Preset Palette、稳定 Theory rule/evidence、Web 解释与四风格 no-key 完整导出 | 当前为 Project-authored Lite 知识/音色；更丰富检索与 HQ Pack 非 S4 门槛 |
| Web Import Review | 可运行 | 上传、分析确认、试听、恢复、同 Project 多 Stem 与窄屏回归 | 更复杂的多轨编辑不属于 Import Review |
| Web Studio（轻量编辑） | 可运行 | Timeline/Piano Roll/Mixer/Library 面板、Draft/save/Undo/Redo、AI Edit/Preview、MP3 Transport、390px review-only | 更丰富专业 DAW 工具不属于个人作品集首版 |
| AI 选区编辑 | 可运行 | 有界上下文、EditPatchProposal/真实影响升级、锁定/非目标保持、L0/L1 自动提交、L2 Preview/HITL、重启恢复 | 付费 Edit planner 未验收；no-key fallback 只覆盖显式 gain/本地音色 |
| Export / Run Inspector | 可运行 | 权威七步 Export 投影、安全下载、最多 200 条脱敏 Timeline、决策/预算/Job/Artifact/恢复事实；重复读取不写库 | 大规模历史 Trace 与外部对象存储不属于首版 |
| Parent Graph 可视化 / 工作台可读性 | 可运行（作品集） | Generate-only `GET /runs/{run_id}/graph` 通过受限 `task_path` 读取器和静态展示注册表投影 `motif-forge-parent.v2`；Run 紧凑路径、Inspector 完整 Graph、并行候选/循环/Worker/人工节点与安全证据面板；Home recent-first、Brief 渐进披露、Run 结果优先、Studio 时间线优先 | 不是通用 Trace 平台；不读取 checkpoint payload/Prompt/推理；Import/Edit 保留事件时间线 |
| Eval/可观测性 | 可运行（作品集） | S1–S7 共 96 条内部案例、80 条公开 measured 分母、持久 Event/Trace/Usage、About/Eval 页面、一条历史 Generate paid 样本；可选 LangSmith 投影现关联 Parent Graph 与 DeepSeek transport，并默认关闭、输入/输出隐藏、失败开放 | 主观音质、长时负载和 Celery/FFmpeg/Chromium 完整分布式 Trace 明确未测 |
| 一键本地启停 | 可运行 | `scripts/start_motif_forge.sh` 统一外置存储、Docker/Colima、Compose readiness、Vite 与浏览器入口；`scripts/stop_motif_forge.sh` 完整停止 Web、Compose 和 Colima，同时保留 Volume/镜像/作品；Shell/契约测试覆盖 PID 防误杀与幂等边界 | 2026-08-31 同机 live startup 已通过；现有 stopper 会关闭默认 Colima；共享 VM 下暂不使用，P1 独立修复；不清理未知占用者 |
| CI/CD 与负载测试 | 后置可选 | 精确本地 S7 gate、确定性报告、PostgreSQL 与浏览器代表性验收 | CI workflow、soak、正式容量 P95 在公开托管/多人使用前再做 |

## 4. 当前验证基线

2026-09-01 可选 LangSmith 开发可观测性纵切：

- Graph/Provider/API/配置/Compose/launcher 聚焦门为 `81 passed`；排除外置盘 AppleDouble `._*` 的临时代码副本完整 unit 为 `521 passed`；Ruff 通过，Mypy strict `112 source files` 通过，Compose `--no-env-resolution` 配置验证与启动/停止脚本语法通过。
- API、Dispatcher、Resume Dispatcher 可在同时设置 `LANGSMITH_TRACING=true` 与 Key 后启用；Migrate/Media/Render/Storage 不接收真实 Key。SDK Client 和 Compose 双边强制隐藏 inputs/outputs，trace 只接收 allowlist 关联 ID、操作、时序、脱敏错误、finish reason 与 token 计数。
- PostgreSQL checkpoint、Run events、Usage ledger 和内置 Graph Inspector 继续是权威事实；LangSmith 故障不会让 Graph/Provider 操作失败、重试或重复。本纵切没有数据库/API/Graph 拓扑变化，没有 DeepSeek 或 LangSmith 网络/付费调用；Celery/FFmpeg/Chromium 分布式 trace 保持后置。

S7 阶段门的最新证据：

- Python unit `494 passed`；全阶段 Eval `36 passed`；S7 contract/report focused `6 passed`；Web `67 passed`。
- 真实 PostgreSQL Export、Inspector、Dispatcher 三个代表性边界 `3 passed`；Export 为 7 steps/13 files，Inspector 对已有成功 Run 投影 7 Jobs/6 Artifacts。
- Ruff、Mypy strict `107 source files`、Vite production build、OpenAPI generation、确定性 Eval 报告与 `git diff --check` 通过。
- Eval inventory 正好 96 条内部案例；公开 measured 分母 80，另列 13 个 expected reject 与 3 个 not measured；报告生成用量为 `0 request / 0 token`。
- Chromium 真实读取 `/about`、`/evaluation`、一个 Run Inspector 和一个 ready Export；桌面与 390px 无横向溢出。新的完整 no-key Run 因测试环境混用了旧 S6 dispatcher 而停在 `materializing`，未伪报为 S7 端到端成功，并在诊断后通过公开 API 正常取消；S2/S5/S6 已有完整 no-key 队列证据仍有效。

S6 阶段门的最新证据：

- Python unit `485 passed`、S6 Eval/contract `8 passed`、真实 PostgreSQL Edit/Dispatcher/SSE `5 passed`；Web `58 passed`。
- Ruff、Mypy strict `101 source files`、Vite production build、OpenAPI generation 与 `git diff --check` 通过。
- 12 条 S6 Eval 覆盖 L0/L1/L2 路由、锁定/非目标/冲突、重复 resume 与 no-key fallback；未量测的主观音质不伪报通过。
- no-Key 公共 API/真实队列 smoke 完成手工 Revision/Undo、L0 自动 Revision、L2 真实 Preview Artifact/审批 Revision，provider requests/tokens 为 `0/0`。
- 真实 PostgreSQL 重启边界复现并修复同一嵌套 EditSubgraph 的连续 worker/HITL interrupt；同一 outbox 重投后 Run 从 `waiting_edit_approval` 到 `succeeded`，无新增模型调用。
- Chromium 从当前 Branch HEAD 完成 Clip 选择和 AI 编辑，刷新后保留 Revision；桌面与 390px 无横向溢出，移动端保持 review-only。

S5 阶段门的最新证据：

- 集中 Python unit/eval/contract `517 passed`；真实 PostgreSQL Candidate/Preview/Parent Graph/SSE `8 passed`；Audio/Render `13 passed`、Web `46 passed`。
- Ruff、Mypy strict `94 source files`、Audio/Web build、OpenAPI generation 与 `git diff --check` 通过。
- 12 条 S5 Eval 覆盖四种风格各两例，以及 repair improved、non-improving、restart replay、reject/cancel；Repair 严格限制为至多一个子 Snapshot。
- no-Key 公共 HTTP/Graph/真实队列 smoke 精确得到 `2 candidate families / 3 snapshots / 1 repair child / 2 selection previews / 1 selected Revision / 7 Jobs / 6 Audio / 1 Bundle / 0 request / 0 token`，并核对协议要求的 Artifact checksum 与单一 Revision/Media Run/source Job lineage。
- 真实浏览器从 Brief、PlanApproval、A/B 逐一试听、选择 B 到只读 Studio 走通同一事实计数；页面在 390px 无横向溢出，候选播放保持单一 audio 元素。
- 运行态验收只修复三个真实当前路径问题：Candidate Preview Media Run 未进入 Parent dispatcher、Worker resume 未按 AI Run 重建完整 S5 Graph、60 秒 fallback 的小节取整超过策略时长容差；均有 RED/GREEN 与 PostgreSQL/浏览器复验。没有调用付费模型，也没有扩充 S7 负载/极端并发矩阵。

S4 阶段门的最新证据：

- 集中 Python unit/eval/contract `482 passed`；真实 PostgreSQL物化回放 `1 passed`（阶段实现时同文件完整门 `12 passed`）；Audio/Render `13 passed`、Web `41 passed`，Ruff、Mypy strict `89 source files`、Vite build、OpenAPI generation 与 `git diff --check` 通过。
- 八条代表性生成 Eval 覆盖每风格两例；另有未知风格和未审核知识拒绝，模型文本不能直接决定音符合法性或许可。
- 独立 Compose no-key 运行态中，Synth Ambient、Minimal Electronic、Classical Chamber、Jazz 均经公开 HTTP/PlanApproval/Parent Graph 得到 `1 Revision / 7 succeeded Jobs / 6 Audio / 1 Bundle / 0 request / 0 token`；容器内六个实体 checksum 与数据库 lineage 一致。
- 阶段只修复真实主路径暴露的两项跨服务问题：Render Worker 使用与 Media Worker 相同的非 root UID 写共享 temp；Jazz swing 保持同一 chord attack 成组且每个 Clip 事件单调。未扩展 S7 故障、负载或多租户矩阵，也未调用付费模型。

S3 最终门的最新证据：

- Python unit + S3 contract：`415 passed`；Audio `13 passed`；Web `41 passed`；Ruff、Mypy strict `85 source files`、Vite build、OpenAPI 双生成一致与 `git diff --check` 均通过。
- 专用空测试库上的 Compose runtime：真实 PostgreSQL integration `59 passed / 1 Redis+Artifact opt-in skipped`；API、Dispatcher、Resume Dispatcher、Media/Render Worker、PostgreSQL、Redis 与 migration head 均通过。
- no-key Chromium 主旅程：父 Plan 与子 Replan 各 1 个且旧 Plan 可读；批准子 Run 得到 `1 Revision / 7 succeeded Jobs / 6 audio / 1 Bundle`，delivery MP3 为 `2,426,924 bytes` 并实际开始播放。
- 同一浏览器旅程在 390px 的 Run/Studio/Project reopen 无页面级 overflow；两个 Stem 进入同一 Project 后 Branch head 连续推进两次；provider requests/tokens 均为 `0/0`。
- S3 没有修改 provider prompt、structured output schema 或 planner 构造，因此未触发新的付费调用；S2 的一次预算受控 live acceptance 仍是当前 provider 证据。

S2 Task 12 最终门后的最新证据：

- 集中 Python gate：`440 passed / 56 integration-only skipped`；最终修复聚焦 suite `152 passed / 7 integration-only skipped`，真实 PostgreSQL恢复/Dispatcher/Parent Graph `8 passed`。
- 当前 Compose runtime 已迁移到 `20260813_0016`；最终无付费运行时 gate 为真实 PostgreSQL integration `57 passed / 1 Redis+Artifact opt-in skipped`，API/Dispatcher/Resume/Media/Render/PostgreSQL/Redis 合同通过。
- Task 10 权威 SQL 主路径精确得到 `1 Plan / 1 Candidate / 1 Revision / 1 receipt / 7 Jobs / 6 audio / 1 Bundle`；重复 start/Master completion 不增加事实，取消和错误 lineage 不产生越权副作用。
- Task 11 Eval 为 16 条（6 valid、3 unsupported、3 malformed、2 approval、2 recovery），包含 S1 fixed sample 与 Parent baseline；确定性 Compose smoke 得到 `7 Jobs / 6 audio / 1 Bundle / 0 model calls / 0 tokens`。
- Audio `13 passed`、Web `15 passed`，Audio/Web build 与 OpenAPI 确定性生成通过；Ruff 通过，Mypy strict `82 source files` 通过，`git diff --check` 通过。
- Task 12 v1 在单请求 2,400 output cap 下只得到 reasoning，记录 4,135 tokens 后安全进入 fallback，未物化 Revision/Job，不计验收成功。修复后固定 v2 Run `3de2a947-6118-45d8-ae7a-f829ef7bc0a0` 以唯一一次 DeepSeek V4 Flash 请求、4,911 known tokens、无 fallback 完成；最终为 1 Plan/1 Revision/7 succeeded Jobs/6 audio/1 Bundle，六个实体文件 checksum 与权威 lineage 一致，`cost_status=unknown` 未伪造费用。Key 随后撤下。

上一份完整跨栈审计（2026-08-12）仍提供 Audio/Web/Compose 基线：

- Python（非 integration）：`205 passed / 21 integration-only skipped`。
- 真实 PostgreSQL 集成：`21 passed / 1 Redis+Artifact opt-in skipped`；其中 S1 专项 `6 passed`，包含执行前/运行中取消、promote/completion 竞态、分歧重复 completion 清理与容量门合同。
- TypeScript Audio Engine/Render Worker：`13 passed`。
- Web：`15 passed`。
- TypeScript strict 与 Vite production build：通过。
- Ruff：通过。
- Mypy strict：`73 source files` 通过。
- Compose：API、Dispatcher、Resume Dispatcher、Media Worker、Render Worker、PostgreSQL、Redis 运行；API 与 Render readiness 均为 ready。
- 当时的运行镜像迁移 head 为 `20260812_0012`；S2 代码/测试数据库已推进到 `20260813_0016`，运行镜像将在后续明确的 S2 Compose 门刷新。

跳过项必须继续保持显式 opt-in，不能用 SQLite 或隐式本机凭证伪造 PostgreSQL/Redis 集成结果。

## 5. 已确认的设计漂移与技术债

### 5.1 单一生产 Parent Graph 已成立

API/Dispatcher 只把 `motif-forge-parent.v2` 作为生产拓扑，`generate` 复用共享 Planning Subgraph；`motif-forge-plan.v3` 仅保留旧 checkpoint 回归 wrapper，不是第三个生产 Graph。后续 S3/S5/S6 继续扩展同一 Parent Graph，禁止复制生成编排。

### 5.2 音频可靠性领先于创作主链路

Import、Artifact、恢复和容量治理已达到较高完成度，S5 已证明四风格 Plan 上的 `two Candidates → Critic/Repair → A/B → Revision → Render → Bundle → Studio`。继续暂停通用存储/恢复平台扩建；下一产品门是 S6 手工编辑与 AI 选区编辑。

### 5.3 前后端 DTO 仍由手工维护

Project、Run 与 Studio 的公开 DTO 已进入 Pydantic/OpenAPI → TypeScript 生成边界；`apps/web/src/shared/api.ts` 仍保留 Import/Artifact 的窄手写运行时解析。后续只在触达具体 API 时增量迁移，不单独发动前端 API 全量重写。

### 5.4 大文件按触达拆分

`api/app.py`、Persistence、Provider 与 Graph 已出现多个 500–900 行文件。不安排独立“大重构阶段”；下一纵切触达某个文件并新增第二项职责时，先保留测试再提取该纵切所需的 Router、Repository 或 Subgraph。禁止顺手改写未经过的模块。

### 5.5 Eval 建设过晚

S1 已形成 20 条可重复的确定性创作/渲染 Eval。S2 剩余工作不再要求每个工程 Task 都单独扩充 Eval；Task 11 集中建立至少 16 条 Generate 代表性案例，之后随四个 Style Pack 和 AI 编辑扩展到首版要求的 96 条。功能 Task 仍须为新创作行为或新失败路由提供至少一个可回归样例，但可以先放在窄测试中，到阶段 Eval 门再统一入库。

### 5.6 当前开发采用作品集工程模式

S2 Task 1–5 的多轮审查证明了核心数据边界，但也产生了明显的重复验证成本。从 Task 6 起按 ADR-016 执行：保留单一 Parent Graph、DeepSeek/Fallback、HITL、原子 Revision、完整导出、持久恢复、代表性 Eval 和真实付费验收；把极端并发矩阵、所有历史 populated downgrade、全量负载/P95、多租户和无上限复审移到 S7/后置硬化。

这不是把系统降成 Demo。当前 Task 仍需 TDD、窄单元测试、一个真实 PostgreSQL/跨服务边界、结构化错误与费用事实；每 2–3 个 Task 做组合回归，S2 结束做完整 Compose 与 live gate。只有不影响当前用户主路径、数据/Secrets、模型费用、HITL、幂等与恢复的非核心问题才可登记后置。

## 6. 版本治理状态

`G0` 已完成：原先跨多个纵切的 48 个修改项和 65 个未跟踪项经逐项盘点后，以一个保持跨服务一致性的里程碑提交 `6bf21f5`（`feat: complete durable audio import web slice`）推送到 `origin/main`。没有提交 `.env`、API key、用户音频、Artifact bytes、dist、node_modules、Python/工具 cache 或 AppleDouble sidecar。

Checkpoint 前复验：Python `152 passed / 13 opt-in skipped`；真实 PostgreSQL `13 passed / 1 Redis+Artifact opt-in skipped`；Audio `6 passed`；Web `15 passed`；Ruff、Mypy strict、Vite build、Compose runtime contract 和 readiness 均通过。Checkpoint 推送后工作区为 clean。

后续每个可独立验收纵切都必须形成 Git checkpoint，不再跨多个阶段积累未提交业务代码。

## 7. S1–S7 验收事实与当前开发断点：发布维护

S1 已完成：固定作品为 24 bars、80 BPM、4/4、C major、四轨、72 秒；固定 seed 生成完整 ArrangementIR。L3 生成先创建 Candidate/Preview，再由调用者提供 16 字符以上审批断言，事务持久化 actor、审批 payload hash 和原始五条生成命令后物化 Revision。正式 Job 链输出 PCM24 Master（20,736,044 bytes）、四条 PCM24 Stem、经 FFprobe 验证时长/格式/码率/非静音的 256 kbps MP3、MIDI、Project JSON 与 credits/license/provenance/trace/export manifests。

最终新容器/新 `/temp` 挂载真实队列复验为 Project `af988445-9123-40f6-81bf-7a6bcc037099`、Revision `f49b820e-0e56-4038-9108-a72cdc3affa5`、Run `c713a239-d169-4c02-836f-ec20ad657c3e`、Bundle Artifact `86d18388-1159-4c76-83ed-ffc317948007`；逻辑 Bundle 只保存 13 个校验项与音频 Artifact 引用，自身占 `59,396` bytes，不复制约 100 MB Master/Stem/MP3。Worker 会从数据库 Revision 重新编译 AudioGraph并拒绝不匹配 payload；`audio-artifact.v2` 结构化保存 Revision/Arrangement/render scope，转码和 Bundle 均拒绝跨 Revision 输入。Render/Transcode/Bundle 均先过会计入显式 temp root、真实目录与有效 Job lease 的 StoragePressureGate；跨挂载提升先复制到最终目录的唯一 partial、复核 bytes/hash，再在 Artifact 文件系统内原子 rename。运行中显式取消会中断协程/FFmpeg、清理新建但未登记的输出并阻止迟到/分歧 completion；Chromium 客户端断连会关闭页面并清理一次性 sink/partial；MP3 还拒绝 `max_volume <= -80 dBFS` 的数字近静音。

历史 S1/S2 记录中当时定义的后续业务纵切是（非当前断点）：

> **S7：把已有完整导出和 Agent/编辑闭环产品化为可公开演示的作品集，并补齐 96+ Eval、Run Inspector、必要可观测性与风险驱动硬化。**

S2 仍不得绕过 PlanApproval，也不得创建第三个生产 Graph。S1 的固定策略继续作为无模型降级和回归基线，不改变首版最终要求的 1–5 分钟、最多 12 轨、最多 2 个候选和四个 Style Pack 同时交付。

S2 实施计划 Task 1–5 已独立复审通过：

1. PostgreSQL AI Run、Plan、审批、Event、真实 usage 与请求预算；
2. 可复用且无审批/持久化副作用的 Planning Subgraph；
3. DeepSeek V4 Flash 安全 Provider 合同与持久预算（仅 MockTransport，未付费调用）；
4. Synth Ambient Plan 策略、确定性编译器和 v1/v2 Plan hash 兼容；
5. 原子 `approved Plan → Candidate/Preview → Revision`，包含 receipt、取消/并发/回放和 legacy fail-closed。

Task 6 已把 S1 的完整导出链抽为共享应用服务：严格七步 cursor 依次 enqueue Master、pad/melody/bass/rhythm Stem、MP3 与逻辑 Bundle；首个 Job 创建唯一 MediaRun，后续 Job 复用同一 Run。每次 enqueue/collect 都重新加载权威 Revision/Artifact，校验 Arrangement hash、render scope、track、quality、availability 与 source Job；cursor 只接受一致的有序前缀，重复 completion 不推进第二次。S1 smoke 已删除第二套 payload 构造并复用该服务。

Task 6 验收为 focused unit `12 passed`、真实 PostgreSQL `1 passed`、Ruff、目标 Mypy、S1 script compile 与 `git diff --check` 通过；独立审查经唯一修复复审后为 `Spec PASS / Quality APPROVED`。本 Task 没有修改 Worker/Artifact/取消合同，没有重跑 S1 故障矩阵、Docker 或 DeepSeek API。

Tasks 7–11 已依次完成 Parent Graph v2 Generate 挂载、权威 Dispatcher、REST/SSE、真实 PostgreSQL 恢复/取消/lineage 组合验证、16 条代表性 Eval 与无付费 Compose smoke，且各自形成 Git checkpoint并通过有界独立复审。

Task 12 已完成：预付费保护使用固定 Project/Run/resume 数据库幂等身份，v2 账本上限为一次 provider 请求和 12,000 tokens；严格核验 Plan v2、审批与 Artifact lineage。真实 v2 Run 在审批后曾暴露两个确定性问题：Plan section function 超过 IR 80 字符边界，以及 approval checkpoint 已推进后 outbox 重投未继续执行。二者均经 RED/GREEN 修复，同一 Run 在 Key 撤下后恢复且没有新增模型调用，最终成功导出。

S3 已完成 Project Home、Brief validation、Plan Review/Approval、immutable child Replan、持久 Run 进度、只读 Arrangement Studio、真实 MP3 Transport、Artifact 四态、390px 审阅以及同一 Project 顺序多 Stem。确定性 browser smoke 从公开 UI 完成整条路径，并用只读 PostgreSQL 事实核验 7 Jobs/6 Audio/1 Bundle；没有第三个 Graph、直接 Revision 写入或付费模型调用。

S4 已完成四个 reviewed Style Pack、稳定 Theory error/warning/advice 证据、四个确定性策略和 Web 风格/来源/许可说明。四风格均通过公开 HTTP → Parent Graph → PlanApproval → Revision → 七步队列导出；每条路径为 7 succeeded Jobs、6 Audio、1 Bundle，provider requests/tokens 为 0/0，物理 checksum 与单一 Revision/Media Run lineage 一致。Compose 验收还真实发现并修复了 Render Worker 与 Media Worker 共享临时文件的 UID 不一致，以及 Jazz chord swing 造成的非单调事件调度。

S5 已完成两个稳定 Candidate family 的 fan-out/fan-in、真实候选 Preview Job、结构化 Critic、至多一次局部 Repair、两个最终 Preview 与显式 CandidateSelection interrupt。选择前不写 Revision；选择后只物化一个 Revision 并复用七步导出。重启/重投、reject/cancel、非改善终止和 no-Key 费用事实均有测试；CLI 与浏览器运行态都得到 2 families、3 snapshots、2 previews、1 Revision、7 Jobs、6 Audio、1 Bundle、0 request/0 token。

S6 已完成轻量 Studio Draft、不可变 Undo/Redo、严格 EditRun/EditPatchProposal、同一 Parent Graph v2 的 EditSubgraph，以及 L0/L1 自动提交和 L2/L3 Preview/HITL。no-key Compose/Chromium 与真实 PostgreSQL 连续 interrupt 重启恢复均已通过，未执行新的付费模型调用。

**当前断点（2026-10-19）：S7 历史封板保持，P0 产品基线/合同同步与 P1 钢琴准备已获用户授权。** 保留 Parent Graph、审批、不可变 Revision、费用/恢复和旧四风格兼容；后续产品工作按 ADR-019 和 P1 计划逐纵切进行，不启动全部 P2–P5。资源与真实旧工程证据的具体覆盖/未测边界见 P0 报告。

具体前后顺序、阶段门和优化规则见 `NEXT_DEVELOPMENT_ROADMAP.md`。
