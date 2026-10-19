# P2 首切片：公版经典旋律导入与新增伴奏完整闭环

Stage P2.1；MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。BASE/Guide `d3ff8b0f91670df400de7d814e02a3849b8ea4d7`，Guide clean。用户已明确要求实施这一完整切片，保留当前手动模型配置、资源限制和阶段正常推送节奏；不重新征求已授权范围的实施许可。

## 已批准产品意图与本轮实施细化

用户要打开一首来源可追溯的短经典谱，按想法增加一条轨道，在同一Parent中试听比较，显式保留或放弃，保存/重开及Undo都保留原谱。既有导入/Revision/人工候选/Worker/导出/Studio继续复用，不创建新编排框架。Brainstorming分类为现有流程的接口演化：使用原ADR-019/P2路线与本次明确实现指令作为授权；写下具体边界供核对，不添加重复审批门。

选曲：Mutopia 528《Ode to Joy》，原数字SATB谱Public Domain，2009-08-05；固定原LilyPond文件/hash/来源与声明。首切片提取16小节soprano旋律转为无歌词单声部MusicXML，明确是钢琴旋律转换，不冒充完整SATB/贝多芬第九交响曲或原生MusicXML。保留原文件和转换说明、逐measure/note稳定ID及往返检查。只提供这一审核曲目入口；首轮MusicXML支持严格有界单声部、固定3/4或4/4、固定速度/调性、精确PPQ时值。未知repeat/tie/tuplets/transpose/变速/多声部等明确拒绝，不静默丢信息；MXL/任意上传/通用曲库留后续。

按想法加轨的第一基线：用户明确选择稀疏根音点奏或分解伴奏、八度/力度与逐小节和弦，不调用模型，界面不承诺任意自然语言编曲。第一版沿用同一已审核小钢琴包，新增的是独立低音区钢琴声部，不假装真实贝斯/弦乐。原旋律锁定，新增轨候选的原轨内容/演奏/全局结构保持；原谱独立Revision及分支保留，改编进入派生分支。没有新的音源下载、依赖安装或付费调用。

当前IRv2与AudioGraphv2显式限制单轨。不能直接放宽旧v2：增加明确IR/AudioGraph/engine v3（render-profile.v1以engine.v3分流）（最多两条同包钢琴），Job v3、ExportPlan/Bundle v4及SQL兼容迁移/降级guard；旧v1/v2和声音字节不变。复用现有Parent piano-preview节点/有限Worker等待、exact-hash人工确认与幂等/恢复，只增加显式加轨请求和纯领域命令。Undo仅恢复当前head的精确parent，不能扩大成任意快照覆盖权限。

资源约束：好听不靠堆文件。采样率/母版位深不提高；包体不增，单层限制如实保留；两轨共享一次渲染内的已校验样本buffer，避免重复加载/解码。render并发1，只跑短曲所需的真实边界；记录采样加载/渲染时间、临时/最终bytes及可测资源，不用文件增大证明音质。试听保持同位置/可比音量，新增伴奏默认低增益；母版不因压缩退化。钢琴保真度审计未找到明确渲染缺陷，不改旧声音包络或用EQ/变响冒充修复。

## Task 1：完整纵切

1. RED→GREEN：严格有界MusicXML解析/稳定ID/导入报告，曲目来源与转换逐音验证、未知语义和不安全XML失败；原谱创建/原分支保留/派生branch原子幂等及source hash。解析先验证再落库，缺音源/非法曲目不创建可误导作品。
2. RED→GREEN：v3双读/重建/VersionRefs与v2不变；显式append/remove钢琴轨命令、原轨/锁定范围保护、选择/和弦/资源限制、精确Undo。v3投影只消费实际轨道和选择，不伪造四角色；共享TS渲染路径和小包缓存复用。
3. 接通v3Job/Worker、v4导出Plan/Bundle/recipe/读模型/API与迁移guard，固定源谱与音源来源进导出声明；不扩大所有历史故障矩阵。相关unit/contract/Eval：成功CLASSICAL_SOURCE_PRESERVED，失败SCORE_FEATURE_UNSUPPORTED/LOCKED_RANGE_VIOLATION，旧声音/未知版本负向保持。
4. UI最小增量：Home审核经典谱导入说明/确认，Studio加一轨意图表单与原谱来源报告；复用现有A/B和保存/放弃/Undo/刷新恢复。无付费模型，显示等待/缺包/冲突/失败/取消，不显示假进度；桌面编辑/手机查看试听边界。
5. 一次隔离PG/Chromium真实UI完整链：导入→原谱→新增轨候选→刷新→两版试听→hash审批→保存→重开→Undo→原轨/hash恢复，必要canonical导出/文件校验；重复事件/取消选一个代表性路径。测试库只用新建任务容器/生成凭据，最终清除；不迁移用户库，不停共享VM。完整回归仅在此跨服务门一次。
6. 一次fresh独立审查/最多一次作者修复；同步Status/TECH/Guide范围事实、精确存储keep/inventory/cleanup、完成门、本地checkpoint。验收后正常推送同一开发分支并核对remote/CI；不合main、不部署/发布。第一首/两轨闭环不代表全部P2、自由编曲、真实多乐器、踏板、质量或性能达标。

原研究P2含两首钢琴/室内乐及更广谱面语义，均保留后续；P3再做真实预算内生成/爵士，P4优化贯穿测量，P5再扩编制。


## 完成证据

Task1已完成；一次初审1Important经唯一作者单事务修复与真实PG回滚RED→GREEN/限定复核关闭。实际边界、最终检查、范围和清理见[验收](../../evidence/2026-10-19-p2-classical-accompaniment.md)。Guide从BASE/clean开始，仅收尾同步顶部当前能力。
