# B2a：独立项目免费API持久化与完整导出

2026-10-21；MF-P06/P13/P16/P17/P18/P21的本次限定验收，基线0bc5b31、Guide last d68b900且diff空。本轮没有应用代码/运行配置改动、构建或服务启停，不触碰原前端正在只读验收的项目；不替代原前端浏览器职责。

## 已实际验证

同一正常Beta服务创建独立固定C02项目，显式roots手工伴奏走正常API/Parent/Outbox/Redis/Celery/renderer，候选停在等待审批后结束首客户端。第二独立进程从本机回执重新GET同一持久thread、candidate hash和两个Artifact；错误hash审批409且head不变，正确审批completed保存新Revision，完全相同decision只回放。保存Studio经既有纯IR canonicalizer复算，与候选hash一致。

第三独立客户端重读保存的相同Revision/IR，再正常请求include_mp3与全部Stem的完整导出。有界GET等待真实队列，无私有Graph resume或手工标Job完成。共28个JSON API请求和11次文件GET；只读数据库按新project范围佐证7个Job全部成功且各attempt1、7个Outbox published、AI Run0，没有测试脚本业务写库。

11文件合计17,315,226bytes：Master WAV/MP3、两个Stem、MIDI、project.json、credits/license/provenance/trace及manifest。逐文件长度/SHA、manifest成员一一对应、project.json完整canonical IR与保存Studio/已批准候选hash一致，导出plan同Revision。3个WAV均48kHz双声道PCM24、925714frames；MP3容器/编码与MIDI头另作离线核验。上述只说明格式和版本一致，不是人耳或浏览器播放通过。

一次fresh独审发现1项当前路径Important：最初导出脚本只存project.json且先写success、后做最后GET，可能误报。唯一窄修将canonical IR/manifest成员核验补齐、成功状态移到全部断言后；限定复查和实际下载证据无剩余阻塞。首恢复/审批步骤未重跑，未重启服务或刷模型成功。

## 当前精确边界

此轮只验证客户端进程关闭后重新读取及正常持久审批/导出。没有验证浏览器关闭重开、服务重启/断电恢复、备份还原、同环境自然语言与多轮编辑/Undo；不能把它称完整B2或个人Beta验收通过。原前端只读浏览器验收继续独立进行，原候选未被本任务读取/审批/丢弃。

继续阶段的依赖：原前端完成并协调后，才可用同一所有权receipt正常停启本任务Beta，保持同数据/卷再核对版本与未决状态；不停止Colima或其他项目。备份恢复只对独立测试数据库/媒体副本，不能覆盖原库/作品；当前尚未开始。模型仍禁用，本轮无需新增凭据或付费授权；如进入模型启用须先提出具体临时凭据/作用对象方案，不能复制现有Key或默认解除保护。

所有HTTP回执、客户端PID、真实Project/Revision、下载文件与独审留在本机任务workspace，仓库只记录脱敏范围和结果，不发布音频/私有配置。保留活动环境和未决候选供原前端；只盘点/清理本任务可再生小缓存，共享BuildKit不prune。新增模型请求0/费用0，旧同一窗口估计上界¥0.059998非账单，授权累计¥10不重置。[机器证据](2026-10-21-beta-b2a-free-api.json)。
