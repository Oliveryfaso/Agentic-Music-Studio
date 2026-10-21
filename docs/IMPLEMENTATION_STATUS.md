# Motif Forge 当前实施状态

> 状态日期：2026-10-21（历史验证按原日期保留）
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

### 当前B2b：正常停启与隔离还原API通过，共享worker额外重启未决（2026-10-21）

MF-P06/P13/P15/P16/P17/P18/P21。独立C02手工候选2真实Job各attempt1；同一自有Beta正常停启一次，保存Revision/待审批checkpoint/13媒体文件18,089,074bytes精确保持，3原body/key回放无新业务效果。只读完整dump216,825bytes+23媒体payload19,661,346bytes还原到空独立库/RO媒体副本，39表及canonical IR/完整正常HTTP一致；目标API读取通过容器自身loopback，宿主18100连接失败保留。精确清退3临时容器/1网络，源Beta最终Web/API正常，无应用/配置/模型/凭据改动。

一次fresh独审1项清退回执Minor已唯一窄复核关闭。**其他3个原running media-worker在窗口内额外重启，原因/其任务恢复未决；不能宣称共享环境全程无影响。** 27其他容器ID和最终status保留，18稳定StartedAt保持、6原restart loops。原前端浏览器原生审批未完成，浏览器播放/恢复/导出、同环境自然语言连续修改/Undo、运行中Job/断电恢复及完整Beta仍未验。新增模型0，旧累计估计¥0.059998非账单/同一¥10保持。[B2b证据](evidence/2026-10-21-beta-b2b-recovery-restore.md)。

### B2a：独立项目免费API持久化与完整导出（2026-10-21）

MF-P06/P13/P16/P17/P18/P21的限定验证。同一正常Beta服务下另建审核C02项目，3个独立客户端依次生成手工候选、GET恢复→错误hash409/head保留→正常审批保存/相同body回放→新client重读相同Revision→完整正式导出。7真实Job各attempt1成功、7published Outbox、11下载文件共17,315,226bytes，SHA/manifest/canonical工程与保存版本一致；AI Run/模型调用0。未触碰原前端项目、未改应用代码/配置/服务。

独审1项Important经唯一窄修复查关闭，修复仅任务验收脚本的完整内容比较与success落盘顺序。浏览器、服务重启/备份还原、同环境自然语言多轮编辑/Undo及完整B2仍未验；重启阶段等原前端完成协调。旧累计估计¥0.059998非账单、同一¥10不变。详见[B2a证据](evidence/2026-10-21-beta-b2a-free-api.md)。

### B1：正常本机运行与手工队列试听已验证（2026-10-21）

MF-P16/P17/P18/P21。经用户精确批准的只读音源共享与同VM一次维护已完成，27原容器/旧卷保留，原4running恢复、17inactive未启动；不声称修复原6restart循环。专用3镜像源码核验、实际正常Compose/Vite、loopback端口、容器RO包/固定pin、实时capability及4谱目录均通过，resource_ready=true。实测非root EACCES经最小Dockerfile权限修复，实际RED→GREEN1、构建合同7/renderer音频124与fresh独审0确认发现；不改宿主数据/包权限或声音。

真实C02导入→显式手工规则伴奏→正常队列2渲染Jobs（各attempt1）→两个可用Artifact→waiting_piano_approval通过，未推进head，无人工完成Job或测试脚本业务写库。模型/tracing仍禁用、AI Run/付费调用0，累计旧估计¥0.059998非账单不重置。真实入口已交原前端session，浏览器实际播放/恢复/确认/导出及B2同环境自然语言编辑/Undo/关开/导出/还原仍待；不宣称个人Beta整链已完成。当前环境保留待前端，shared BuildKit归属不明不prune。详见[本机运行证据](evidence/2026-10-21-beta-b1-runtime.md)。

### Historical B1 source preparation: runtime gate pending at that checkpoint (2026-10-21)

MF-P16/P17/P18/P21. Installed source/config for isolated loopback Beta, explicit public templates, disabled model/tracing, reviewed readonly pack/pin, live capability/catalog guard and dedicated single-target image build.67 installed focused checks and17 independent checks pass; no review findings. Host assets verify and6 actual Compose config checks pass. Real readonly bind probe fails125: VM sees old ext4 placeholders rather than the actual host external volume. No permission to modify/restart sharedVM; no new image build/service/URL/Project/Revision. This is a source checkpoint, not B1 runtime acceptance. Real Compose/UI and B2 same-environment model/edit/reopen/export await the concrete external-share and later credential boundaries. [Evidence](evidence/2026-10-21-beta-b1-source.md).

### Current slice: personal Beta preparation B0 runtime boundary (2026-10-21)

MF-P16/P17/P18/P21. Strictly-owned start/stop is installed and real-Docker verified: unknown persistent resources refused, two stop/reopen cycles retain data and owner, repeat stop succeeds. Only task-created test resources removed; all27 preexisting container IDs retained, no VM changes. New real-CLI JSON-template defect was preserved, corrected by one literal brace, and narrowly independently reviewed. Installed checks27, original UI39+types, resources11; these do not replace full Beta Compose/browser acceptance.

User accepted the previous P2.3 local listening result as the music baseline. This slice does not change music/compiler/Graph/IR/DSP. Default model remains disabled; no secret read/copy/persistence and no new paid calls. Cumulative estimate upper CNY0.059998, not a bill, within the same CNY10 authorization. B1 dedicated loopback/current-image/resource runtime and B2 same-environment model/edit/reopen/export are still pending. [Boundary evidence](evidence/2026-10-21-beta-b0-runtime.md).

### 前次切片：P2.3 日常局部编辑稳定性（2026-10-21，技术收口；新局部听感待验）

MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P20/P21。用户已听上一轮36d2a3e九段并称效果不错，作为该次声音基线保留；不推断全曲库或盲测偏好。本轮不改Prompt/编译器/IR/Graph/DB/DSP/音源，只补PianoPanel显式保留音区文本填入、来源拍号/主旋律摘录提示、partial已报告tokens、音区及真实stale HTTP中文处理；无自动提交或默认意图改变。

三曲首/中/末与对抗Eval25；实际PG新多轮链及既有三曲共4通过，覆盖重叠修改、精确Undo、祖先音区证明、重放/重复/过期/错误hash/越界。Python942（已有弃用warning1）、完整Web133、最终文案alias聚焦7、TS/build135modules、Ruff、任务门禁55通过。实际built UI/API/自有PG/生产Parent/Worker离线8Jobs+本次4Jobs成功，原生同位置A/B及390px通过；不冒充Redis/Celery/Compose重验或人耳质量通过。

唯一真实C02第5–8bar局部请求，免费复用已认可Plan种子，无新付费append/重试：15→7音、平均力度58.8→41.43、gate5760→2520ticks，原旋律/原和声C-Dm-F-G/逐bar octave2/范围外精确保留，原模型Plan不修补。候选已在隔离项目放弃；新局部听感待用户。2245in+220out=2465tokens，峰价估计上界¥0.006250非账单；批准窗口累计10次/21626tokens/¥0.059998，原累计¥10不重置，按估计余量¥9.940002。request deepseek-v4-flash/response deepseek-flash，人类接受官方V4.1-Flash-1017替代，pre/post官方映射/峰价与精确scope/账本gate通过，未知权重不声称独立验证。所有历史批次和新批永久pause。

一fresh独审3Important+1Minor经唯一修复复查关闭，独立13通过；真实发送阶段/非JSON回执及post核验/相反意图停止器补齐，代理仍不等同人耳。新四段原增益/固定增益等LUFS离线实播通过，**Library明确成功 libfile_b4c25a60cb108191a5bd5d511da428a1（941,269bytes）**；旧包/九段/失败/账本不变。自有PG/生成DSN/API/renderer/browser关闭，共享27容器身份不变，清单先持久再清理12,316,929逻辑bytes，60保留文件指纹通过。Guide/main不变、不部署；dev正常checkpoint与push远端回读以最终交付记录为准。见[验收](evidence/2026-10-21-p23-daily-stability.md)、[机器证据](evidence/2026-10-21-p23-daily-stability.json)、[独审](evidence/2026-10-21-p23-daily-stability-review.md)。

### 前次切片：P2.3 音乐契合度上下文与针对性验证（2026-10-21；后续用户已认可该次听感）

MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P20/P21。用户听到新增轨但认为契合不足；已核对旧三曲、最新Q4与原谱左手，确认和声功能/半终止、3/4脉冲、26/23半音无动机跳进和句尾填音风险。原轨与编译时间相同、无声部交叉，不据此宣称测过声学起音。基线明确为固定速度主旋律摘录，非完整原作演奏。

新Prompt v5仅给v2增加拍位/时长加权的多候选和声、核对的源谱锚点、终止/休止/重复/拍号建议；fixed harmony/register优先，modify不加竞争和声。新记录标fit policy，Plan原样保存，旧记录不重解释；无新Schema/Graph/DB/DSP/音源/依赖。一次真实C02同旧意图：第2小节F/第8小节G/末拍休止代理通过，原旋律exact；第4–7bar仍重新配和声，26→23音但gate6720→9600ticks，不能称音乐质量通过。

Python917（既有弃用warning1）、相关31、任务门禁45/mypy2/Ruff通过；一fresh独审1项Important（缺post官方映射/价格GET）经唯一修复/5例限定复核关闭。4组控制8正式Jobs+真实2Jobs，actual API/自有PG/Parent/Worker/fresh重复resume/0追加调用重放与拒绝通过；不冒充Redis/Celery/Compose或新前端全验。单独声部为共享编译器诊断渲染，不计持久Job。

官方V4.1-Flash-1017已有人类接受，request deepseek-v4-flash/response deepseek-flash，pre/post官方GET与精确数据/预算gate通过，不能独立证明权重。本次1请求/2501tokens/峰价估计上界¥0.007132非账单；批准后累计9次/19161tokens/¥0.053748，沿用同一¥10；新旧账本永久pause，无第2次/重试，reasoning未知保持partial/null。

九段原/旧/新及H/R/V/独奏离线实播/同位置切换通过，固定增益−24.01至−23.99LUFS，160k有损副本。**Library新包已明确成功：libfile_9f7aadcc6c988191a1ea2f7ce36f402e（1,946,591bytes）**，历史失败不改写。自有PG/DSN/renderer/browser关闭，共享27容器保持；54保留文件校验，恢复清理可计量17,637,889逻辑bytes，外置盘首次部分删除未计量。Guide/main不变、不部署。当时下一门为人耳契合/清晰/乐句/偏好对照，后续反馈见当前切片；未启动新架构。[研究与验收](evidence/2026-10-21-p23-musical-fit.md)、[机器证据](evidence/2026-10-21-p23-musical-fit.json)。

### 历史切片：P2.3 Q4音区保持修复及单次真实验证通过（2026-10-20）

MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P20/P21。显式“保留音区”固定选区逐bar保存Plan.octave，来源必须用source_run_id重编译并比对精确NoteEvents/Track；不能证明/矛盾在Provider前拒绝。新Prompt v4固定register；Provider、存前、重放三处校验，违例无候选/Job，不转八度修补/重试；旧Schema/IR/DB/Graph不改，原失败样本和七次暂停账本封存。

用户明确接受官方V4.1-Flash-1017替代后，新独立批仅1真实请求/2187tokens（1985in+202out）/公开高峰价估计上界¥0.005586，非账单；批准后累计8次/16660tokens/¥0.046616，旧批准前4次另保留，历史合计12次/23888tokens/¥0.070468。request deepseek-v4-flash/response deepseek-flash，发送前即时核对官方路由/价格与精确数据范围。新批已永久pause，没有第2次；旧seq23 pause和null身份文件不解锁。reasoning_tokens未提供，必需计费字段完整，产品保持partial/null。

原Q4第10/12bar octave3→2的真实反例RED→GREEN；新真实结果9–12bar为2/3/2/3，原和声不变、音符12→8、力度56–60→38–42、总gate4320→1920ticks。实际API/自有PG/正式Worker2Jobs+fresh Parent重复resume、保存计划0追加调用重放、候选拒绝/分支不变通过。原Q1保存计划仅作隔离输入复用，无新append；不重跑旧整批。Python908（unit/root856+Eval52）、任务门禁37、mypy4source/Ruff/format，fresh独审无确认发现，另8内存+4范围检查。无需重跑未改变的前端/DSP构建，不冒充Redis/Celery/Compose或人耳审美通过。

新四段原增益/固定增益等LUFS离线播放通过（−24.00/−24.01LUFS），完整canonical保留，128k副本有损。自有PG/生成DSN/renderer/browser关闭，共享27容器身份不变，精确清理34599371逻辑bytes，24保留媒体/归档hash一致。Library本次唯一重试明确失败、无ID；新旧本地试听均保留。Guide/main不变、不部署。[切片验收](evidence/2026-10-20-p23-q4-register.md)、[机器证据](evidence/2026-10-20-p23-q4-register.json)。

### 历史批次：P2.3首次真实采样与身份暂停（2026-10-20；后续确认见上节）

MF-P04/P05/P06/P10/P11/P13/P15/P16/P17/P18/P20/P21。本轮7次真实调用/14473tokens，公开峰价上界¥0.041030（非账单），无第8次/重试。历史合计11次/21701tokens/上界¥0.064882，不清零。请求名保持deepseek-v4-flash、响应deepseek-flash；官方说明旧模型下线→V4.1-Flash-1017替代。主线已读映射却误当已获人类身份确认，未在首个名称差异停止；现账本永久pause，任务驱动逐次pre/post身份门禁要求精确替代版本的人类确认，当前null拒绝外发。不能称原V4 Flash同权重或音乐质量通过。

实际UI/API/隔离PG/正式Worker函数+fresh Parent三曲六例、真实第三轨拒绝、两项零调用守卫；19新Job/11完整导出文件校验，旧26不重跑，不冒充Redis/Celery传输。Q4更轻更疏但第10/12小节音区3→2违反保留指令，Q5密度减半但总gate时长不减；用户听感待验，保留失败不追加调用。实际发现语义加轨Undo白名单遗漏，生产一行补齐AgentAppend且保留精确parent/current-head/HITL条件，三曲有效RED→GREEN14、真实PG/UI零调用恢复原IR/hash，最终Python888与任务门禁33通过，独立Undo/身份审查无确认发现。

24对比剪辑+12完整源MP3离线原包保留，原增益/固定增益等LUFS分列；标明模型替代/意图失败/人工未验。owned API/renderer/browser退出，精确PG与凭据删除，共享容器ID列表不变。Library完整/轻量两次blob上传均失败，无新ID，不宣称附件已交付。main/Guide不变，不部署。详见[验收与执行失误](evidence/2026-10-20-p23-real-model-validation.md)、[机器证据](evidence/2026-10-20-p23-real-model-validation.json)。

### 质量收尾：P2.3 真实模型验收准备与停止器截止竞争（2026-10-20）

MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P21。准备9例/最多7真实提交、建议独立CNY1与0.672元最坏预留，尚未授权/调用；旧4次7228tokens/0.023852元公开价上界与累计门不重置。Settings白名单确认官方端点/原请求名/局部单次限制。真实音乐效果待人工，不让fixture代替模型验收。

停止器两种截止交错都观察RED→GREEN：已完成child在deadline前或TERM前退出时保留真实status，仍用原3秒截止门，TERM后wait并非绝对退出上限；旧自有Web测试修env/ready并去忙循环。合同11、完整Python885、Bash/Ruff/format/diff通过，原3.2秒调度间隔探针修前漏Compose、修后执行Compose；普通并行修前后各12绿不作根因证明。原历史偶发无trace，不能断言同因。既有Master/Stem只读复算1LSB、严格SHA不等，14保留音频/归档hash不变，不放宽身份协议或扩大确定性声明。本轮0模型/0新Job、无DB/业务/前端/音频引擎改动；独立审查结果见质量证据，main/Guide保持。详见[验收计划](evidence/2026-10-20-p23-live-model-acceptance-plan.md)、[质量收尾](evidence/2026-10-20-p23-quality-closure.md)。

### 当前集成：P2.3 三曲语义 v2 / 0030（2026-10-20）

MF-P02/P04/P05/P06/P08/P09/P11/P13/P15/P16/P17/P18/P20/P21。在88c0a07三曲目录/规则路径上接通source/meter绑定的request v2、实际bar ticks计划/编译、record v2双读和0030 JSON约束/危险降级保护；三曲自然语言append与第二轨1–4bar局部modify已开放。旧v1六和弦plan/Track/IR hash独立6/6完全一致；不可证明和声付费前拒绝，不猜D/Dm根音。Prompt新写v3，旧记录不改。8bar默认5–8，未知回执同body/key保留。

最终Python879/Web127/Audio124、Mypy141/Ruff-format/两TS、实际Web build/renderer bundle通过。真实PG三曲v2+旧v1回放/预算/局部/重开/Undo4项及独立fixture守卫2项；一次fresh独审无已确认发现，独立Python31/UI16/损坏record10例。Mac实际UI/API/PG/正式Worker+fresh Parent验证三曲A/B、拒绝/保留、C02局部/重开/精确Undo；15个新Job成功、11文件完整导出校验；旧26Job未重跑。4次Provider回执是明确离线fixture，真实模型调用/新增付费0，不当作模型质量证据。

实际候选另交原增益和等响度剪辑（−23.99/−24.00LUFS），四段离线真实播放及hash通过，人耳产品效果/偏好待验。先前用户只确认强滤波诊断差异可辨，未扩大为音乐质量通过。补全导出的严格重复Master SHA断言失败原始保留；宿主重复及Master减两Stem最大各1PCM24LSB，按既有宿主容差通过，不宣称pinned Docker字节确定性。旧启动器一次并行stub失败，单独及最终串行通过，未称已修复。

自有PG/API/renderer/browser及凭据关闭，精确回收34,334,972逻辑bytes，47保留文件校验；共享VM/用户DB/混合builder及固定试听构建/原诊断保持。Guide不变；未合main/部署。代码接线阶段完成，实际新曲付费模型/人类审美、实时EQ/主题及其余P3–P5保持单列。[验收](evidence/2026-10-20-p23-semantic-v2.md)、[机器证据](evidence/2026-10-20-p23-semantic-v2.json)。

### 当前集成：P2.3 三曲目录与规则路径（2026-10-20）

MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。生产目录新增Petzold小步舞曲16bars3/4 G、Burgmüller坦诉8bars4/4 C、Joplin Bethena原第9–16小节/8bars3/4 G，保留旧谱第四项。固定ID/XML及manifest/source hash、来源/转换损失/许可、原/工作分支、原旋律保护、实际bar ticks、规则F/Dm及MIDI拍号和导出credits已接入真实代码。没有下载或执行LilyPond。

目录使用实际DTO，逐曲确认绑定元数据；导入意图绑定score/key/body，未知回执锁曲并保留sessionStorage，同请求重试/刷新恢复；明确写入前失败可重选。新曲进入权威来源报告与规则伴奏；**新曲自然语言/两轨局部修改明确禁用**，旧谱v1语义保留。semantic v2/0030尚未实现，不称P2.3整体完成。

真实repo Python69/Web34、fullWebTS/mypy132/Ruff-format、独立目录生产build通过；actual OpenAPI重新生成DTO逐字节相同。Mac本机built UI+actual API+隔离PG三曲导入/重开、XML/节拍/调/原轨锁与两分支heads、same-key重放/异body409；C02服务器完成后故意丢回执，刷新重试仍同project；after-root异常回滚、不留第四个project。渲染服务可用性 admission stub明确保留，MediaJob/AIRun行均0，不宣称此次真实渲染/Redis-Celery通过。复用既有候选三曲26Job，不重跑。

一次fresh独立审查无当前路径阻塞，独立Python69与6个额外UI失败探针通过，无作者修复复核。自有PG/API/browser/凭据已关；固定试听4a构建/媒体/原截止时间保持，新build仅workspace。精确回收34,711,908逻辑bytes的本任务重复build/mypy缓存，保留当前build和试听备份，不动混合缓存/共享VM/用户DB。Guide不变，无main合并/部署。[验收与剩余](evidence/2026-10-20-p23-catalog.md)、[机器证据](evidence/2026-10-20-p23-catalog.json)。

### 已集成：P2.3 试听可靠性后续（2026-10-20，人工听感待验）

MF-P11/P18/P20/P21。六个 Web 生产文件隔离 Stop/替源/卸载后的旧播放回执，跟随原生媒体事件；候选和钢琴 A/B 保留绝对秒数、续播意图和 metadata 切换锁，失效候选清理，播放入口双向互斥。保存版明确标记 Revision，EQ 草稿不冒充实时音频。无 API/数据库/IR/DSP/Worker/主题/依赖变更。

真实仓库 Web25/Audio39/Export25、完整 Web TS 和生产 build 通过；一次 fresh 独立审查无阻塞，另12状态探针通过，无作者修复复核。Mac 本地无头 Chromium 使用实际仓库 build + 明示只读的保留快照接口，四份保存音频身份/实际播放/停止与验收页 A/B、写入403通过；390px viewport 无页面横溢。这不等于当前生产 API/PG/Worker 重跑或人耳听感验收。

复用此前候选三曲26Jobs及后段6个EQ/旁路Job证据；本次集成0新Job/0模型，不重跑旧链。先前正式音频旁路最大1PCM24LSB、1kHz中频−12dB不是纯整体增益；客观数据不能代替用户设备听感。三曲 picker、来源感知语义v2/0030仍未实现，P2.3整体未完成。自有只读入口自动限时关闭，不触碰用户DB/共享VM；未合main/部署。见[集成验收](evidence/2026-10-20-p23-playback.md)、[机器证据](evidence/2026-10-20-p23-playback.json)、[统一人工验收](evidence/2026-10-20-p23-human-acceptance.md)。

### 已验收：M2 真实三段 EQ（2026-10-19）

MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。已保存 v4/v5 双钢琴可调三段 ±12dB/总旁路/归零/恢复保存 EQ；IR5+固定 profile、human L0 snapshot 与精确 Undo，原 Track/来源/performance/M1 mix 保留。engine/Job5、Plan6/Bundle6、0029 历史 guard；Worker 重编译完整权威 graph/hash。旧 Tone EQ3 后只为可听非零段增至多3个 native biquad；零/旁路不增节点。无实时/频谱/整页新主题，候选配色未定。

真实 PG1、built UI/正式Worker/Parent export 最终15Jobs，全部三次探针尝试25Jobs/0AIRun；13实际音频，旁路/全零对M1≤1PCM24LSB、Master两Stem和≤2LSB、可信静音真零。生产模块15设置/75频点PCM曲线误差≤1.1e-6dB（有界探针）。Python838/Web115单worker/Audio124/Mypy133/Ruff/两build通过；一次fresh独立审查27领域断言+独立PCM/身份核验，两Minor唯一作者修复与限定UI3复核关闭。迁移JSON绑定反例、手势RED和两次浏览器harness失败保留。旧v4 M1-R1未改写，新v5规则标签正确。

自有PG/凭据/启动器关闭，31保留文件rehash；另13音频/20导出文件与buildassets复核。总精确回收77,654,375逻辑bytes，共享容器身份不变，无prune。产品模型0，既有4调用/7228tokens/公开峰价上界¥0.023852非账单；额度轮询取消，Library本轮未重试。非全曲审美/CPU/RSS/P95/Redis-Celery-Compose验收。见[合同](PIANO_EQ_CONTRACT.md)、[验收](evidence/2026-10-19-m2-three-band-eq.md)、[独立审查](evidence/2026-10-19-m2-review.md)。

### 已验收：M1 双钢琴基础混音（2026-10-19）

MF-P05/P06/P11/P13/P15/P16/P17/P18/P21。独立 piano_mix/IR4 保留原 Track/notes/来源，严格 human L0 命令与原谱锁分离；完整 IR 计算 mute/solo 后选 stem，v4 可信预期静音为真正零 PCM；Job4/engine4、Plan5/Bundle5、0028 历史降级 guard。UI 草稿→保存→显式生成保存版音频，reset/重开/精确 Undo 通过，无实时/EQ/整页改造。

真实隔离 PG/built UI/生产 Worker 与 Parent export 19 Jobs、17 音频信号检查；−6dB/左右声像/多 solo/mute 优先/静音与同图同 hash 试听导出通过。HTTP 字符串布尔宽松转换反例已修复并实测复验。Python792（unit/Eval758+root34）、Web109单worker、Audio77、PG1、Mypy133、两build/Ruff/diff通过。默认并行Web2等待超时原始保留，不称已解决。一次fresh独立审查63项无阻塞，Minor recipe静音规则标签延后。自有PG/凭据已关闭，回收43,396,290逻辑bytes，共享资源未动。模型0，既有4调用/7228token公开峰价上界¥0.023852原账不变；Library未保存成功、无ID。见[合同](BASIC_PIANO_MIX_CONTRACT.md)、[验收](evidence/2026-10-19-m1-basic-mixing.md)。

### 已验收：P2.2 自然语言伴奏与局部修改（2026-10-19）

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


## 2026-10-21 B2c：个人Beta重开与只读恢复合同

MF-P06/P13/P18/P21。已集成原前端ProjectCard一行修正，保存head无MP3仍可打开（真实源码RED→GREEN+首页回归3/3、TS）。workspace新增手工/semantic候选目录与ready/unavailable/limit_reached/count/确定排序；只读既有业务身份与Graph，stale保原base，TTL/终态排除，最多10条/3秒，不创建或审批。capability独立配置三态只注入本地bool，不探测模型或泄密。62相关unit/API/SQL检查、独立真实PG边界1、Mypy/Ruff、一次fresh独审0阻塞通过。正常Beta仅更新自有API，真实5GET确认两个原pending线程与三个head/主库计数保持、音源ready且模型not_configured。

原前端尚需消费两读合同与root Undo提示；真实浏览器原生审批仍阻塞，未把fixture/API称UI通过，完整个人Beta仍未整体验收。模型0新调用，旧累计估计¥0.059998/同一¥10非账单；main/Guide不变。旧镜像tag失败发生在替换前，已重建636d4aa应用回滚镜像，非旧镜像字节复刻；隔离测试库与35,986,643逻辑bytes自有cache/context清退，shared builder4.49GB归属混合未prune。[完整证据](evidence/2026-10-21-beta-b2c-reopen-contracts.md) / [独审](evidence/2026-10-21-beta-b2c-review.md)。


## 2026-10-21 B2c UI消费者已集成，停在用户验收关口

MF-P06/P13/P18/P21。原前端a83decb基线补丁精确5文件集成；恢复目录、模型配置三态、root Undo、读取/终态/旧base/草稿门禁均接入既有页面，无新接口或音乐变化。真实仓库源码60相关检查、阶段全Web47文件164项与TS通过；原前端一次独审+唯一窄复核关闭2 Important/1 Minor，本次不重复审查循环。仅恢复已无监听的自有Web，API/旧项目/Colima不动；普通HTTP核验三个当前模块和真实6个API，原候选/三个head保持、固定同版导出ready11项。

此前“原前端尚需消费”事项已由本条闭合；源码GET/组件检查不等于浏览器验收。原生DevTools状态仍unknown、不可转发，未重发/绕过。实际播放、下载、键盘/小屏及完整自然语言连续创作仍未据此通过；本轮不再扩功能。模型0新调用，旧累计估计¥0.059998/同一¥10非账单，main/Guide不变。[集成证据与手动入口](evidence/2026-10-21-beta-b2c-ui-integration.md)。
