# P1-C1 真实小型钢琴包与共享适配器边界

2026-10-19；Stage P1-C1内部音源接入；MF-P02/P05/P10/P15/P16/P17/P18/P21。起点6099fca、Guide无diff、工作区clean。用户已明确批准正常共享映像重挂和官方7-Zip任务内下载/运行；覆盖旧计划对此二项的限制。保留手动Sol/xhigh，不下载大包、付费或push。

## 已完成资源解阻

同一UnityWorkspace映像普通detach/读写attach均0，Writable=true，无force/chmod/删VM。Colima保留4CPU/4GiB/15GiB配置、default Docker context不变；有历史Motif服务随daemon恢复，未把它们作为测试设施或连接旧数据库。缓存postgres镜像用--pull=never创建唯一任务库，1CPU/768MiB、512MiB临时数据、localhost随机端口；两条原SKIP的PG导出基线已2 passed/1.18s。数据为一次性tmpfs，不宣称主机掉电持久性。

官方7-Zip26.04下载1,861,928bytes，与GitHub发布asset digest一致，仅任务tools目录。小包CRC全过，排除照片后26WAV+3文本9,463,579bytes；WAV全部44.1k/mono/PCM16，编码9,452,994bytes，48k解码预算20,575,508bytes，12个SFZ inclusive loop_end按格式文档转换exclusive+1，均在实际frames内。manifest作为审计候选，未自动接用户v1工程。

## 当前最小实现与验证

1. TDD新增Node侧reviewed instrument catalog loader：受信配置显式root+manifest SHA；实际许可证hash、每个WAV hash/PCM格式与frames校验；拒绝越界/符号链接/损坏或未知样本。原始音源不进Git，不下载任何URL。
2. 现有LoopbackRenderServer新增显式注册的nonce+sampleId音源路由，未配置默认404；永不消费请求中的文件路径。旧构造/内置click/输出sink不改。RED成功读取、错hash、许可、symlink、损坏样本、未知nonce/id；GREEN最小实现。
3. 新真实probe消费外部审计manifest/源目录并调用共享planPianoVoices/schedulePianoVoices，串行输出30秒48k stereo PCM24的旧synth/真实机械/真实表达/回退四份。自制短谱固定，表达用独立覆盖，最后两秒释放；测统一RMS标尺、波形差异/尾音/voice边界，不把这些数据说成人耳质量评测。
4. 缺样本/错hash显式失败，无silent fallback。v1 compiler/aliases、IR/Job/Revision版本仍不改；这证明真实数据→catalog→同一适配器→WAV，尚不是生产v2 IR/Worker/Studio链路。A2.2/B继续按原版本化计划，真实PG门现已具备。
5. 窄TS tests→audio suite/tsc/host build；一次独立审查和最多一次修复复审。保留精确证据/有效音频，清理仅自有失败probe与临时PG资源；共享历史服务不清理。文档状态/本地checkpoint，不push。

## 后续持久接线

A2.2仍必须在同一Parent/Outbox完成新cursor/job双读、动态权威读模型/API/UI、真实lineage与恢复；B音乐v2双读/Commands/Undo/迁移guard完成后，才允许用户选择新钢琴profile。C1不以实验probe绕过这些消费者。

## 独立审查修复

修复启动期间RSS超限竞态：延迟launch返回后检查预算，未交接browser前自行close；deferred真实异步生命周期回归先RED、后GREEN。150s期限覆盖launch及后续渲染。非阻塞失败产物策略：新建的失败probe目录保留已完成WAV供诊断，接受后按精确目录hygiene清理；不宣称cancelSink会移除已201的完成文件。
