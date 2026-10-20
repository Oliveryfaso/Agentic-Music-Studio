# P2.3 质量收尾：启动器竞态与真实模型验收准备

2026-10-20；BASE97d7a20，开发分支codex/motif-p0-piano-preparation，Guide最后d68b900/start diff空；MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P21。未调用付费模型、未重置历史预算、未改业务IR/API/Provider/音频引擎/DB/UI，无新渲染Job，旧26Job及现有离线媒体未重跑/覆盖。

## 可批准的真实模型验收

[9条用例、预算与停止条件](2026-10-20-p23-live-model-acceptance-plan.md)，三曲各一次加轨与一次局部修改共6条、一次不支持意图模型拒绝、两条模型前拒绝。三曲音色指同审核钢琴包的实际回放质量，不冒充模型能换音源。每条保护原谱/来源/拍号/选区外、hash HITL与Undo；工程正确、意图符合、人工偏好分开。Q4放弃验证不动head，Q5/Q6保留/重开/Undo；不复活已拒绝Run来省调用。

建议父端单独申请本轮CNY1、最多7次真实提交（失败/超时计入），每次12000total/3072output/8000UTF8bytes/non-thinking/1attempt/0repair/并发1。全部tokens按公开峰值输出8元/百万计算，预留0.096元/次、共0.672元；实际输入输出2/8元分计上界，非账单。历史仍4次/7228tokens/上界0.023852元，不重置原CNY10，不自动继承旧未用次数。新增调用0。CNY批次门是未来验收harness应落账的要求，不冒称现有Provider已实现全局金额闸门。

项目Settings仅白名单核对：已配置、官方endpoint、保留请求名deepseek-v4-flash，连接5秒/读取45秒；钢琴专用Factory实际固定单次，不受通用max_attempts3扩大。没打印配置对象、密钥或环境，没查询余额/账单/额度。2026-10-20[官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)确认旧别名仍路由Flash新服务；精确响应身份须另查原始HTTP字段，不使用Adapter缺字段回退冒称服务端身份。

## 旧停止器问题：从可控失败到修复

真实stop_motif_forge.sh在kill -0判活后检查SECONDS截止。父进程在两者之间被延迟时，即使docker info已成功退出，旧代码仍无条件return124，跳过compose down，最后却可能report fully stopped。自有docker/colima stub、空runtime、真实/bin/bash和3.2秒调度间隔复现：子命令0.15秒完成、只记录colima stop。没有调用真正的Docker/Colima停止服务。

先补可控Bash DEBUG握手：child在deadline判断前已完成/非零完成/仍运行，旧代码首例RED（1失败2通过）。首个判活修复后当时8项通过；随后，补child在重新判活之后、TERM之前完成的第二窗口，再次准确RED（1失败5通过），才补TERM失败时wait真实status。最终生产改动仅截止分支两处返回已完成child真实退出码；原3秒截止不加长，当前测试中仍运行且响应TERM的child继续TERM并return124，非零结果不误作成功。六种确定性交错都在真实脚本上运行，不用CPU压力碰概率。

原测试另有env没有传给fake npm，TERM trap touch空路径、忙循环且父脚本可能多等5秒；现在传入自有env，trap后发ready标记、父端有界等ready、假Web循环sleep，不空转。不改生产Web启动/停止权限或真实Colima范围。

原3.2秒探针修后命令恰为docker compose down/colima stop；普通隔离并行重复修前12/12、修后12/12分别保留。普通重复绿不是根因证明；两个确定性RED→GREEN才证明本次竞态。缺少原偶发事件的原始trace，所以不宣称该历史失败必然同因，也不宣称所有并行启停问题已解决。

最终合同11通过；Python unit/Eval/root885通过，保留一个既有Starlette/httpx弃用警告；Bash语法、Ruff/format与diff通过。无业务层改动，不重跑PG/媒体/前端套件冒充新运行时证据。测试在现有Mac host-first环境，不运行实际全栈关闭，不宣称Docker/Compose生产启停矩阵通过。

## 1PCM24 LSB证据边界

只读重新解析既有两份Master与两Stem，均48kHz/stereo/PCM24、925714frames；重复Master最大差1LSB、Master减两Stem和最大1LSB，文件SHA仍不相等。两套旧/新离线ZIP及8段实际比较文件hash重核不变，共14保留文件核对；没有新渲染或修改canonical。

M1 solo/mute、M2旁路/全零已有1LSB有界比较，M2低电平Master两Stem门曾用2LSB。但这不是事前为同Revision重复渲染声明的逐字节门。P2.3更强的严格repeat SHA断言确实失败，原报告保留；更准确地称“在继承的宿主数值比较准则内，严格SHA失败”，不改判失败、不为追求偶然一致再渲染，不扩为普遍/跨平台/pinned Docker确定性证明。求和结论也仅限该低电平样本，不取消limiter非线性。

每个Artifact的权威bytes/SHA、Revision/IR/hash、HITL candidate hash、原轨和计划重放身份仍须精确一致。1LSB不能放宽任何这些身份协议。主观可辨/目标符合/音乐偏好、真实模型质量均待新验收和授权。

## 审查与资源

一次fresh独立审查完成，无已确认Critical/Important/Minor；独立合同11通过、Bash/diff/Guide通过，无作者修复复核。[审查与证据归属](2026-10-20-p23-quality-closure-review.md)。本轮仅自有bash子进程/stubs，普通12次probe已退出并完成finally清理；未建DB/服务/容器、不读用户库、不清理共享VM/Builder。执行通道曾报exec-server transport disconnected，恢复后继续；不是权限审核拒绝，精确写入审核已放行。

[机器证据](2026-10-20-p23-quality-closure.json)。未合main、未改Guide、未强推或部署；开发分支checkpoint与远端核对在任务交付回执记录。

审查后界限：现有helper在TERM后仍wait，不宣称忽略TERM或内核不可中断命令也有绝对3秒退出保证；本轮没有扩展成整栈强杀/watchdog。默认Colima停止范围为既有行为，本次不扩大它，也没有实际运行，不能把本次测试视为停止共享VM的授权。下一轮真实模型质量、真实账单/额度/精确响应权重仍须分别取得证据，PG/UI/Worker历史链不借shell修改重复跑。
