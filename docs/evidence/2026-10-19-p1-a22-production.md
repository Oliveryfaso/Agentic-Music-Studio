# P1-A2.2 生产动态导出验收

Stage P1-A2.2；MF-P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。BASE cd15bde；Guide 历史 e3d9438、无 diff。用户授权连续完成A2.2/B/C/D，保留手动模型，不付费、不新语言/大包、不push。本Task已通过一次独立审查及唯一修复复核；音乐v2/新钢琴持久Undo/UI仍是后续B/C/D。

## 实际变化

同一个 Parent Graph 新增确定性 export 分支，每次显式导出是有限线程，无模型/AI Run。POST请求按Idempotency-Key派生request_id并固定body；计划绑定不可变Revision/hash、实际track UUID、可选MP3/显式分轨。Run/首Job/Outbox同事务保存plan，后续Job验证pin。新请求可得到不同plan/Bundle，旧七步cursor/keys/receipt保持。

Worker显式双读v1/v2 Bundle，v2文件/输入计数来自计划；Run/Bundle增加plan/hash及0022/0023迁移和不能降级的明确guard。最终音频元数据按source Job区分，底层内容文件仍复用，配额按可用storage_key统计一次。读模型按计划隔离Job/Artifact并固定manifest SHA；同时替换成员/manifest不能绕过数据库pin。Bundle是原有逻辑文件集合，音频由AudioArtifact下载，不冒充自包含ZIP。

界面提供MP3/全部实际分轨选择、开始、取消、显式重新导出；URL保存选定plan，刷新按该计划读进度。网络请求重试保留原key，新的导出使用新key。取消先持久Run意图，再取消当前Job；claim/followup/completion不复活已取消Run。每个实际产物写入前复用原Worker StoragePressureGate；API可先入队、空间问题在执行时明确失败/等待。

## 证据与边界

真实独立PG17.10（缓存镜像、任务标签、本机端口/tmpfs；未接触用户库）中验证幂等/body冲突、两个不同请求、按计划读取、重开API/checkpoint连接、取消及取消后拒绝claim、显式重试。metadata fixture另证v1 receipt JSON/SQLNULL不变、v2 Bundle实际writer/读回/download、downgrade拒绝及source Job身份；fixture不当作发声证据。

实际短canonical链使用自制2秒单轨、Chromium/共享TS引擎。master-only为2Jobs/8files，另一次同Revision含单stem为3Jobs/9files，共5Jobs/2Bundles，2.886秒。每步重建API/checkpoint连接，用实际持久Outbox事件调用生产Publisher，重复事件不增加Job；全部文件下载size/SHA匹配。它没有重跑Redis/Celery投递进程或Compose，不是掉电恢复/长曲压力/钢琴音质证据。原始[JSON](2026-10-19-p1-a22-production.json)。

相关跨消费者回归107 passed/4.20s；更新后的配额fixture另1 passed/0.86s：4条元数据、3个物理键、21,732 bytes，不按同大小漏计。Web导出4 passed；严格Mypy116源文件、Ruff、生成DTO、TS和audio宿主build通过。旧v1七步/Parent/checkpoint/Outbox/导出读回保留。未为文档重复全量或五分钟压力。

独立审查发现两类Important：API/Worker已收记录却漏续下游节点、重复metadata容量计数。均先复现RED后最小修复；API重试和Outbox重投对非interrupt待执行节点用ainvoke(None)，事务幂等确保不多建Job。独立修复复核21 passed、无剩余阻塞，见[原报告](2026-10-19-p1-a22-review.md)。

仅清理本任务可重建临时renderer bundle/空log；保留真实canonical文件、metadata与JSON，partial=0。精确bytes见JSON.storage。自有PG因授权继续B而保留，最终阶段精确清理；共享VM/历史服务不停止、不prune。代码与报告只做本地checkpoint。
