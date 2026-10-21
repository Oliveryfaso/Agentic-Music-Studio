# B2a：独立项目的免费保存/重新读取/恢复/同版本导出

基线0bc5b31，worktree clean，Guide last d68b900且diff空。MF-P06/P13/P16/P17/P18/P21。沿用正在运行的个人Beta，不改变源码、服务、音源或凭据。原前端只读验收项目（具体ID仅本机交接），本验证所有写入必须拒绝该ID，也不读取它；不启停服务、不替代浏览器操作。

1. 独立新幂等键导入固定审核C02，名称明确为B2隔离用例；显式roots手工伴奏、正常Parent/Outbox/Redis/Celery/renderer，停在候选待审批。无semantic、LLM或直接数据库写入。
2. 结束首个客户端进程。新进程从磁盘回执重建client，正常GET恢复同一thread/精确candidate hash及两Artifact；错误hash审批应409且head不变。再正确审批保存新Revision，重复相同审批只回放、不生成更多Revision；重新读取studio与分支head验证持久状态。必要Undo仅在新独立项目正常API执行，不能动原项目。
3. 再结束客户端，新进程GET保存Revision，正常POST该Revision完整export（Master/MP3/全部Stem/MIDI/project/manifest等），有界GET轮询真实Worker；不调用Graph私有resume、不手工完成Job。所有下载限定本机且对应该bundle，文件名/大小/总量有界，逐文件SHA和manifest/Revision/Arrangement对应核验。
4. 只读核验新项目Job/Outbox/Artifact及AI Run0，记录全部HTTP回执与PID、幂等键和失败；不自动重发不确定POST。错误或超时先保留证据诊断，不能刷成功。正常同键回放是明确验收动作，不是错误重试。
5. 真实服务重启/断连恢复、浏览器关闭重开，以及隔离数据库/媒体副本备份还原，均待原前端结束并协调后执行。这次新客户端读取不能冒充服务重启、断电或浏览器验收。费用新增0，旧累计估计¥0.059998非账单、同一¥10不变。

先免费路径，发现产品缺陷才单列测试优先最小修复/独立审查；本计划本身不启动重构、模型启用或环境扩权。
