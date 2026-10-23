# 2026-10-23：当前服务/保存版/11文件复核与B3技术交付

阶段P2.3/个人Beta B2→B3；MF-P04/P05/P06/P11/P13/P15/P16/P17/P18/P21。起点dev `f385f179f741097f57a6138f5b7836d6519c8102`、工作树clean；main `bebef9f`、Guide最近提交 `d68b900`未变。此次仅文档事实对齐与当前只读验收，无产品/模型/声音/配置/持久schema变化，原前端与资源session分工保持。

## 今天真实执行，不用历史代替

此前受审核命令两次因exec-server断线在创建进程前失败，原记录保留。今天基础命令和后续受审核检查均真实执行；进程42348最终exit0，回执UTC **2026-10-23T02:48:02.554223+00:00**。

- 同一项目 `cbc1c479-a90e-4730-9231-d63cf5cd6d81` 当前head仍为撤回版U `8afd8b30-aafd-4fbd-94b9-8970d77e7990`，完整IR/hash `4f01c68d2186bfbc0f1be342d68f879518c09a98a8d7541893ee9aecf8ffd4eb` 与原成功回执一致；原三个项目保存head未变。
- 两个模型preview均 **completed**，其base、保存Revision、candidate hash与baseline/candidate Artifact IDs均与原真实回执相同。不是因跨天被改称expired，不重新审批/丢弃。
- 固定U导出plan `05d24d3ccae18334ed533008641d13a0c0309655aa6e3831a9e8bb4abc03d120` 仍ready、同project/U/hash。实际再次流式GET全部11文件，全部HTTP200、总17,317,449bytes，大小/SHA与先前实际下载和当前投影相同；不创建新导出、不重写媒体。
- API ready、真实renderer capability available、Web普通HTTP200。API能力读逻辑要求renderer health ready及精确pack ID/version/manifest pin，不能用宿主文件存在冒充实时准入。
- API与resume-dispatcher当前空密钥、tracing关闭，目标容器ID自原清空后未变。该独立项目仍2次实际请求、4783tokens；本轮0新模型/0POST/0秘密读取或启用/0启停。

另一次标准入口 `scripts/start_motif_forge.sh --personal-beta --check` 在同runtime/数据根下实际exit0（进程10384），输出launch prerequisites ready。静态预检assets_verified=true、issues=[]，renderer_admission=not_checked/resource_ready=false；该静态标志不伪改为true，实时准入由上面独立API回执证明。该命令未init运行栈、读真实.env、下载/构建镜像或启停VM/服务。不是新冷启动证明。

## 两种候选状态分清

当前新项目两轮completed已保存，读取正常。**另两个旧项目**的未确认候选在10/22自然超过24h `expires_at`，数据库仍pending且approved_revision_id/decision_at均null，所以按恢复目录 `pending AND expires_at>now` 规则不再显示：

- 项目 `239f66ff-816a-4b3a-a352-500dbd67c11b`，旧preview `a532fb8c-c447-47e4-b656-26f2c78df1bb`，到期2026-10-22 11:23:35.877686 UTC。
- 项目 `fb5c1908-6159-4ea5-84ad-6244083752c2`，旧preview `e3642043-9213-48fd-8cac-a7d02a54f380`，到期2026-10-22 12:15:27.859776 UTC。

今天只读SELECT再次确认该原因，且本次读取前后投影一致。没有作品丢失/偷偷丢弃/延长TTL的产品反例，不修改TTL或恢复逻辑，也不用这两个旧候选当作前端恢复成功fixture。

## 复用的强证据与限制

10/22真实环境验证是规则R0加轨→两轮模型局部编辑R1/R2→正常保存→新进程精确Undo U→同U完整导出。U新UUID、parentR2、完整IR精确等于R1；11Jobs均attempt1。并非本轮新的真实模型append或浏览器A/B完整通过，不拼接旧测试扩张声明。

10/22的本地补证已将8实际音频 `-xerror -err_detect explode` 完整解码：48kHz/双声道/925714帧、19.285708秒，无解码错误/NaN/Inf/满幅削波且非静音；MIDI Format1/3 tracks/PPQ480、83个音符与导出IR的pitch/start/duration/velocity相同，截断副本负例被拒绝。两对A/B解码信号确有差异。今天复用这些原件及SHA，没有为了“继续”重复渲染或解码。

同内容R1两次独立预览PCM并非逐样本相同，已披露差分RMS -82.619dBFS；不在没有定位的情况下归因或修改声音，不承诺bit-exact复现/音乐审美。B2b历史正常停启/隔离恢复是另一次证据；宿主18100还原入口失败、其他三个worker额外重启原因/其任务影响未决，不能声称全共享环境全程无影响，也不因此扩恢复矩阵或操作旧项目。

原前端本轮报告无原Edge CUA/下载审批查询能力，刷新/返回及下载等浏览器检查未完成，未发现新代码缺陷、无新补丁。主线不替代其浏览器职责，不重发/绕过旧unknown原生审批。HTTP、文件流或解码不标成浏览器通过，主观偏好不阻止技术工作继续。

## B3已经推进的独立工作

总Beta计划按实际证据同步B1/B2客观项，拆开规则R0/真实局部编辑与浏览器复合门；状态摘要与路线当前断点改为今天B2→B3事实，旧失败/旧日期留存。新增[统一运行与恢复说明](../PERSONAL_BETA_RUNBOOK.md)，包含真实入口、现存U/固定导出、原已验证正常启停变量、保留数据、TTL与completed区别、默认模型未配置含义。

当前模型not_configured是临时授权窗口结束后的正确状态；现存作品可读，新自然语言操作不能被写成无需配置的长期服务。持久key配置不是本轮必须先走的新权限流程，也未偷偷创建。没有新资源需求、未重做资源线盘点，无确认产品代码缺陷需修复；若原前端后续发现可复现问题，再交已审窄补丁由主线唯一集成。

本轮新增付费请求/费用0，批准窗口累计观测峰价上界估计¥0.071874，含旧未冲销预留的gate保守曝光¥0.161688、剩余¥9.838312；均非账单。两套历史账本不重置/解锁，不为勾满计划而补调用。

保留当前一套Beta、数据库卷、approved Artifact根、审核RO包pin、现存U/两轮音频/全部失败和导出证据，供原前端验收。此次不新增运行资源/镜像/build cache；没有确定的清退目标，删除0bytes，不prune共享builder/卷或停止仍需使用的服务。新文档候选/检查回执仅任务workspace，提交不含密钥、音频、完整模型Plan或用户工程。

当前B3是**技术交付与说明已收口，浏览器验收工具依赖待闭合**。不能称任意曲谱/全风格/多人成熟产品或完整个人Beta浏览器封板；无需先等用户试听才能继续已有技术任务，也不因暂无代码缺陷扩新功能。

原始当日回执：任务workspace `research/beta-model-loop-20261022/final-model-loop/objective-followup/current-runtime-and-downloads.json`；启动预检/独立范围图在 `research/beta-current-closure-20261023/`。Git检查点与远端回核以实际提交历史/交付回执为准，本文不预写未来SHA或推送成功。
