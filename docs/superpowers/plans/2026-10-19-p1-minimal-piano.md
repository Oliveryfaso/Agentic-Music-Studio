# P1 最小钢琴纵切：明确版本、真实声音、可逆表达

日期：2026-10-19（Asia/Shanghai）。状态：原始P1方案；A1容量与独立包合同准备子门已有证据，**真实钢琴产品功能尚未完成**。Stage：P1；覆盖 MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21；MF-P09 的古典/爵士新建入口调整在本阶段明确单独交付，不删除 legacy 风格。

执行模型：按用户指定 GPT-6.1 Sol / xhigh。采用 ADR-016 的有界纵切节奏；一次 Task、一份证据、一个本地 checkpoint。P0 报告中的未测项不得因本计划存在而转为完成。

## 用户结果与范围

用户打开一份新建的 30 秒钢琴测试谱，显式选择钢琴音源，调整力度和二态延音踏板，在同位置比较原版/表达版，接受或撤销后重开仍保持对应声音。原有 v1 工程默认沿用 v1 声音；升级是用户触发、带 Preview 的新 Revision。

固定 PPQ=480、单一 BPM、4/4、单钢琴、一份自制短谱（无外部作品版权，30 秒内末 2 秒显式休止并完成踏板释放/尾音）、原有最大 12 轨合同不扩大。P2 才加入经典谱导入、反复展开与丰富编曲。P1 不做复杂 tempo map、半踏/物理共鸣、全 SFZ 解释器、VST、专业交响、多 Agent 扩张、付费模型验收。

## 已确认的起点和风险

- `_track_spec` 将 `builtin:jazz-piano` 映射 `warm_pad`；violin→glass_pluck；pizz-cello/brush-kit→click。这些是 v1 占位声音，不能直接改映射。
- NoteEvent 已有 articulation/cents，但当前 AudioGraph v1 不传；不存在 pedal 表达合同。Clip gain/pan/fade 在该投影也未消费。v2 若遇暂不支持的非默认参数，应显式拒绝或告知，不能默认当已生效。
- `CanonicalRenderJobPayload` 和 `CandidatePreviewJobPayload` 的 engine 字段是 v1 Literal。改 TypeScript 常量还不够；应用投影、Job、Worker 验证、recipe、版本引用、API DTO 都要接通。
- `_revision_from_row`/candidate readers 直接调用 `ArrangementIR.model_validate_json`，命令 `_replace_track` 等直接调用 v1 `model_validate`。v2 双读与命令重建必须一起覆盖；只加 schema 类会让新工程保存后读不回或编辑后降级。
- 30 秒重复渲染可差 1 个 PCM24 LSB；不能靠 SHA 完全一致证明音频兼容。canonical JSON 重排会改变图 hash；本固定谱两种顺序的音频最大差异为 1 LSB，但其他谱尚未证明。
- 五分钟 PCM24+44 byte header 为 86,400,044 bytes，当前 limit=67,108,864。输出容量修正是独立、优先的 P1-A Task。

## 接口和版本：先冻结这些，再写功能

| 生产者 → 消费者 | 拟定合同 | 不可违反的边界 |
|---|---|---|
| 旧 JSON/数据库 → 领域层 | 现有 `ArrangementIR` 作为 v1 保留；新增 `ArrangementIRV2` 与显式 discriminator reader | 缺 v2 版本不自动升级；v1 canonical bytes/hash 不变 |
| v2 Revision → renderer | v2 在不可变快照内含 `render_profile` 与 `performance_plan`，都参与 content hash | 禁止放入可变旁路字典或只靠前端状态记声音 |
| render profile →音源库 | `render-profile.v1{engine_version, instrument_pack_id, instrument_pack_version, manifest_sha256}` | 必须绑定确切音源；缺失时 `INSTRUMENT_PACK_UNAVAILABLE`；无 silent fallback |
| 乐谱 note_id →演奏 | `performance-plan.v1`：track/clip/note 的 ID、`onset_offset_tick`（-60..60）、可选 velocity_override（1..127）、可选 gate_duration_tick（1..9600），track pedal events（tick,value=0或127） | ID 必须存在；起音不早于 0；gate 在输出预算内；事件数/复音有硬上限；原谱不随随机 humanize 改写 |
| 音源 manifest →共享 TS 引擎 | `instrument-pack.v1`：来源/作者/CC0 文本引用、版本、文件 hash/size、rootMidi、key/velocity 区间、loop 与 release 参数 | 仅审核本地文件；路径不得越出包；不让 URL 变任意下载/文件读入口 |
| v2投影 →浏览器/Worker | `audio-graph-spec.v2` + `motif-forge-audio-engine.v2`；新 `multisample` track；明确奏法、detune cents、pedal 处理后的发音事件与音源 ID | v1 compiler/validator 保留；unsupported engine/version fail closed |
| renderer → Artifact | 音源/表现计划/engine/quality/范围 hash 固定进 recipe 与 lineage | 错版本不命中缓存；原有 v1 Artifact 不覆盖 |
| Revision/导出请求 → cursor/bundle/read API | `export-plan.v2` + `complete-export-cursor.v2` + `export-bundle-job.v2`，步骤来自固定 Revision/实际 track IDs/显式格式请求 | v1 七步/四 stem 旧任务照常恢复；v2 不伪造四个角色补齐导出 |
| UI →服务器 | 原有有界 EditorCommand + 新表达命令；显式 upgrade 命令产生 v2 候选 | L2 Preview/HITL；锁定区/实际 diff；审批后原子 Revision，支持 Undo |

`ArrangementIRV2` 先复用 v1 的固定速度/拍号限制，仅增加明确表达与 render profile。所有读入口使用版本分派，命令重建使用保持版本的 reader；不要通过扩大旧 Literal 或统一补默认字段让 v1 序列化悄悄变化。版本化实现细节应在 Task B 开始时补到 DOMAIN/WORKER 专项合同。

现有数据库 Revision JSONB 可以存新快照，但旧客户端不能读 v2。必须提供前向部署顺序和 downgrade guard：先上双读 Worker/API，再允许创建 v2；有 v2 rows/checkpoints/recipes 时禁止退到只读 v1 的版本。若需要 capability marker/DB constraint，使用新的 Alembic migration（当前 head 应重新查询，不能猜 revision ID）；没有 SQL 列变化也要记录 JSON 兼容迁移与回退策略。不能把“JSONB 无需加列”解释成“无需迁移方案”。

## 具体小型音源候选（已隔离小包，尚未准入）

FreePats Upright Piano KW **small SFZ WAV**：官方页面标 CC0、4.3 MiB 下载 / 10 MiB 展开。精确链接：`https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-small-SFZ-20190703.7z`。页面上层显示 2022-02-21，但 small 文件名为 20190703，必须分别记录，不能伪称是完整 2022 两力度层包。

来源：[FreePats 官方条目](https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html)，本轮核实 2026-10-19。采样录制人员/许可以归档中的具体文本为准；目前确认网页CC0、4,551,289-byte归档SHA256/目录（26WAV），包内许可与root/loop/力度层仍待检查，见2026-10-19包合同证据。系统bsdtar可列目录但不能解其过滤器；未安装新工具，不放行真实manifest。**小包的力度层数量尚未核实**；若单层，只能先证明力度包络/演奏变化，不能宣传多层真实钢琴或真实半踏。

Task A/B 可在没有样本时完成。Task C 下载前如平台需要许可证接受/权限确认，应一次说明具体文件、4.3 MiB 上限、CC0 用途和外置目标；不扩大到 69 MiB/1 GiB 包，不安装 7z 软件。先检测本机已有解压能力；无能力时停止资产 Task，其他任务可继续。

## Task A：修正输出容量与共享 VM 停止边界

这是两条独立可审查修复，可分别 commit；不会改音乐或历史作品。

Files：`application/rendering.py`、`domain/media_jobs.py`、`audio/chromium_render.py` 及相关测试；`scripts/stop_motif_forge.sh` 与 `tests/test_local_launcher_contract.py`。若为减少范围，可先只做容量，默认 Colima 继续不使用现有 stopper。

1. RED：新测试 `test_five_minute_pcm24_payload_capacity`、`test_preview_intermediate_capacity` 断言精确 bytes 与 bounded allowance；验证峰值 temp 空间估计纳入 StoragePressureGate。Expected：64 MiB 现状失败。
2. GREEN：用纯函数按 ceil(frames)×channels×bytesPerSample+header 计算，含明确尾音策略与硬上限，不按猜测添加无限余量。Canonical 2GiB/Candidate 512MiB的旧序列化字段范围保留；A1已实现执行前按render-capacity.v1推导并clamp，不能混淆两个schema上限。Preview 中间件也是 PCM24，不能按 MP3 大小估算。
3. RED/GREEN：默认 stopper 只停止项目 Web/Compose，Colima 只能显式 opt-in，且明确共享 VM 影响；替换旧“必须停 Colima”的 mock 断言。测试全部用 fake binaries，真实 Colima 不启停。
4. 窄测试：`pytest -p no:cacheprovider services/api/tests/unit/application/test_rendering.py services/api/tests/unit/audio/test_chromium_render.py tests/test_local_launcher_contract.py -q`。Expected：新边界与旧用例通过。新测试文件名应在实际写入后加入精确命令，不能只跑旧测试。
5. 真实边界：一份五分钟 canonical WAV 成功、超出配额有结构化失败、取消清理；只在接受的 render profile 和必要 Worker 下跑，不启动 UI/模型。

## Task A2：单钢琴可完成的版本化导出（P1 必需，不能延后到 P2）

独立审查确认：现有 `_track_id_for_step` 会在缺少四角色轨时拒绝；`ExportBundleJobPayload` 强制 6 个音频/4 stems。若只做新钢琴，P1 最终导出会被阻塞。本任务先用已有 v1 单轨测试谱验证新导出合同，不依赖 Task B/C 的新引擎；P2 才扩更丰富编制。

Files：`application/generation.py` 的 export services、`application/exporting.py`、`domain/media_jobs.py` 的 Bundle schema、Worker bundle handler、Parent state/cursor reader、`infrastructure/persistence/export_reads.py`、Export API/DTO 与前端 Export 页面。准确文件以 Task 开始的 `rg` consumer scan 冻结；不能只改 EXPORT_STEPS 常量。

1. RED：单轨单声部 Revision 请求 Master+MP3+MIDI/manifests 时，旧四角色路径应复现失败；新增 `test_single_piano_export_without_stems`、`test_one_requested_stem_is_revision_bound`、`test_legacy_seven_step_cursor_still_resumes`。后续测试不得靠补三条空轨冒充单钢琴导出。
2. GREEN：新增显式 `export-plan.v2`、`complete-export-cursor.v2`、`export-bundle-job.v2`；计划绑定 Revision hash 与真实轨道列表。默认不建 stem Jobs；显式请求只导出选定的单钢琴 stem。允许的格式/步骤和输入计数由该版本计划推导，严格验证，不接受任意 step 字符串或动态路径。
3. 保留旧 v1 七步 cursor/6 音频/4 stem Job 与 checkpoint reader，按版本恢复，不能把活跃旧 Run 重新解释为 v2。所有流程仍经同一 Parent Graph/Application/Outbox；不新增第三套导出 Graph。
4. Bundle/manifest 的期望文件集与 lineage 来自实际计划；不再对 v2 使用固定 13 files/7 steps 的 readiness 判断。更新 API/Export UI，缺 stem 不算缺文件，未请求 stem 不是失败；保留旧 UI 读模型回归。
5. 真实边界：一条实际单轨 Revision 完成 master-only 音频交付和显式单 stem 两种请求；MIDI/project/credits/license/provenance/trace checksum 完整。重复完成/刷新不创建额外 Job。新增内容按需产生，不能为达到成功状态重新后台生成四 stem。
6. 窄检查：generation/exporting/bundle/export reads 的相关 unit 与新测试；一个隔离 PostgreSQL + Worker 边界。只修单琴导出所需接线，不在本 Task 实现全 DAW 导出选项或 P2 曲库。

## Task B：v1 保留与 v2 乐谱/演奏合同

Files：`domain/ir.py` 或相邻 `performance.py`、`domain/revisions.py`、`domain/commands.py`、`domain/canonical.py`、`application/rendering.py`、`infrastructure/persistence/database.py`/candidate readers、相关 Job schema；专项 DOMAIN/WORKER 文档与迁移说明。

1. RED：保存 P0 v1 fixture 的字节/hash 与 AudioGraph golden；测试 v1 dual reader 原样读写。新增 `test_v2_performance_roundtrip`、未知版本/悬空 note/重复 ID/负起音/越界踏板拒绝；`test_v2_command_keeps_version_and_expression`；v1 预期保持通过，v2 当前失败。
2. GREEN：实现上表最小合同、显式读分派、v2 commands、hash 与版本校验。默认生成器仍输出 v1，除非明确选择 v2 piano profile；旧 aliases 不修改。
3. 当前 canonical 列表重排仅在 v2 投影中统一稳定发音排序（time、track/clip/note ID 作为 tie break），不得改 v1 内容哈希算法。正序/倒序输入应得到相同 v2 projection hash；旧 golden 不变。
4. 真实 PostgreSQL 边界：新 v2 Revision 写入/读回/命令/Undo，保留 v1 parent；unsupported downgrade 被拒绝。用隔离 test DB 与显式 test settings，不读取用户 `.env` 或升级用户库。
5. 数据仍未接声音时只标“合同子门通过”，不标钢琴能力完成。

## Task C：音源 manifest 与共享真实钢琴渲染

Files：`packages/audio-engine/src/contracts.ts`/`validation.ts`/`compiler.ts`、新的 `instruments.ts`、`services/render-worker/src/runtime.ts`/`server.ts`/`service.ts`、应用渲染投影、审核 Catalog、pack manifest/credits（原始样本在外置目录，不进 Git）。

1. 先审核具体小包 bytes、归档路径/符号链接、许可、hash；解包只到新隔离目录，保留原许可。不运行包内代码。转换仅支持确认过的 SFZ 子集，loop 语义必须读懂；未知 opcode 拒绝/报告，不能误称全 SFZ 支持。
2. RED：假样本测试验证 rootMidi、keyzone、velocityzone、hash/缺文件/路径穿越/超大解码拒绝；验证 v1→legacy synth，v2→新钢琴，不存在暗中替换。
3. GREEN：shared compiler 增加多采样轨；按 note pitch 正确变调、明示复音上限与 voice stealing、增益/ramp/release 防 click。同音重击和踏板 release 只停止对应 voice，不能一抬踏板切断所有新音。
4. 演奏语义：二态 sustain 决定 note-off 延迟，retrigger 保留独立声音；最长 gate 与全抬踏板由确定性规则实现。此为工程近似，不声称物理琴弦/半踏共鸣。确保末尾总释放和有限 tail。
5. 真实 30 秒：旧 synth、新钢琴机械、新钢琴表达、回退四份 audio，同谱同响度条件；谱面不变、波形确实不同、无 hanging note/截尾；记录冷/热资源。样本层数不足时如实列限制。
6. Worker HTTP 内容端点仅通过审核 pack/sample ID 解析到固定 root，nonce/内容校验与最大 bytes 保留；不暴露任意路径。不因新增钢琴而启动新原生渲染器。

## Task D：Studio 的显式选择、表达编辑与撤销

Files：`apps/web/src/features/studio/{StudioPage,PianoRoll,ClipInspector,SampleLibrary,EditPreviewCard}.tsx`、`editorState.ts`、API schema/DTO 生成；相关 domain command/actual diff 与 edit pipeline。

1. RED：v1 打开不自动升级；缺包禁止应用且原声可用；“使用真实钢琴”产生 Preview，确认后新 Revision；力度/踏板编辑回读；Undo 恢复 v1 声音；刷新恢复待审批；非目标区域 hash 不变。
2. GREEN：最少 UI 增量：音源版本/缺失状态、选区力度/踏板、同位置 A/B 与接受/撤销。继续区分 Draft、保存版本与 preview；不新增独立大屏，不改整体主题。
3. `useAudioTransport` 当前播放已交付的 MP3，不能把 Draft 修改宣传为实时生效。v2 表达修改须有新预览 Audio Artifact，然后切换对应版本；若使用本地共享预览，状态必须明确且导出一致。
4. 当真正调整新建入口时才过滤电子风格：新的首页主线为 classical/jazz；legacy 作品路由、四 StylePack IDs、详情/播放/导出仍有测试。不能只从后端删除 enum。
5. 窄测试：目标 Vitest 文件 + domain/edit schema；重新生成 OpenAPI TypeScript 与 `tsc`/Vite build。浏览器真实检查需先协调其他 session，使用隔离 profile/端口；本轮未进行 UI 浏览器验收。

## Task E：一次完整验收和交付

依赖 Task A2 的单琴导出合同；在必要服务中从用户入口完成：新短谱→钢琴预览→表达修改→审批→保存→重开→Undo→导出。无模型，使用确定性谱面与人工命令；历史 v1 JSON/AudioGraph golden 保持。新音频特征与听者判断分别报告。

Eval 至少一条成功 `PIANO_EXPRESSION_AUDIBLE` 和一条失败 `INSTRUMENT_PACK_UNAVAILABLE`，并覆盖锁定范围、末尾踏板释放；不能把 96 条规则 Eval 当钢琴音质证明。结构化事件记录 revision/profile/pack hash、渲染时长、request/token=0、预算失败/取消标签。

资源门：render 并发 1；只用一个样本包；记录进程树 RSS（共享页可能重复计数）、系统 memory pressure/swap 若有权限、临时/最终 bytes、冷/热预览；固定三次只报告范围/中位数。若资源压力明显，停止扩包，先查释放、样本缓存与全文件副本。禁止凭 P0 五次上升直接断言泄漏。

最终本地 checkpoint；更新 IMPLEMENTATION_STATUS/TECH_EVOLUTION；保留有效音频基线/原样本/许可和哈希，只删除本 Task 可重建 bundle。独立审查一次；阻塞问题一次有界修复。用户没有授权本计划自动执行 P2–P5 或公开发布。

## 下一 session 的最小入口

Task A1容量已验收；本次已独立验证包合同/适配准备，真实包仍隔离。生产链路继续按A2单琴导出合同与Task B的v1/v2表达合同推进。音源 Task C 要在确切归档许可/解压能力确认后执行；若需要新软件或许可证接受，明确说明再确认。P0 的旧用户工程 DB/UI 与 pinned 容器验证仍是未测项，应在专用资源窗口补一次，不与其他项目争用默认 VM。


资源补充：A1五分钟3轨/880事件进程树RSS采样最高约2.15GiB；320MiB只约束声明的裸媒体缓冲，不能当作RSS封顶。真实钢琴解码、缓存与最大编制仍需独立测量。
