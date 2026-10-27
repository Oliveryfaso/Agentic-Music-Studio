# 两个调度器 SIGTERM 修复：主线适配候选

阶段Personal Beta，MF-P16/P17/P18/P21；源码基线a703660。

先前f3913d2已修复并独审，但留在包含备份依赖的隔离分支，未进入公开主体。本次
仅提取dispatcher / resume_dispatcher接线、35行shutdown入口和原有7项测试，不合入
备份、0031或冷重建草稿。当前运行API14ce937 / Web f7462dd及原workers不变。

在当前代码实际复现：两个真实main的SIGTERM均exit-15，未执行资源finally；同一
合成外部边界下SIGINT两项通过。先保存2FAIL / 2PASS / 3deselected的RED记录，
再应用既有最小修复；7个信号 / 取消检查与Outbox、钢琴语义Outbox、Celery合同
组合30PASS。子进程只用for_test配置、合成数据库 / broker / checkpointer替身，
信号仅发送给本测试拥有的子进程，没有外部连接、真实任务或服务生命周期。

SIGTERM只请求取消主任务一次；现有finally负责释放engine / checkpointer，重复
SIGTERM不再次打断清理。正常SIGINT、非信号取消和真实异常传播保留；发布中断
不能误标为published / failed。不改变队列、lease、幂等、Job或schema合同。

Ruff检查通过。format检查的3个文件通过；resume_dispatcher原有两段非本次修改的
格式差异仍在，已对a703660原文复核同样失败，没有扩大此补丁去重排旧代码。
Mypy三个生产文件通过；限定独审无当前路径阻断，独立再跑7项信号测试通过，并直接
验证原更新提案器拒绝backend漂移。不把独审或原f3913d2的检查数与本轮相加。

仅在独立后续分支保存 / 发布，不修改main或当前运行checkout，不构建或切换镜像。
固定14ce的API/Web更新提案器应继续拒绝本候选的worker源码漂移；不得为部署它而
放宽原版本门。后续需另冻结匹配源码 / 镜像与维护范围。真实Docker PID1退出、
传输线程终止和真实PG事务取消尚未由本批证明，也不算0031组合通过。
