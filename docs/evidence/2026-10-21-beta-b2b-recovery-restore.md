# B2b：正常停启恢复与隔离备份还原

2026-10-21；MF-P06/P13/P15/P16/P17/P18/P21。基线436910b，应用代码仍为此前正常运行版，本轮仅做实际环境验收与文档记录；没有改变音乐算法、模型、运行配置或重建镜像。

## 已通过的限定结果

- 同一自有Beta正常stop/start一次。另建审核C02显式手工候选，2个真实队列渲染Job各attempt1成功；在待确认状态跨停启恢复。既有保存Revision、待审批thread/hash/两个Artifact及固定plan_hash导出精确保持。
- 停机前、重开后、隔离还原后分别核对6个JSON GET及13份完整媒体/导出文件，每次18,089,074bytes；含原完整11文件与待审批2个试听。保存Studio/导出完整canonical IR同一hash。3次原body/key的审批、导出、候选请求均replayed=true，没有新增版本/Job/Outbox/Artifact/模型请求；源39张表内容摘要全保持。
- 正常冻结自有写入方后，只启动精确自有PG作单库只读dump；完整备份覆盖app、observability、checkpoint及Alembic。dump216,825bytes，媒体23payload/19,661,346bytes。备份和还原均为已批准专用Beta数据根下的新子目录，不覆盖源库/旧作品。
- 还原到新空独立PG实例/独立数据库；目标PG/Redis使用有界tmpfs，无新持久数据库卷。只使用已存镜像、新internal网络、媒体副本RO、独立API，模型/tracing为空且无worker/dispatcher。还原后及API启动/只读访问后39表rows/digest均与源备份一致，源表亦保持；没有直接改业务表或手工完成Job。
- 原Beta最后Web/ready/保存版/待确认候选5GET正常，原9容器ID/镜像/挂载保留。清退仅精确本轮3个临时容器/1网络；dump及两份媒体副本保留，无共享prune，不管理Colima。

## 失败与证据边界

1. 首次文件清单校验因macOS生成34个AppleDouble元数据旁文件失败。23payload无缺失/变更；明确识别header与对应文件/目录后单列，保留原失败；没有重copy/dump。7个离线探针拒绝丢失、改字节、未知额外文件、伪sidecar、orphan及symlink。
2. 回放验证器误用简写表名、mount数组顺序、tmpfs检查字段的断言失败均保留，修复仅任务验收检查；未重发POST、未重建/重新restore。不能把这些校验器失败记成产品失败或抹去。
3. 还原API宿主loopback18100连接拒绝，internal网络未提供实际host映射。没有放宽网络；成功读取通过精确还原API容器自身loopback的正常HTTP进行。它证明API/数据库/媒体恢复，不证明宿主或浏览器入口。原Beta用户入口仍正常。
4. **共享环境未能证明全程无影响。** 其他27容器ID和最终status保留，但3个原running media-worker在约12:33:56–57 UTC额外重启，原因和其任务恢复未核实；18个稳定容器StartedAt保持，6个原restart loops继续。已审操作没有指向这3个worker；events为空、当前OOMKilled=false/ExitCode0、过滤内核OOM无记录，都不足以归因或排除历史影响。临时负载已清退，不调整共享配置，不宣称这些worker从未受影响。

一次fresh独审0 Critical/Important；容器内验证方案新增后，1项清退回执指针Minor已唯一限定复核关闭，无剩余代码审查阻塞。3个其他worker额外重启仍是未决运行观察，不能以代码审查通过消除它。

本轮新增模型调用0/费用0；同一窗口累计公开价估计上界¥0.059998、累计上限¥10（估计非账单）。没有读取/复制/持久化模型凭据，没有用户音频外传。

## 尚未完成

原前端浏览器DevTools原生权限没有批准成功回执，其播放/恢复失败/导出交互仍未通过；本轮没有绕过或替代。尚未验收同环境自然语言连续修改/Undo、运行中Job被打断后的恢复、断电/整机重启、长期稳定性或任意曲库音乐质量。临时PGDATA随清退消失，保留dump可重建，不宣称持久PGDATA还原耐久。

本结果可交付为有限恢复证据，不能标记完整B2或个人日用Beta全部验收。下一步先保留共享worker异常供后续有依据排查，再通过原前端授权入口完成日常浏览器主路径；模型仍默认禁用。

本机原始回执、完整独审、失败、SHA保留集与备份位置留在任务workspace，不提交音频、数据库dump、容器清单、凭据或私有路径。[机器摘要](2026-10-21-beta-b2b-recovery-restore.json)。
