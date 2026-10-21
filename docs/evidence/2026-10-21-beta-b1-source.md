# 个人 Beta B1：源码就绪，真实运行门仍待外盘共享

2026-10-21；P2.3→审核曲库双钢琴个人日用 Beta；MF-P16/P17/P18/P21。基准为已推送的安全启停检查点6cb58b2。声音/编配/IR/Graph/DB业务合同不变。

本切片交付的是可复查的运行配置与诊断，**不宣称完整Beta已运行或验收**。真实仓库67项限定检查通过，一次fresh独审0 Critical/Important/Minor，独立17项通过。9个代码文件与受审冻结清单一致；无需修复复核。

## 源码已完成

- 显式 `--personal-beta` 启停档位，复用B0精确所有权和内核锁。独立project、runtime后缀、媒体根；临时receipt只承诺正常关开，不推断整机重启或OS清理后的自动恢复。
- 公开 `.env.example` 在Compose插值和容器env_file两层明确选择，不读/复制实际.env；排除ambient Compose文件选择、旧媒体根误继承。模型key保持空，tracing关闭。
- Web/API/renderer/PG/Redis仅loopback，独立默认端口。审核包只读long bind、缺源不创建、固定受审manifest pin。启动前验证资源，后续需新鲜renderer身份、API capability/profile及四谱目录均匹配。
- 独立Beta镜像标签。缺镜像明确exit78，启动不下载、不构建。构建入口只接受api/media-worker/render-worker之一，拒绝Beta all，复用既有白名单clean context；不覆盖共享旧标签。

## 已做的实际边界与当前阻塞

实际宿主资源预检assets_verified=true，但renderer_admission=not_checked/resource_ready=false。实际公开Compose配置6项核验通过：全部端口本机、模型key空、遥测关闭、只读且不自动建源、固定pin、独立镜像。缺镜像检查真实exit78且未启动服务。

为避免先做无效大构建，用已有缓存镜像、无网络、一个随机自有短容器，尝试只读挂载本仓库已审核钢琴包并核对pin。Docker返回exit125：`bind source path does not exist`。已核对没有残留容器。进一步只读查看确认，VM中/Volumes/KINGSTON和旧仓库路径只是八月留下的ext4占位目录，`findmnt`显示 `/ /dev/vda1 ext4`，并非宿主外盘共享，精确音源目录不存在。宿主预检成功不代表VM能看见同一路径。

用户本轮只允许启动已存在VM，明确“不改配置、不停止它”。因此没有追加共享、覆盖配置、重启VM、复制音源到内部盘、挪用其他项目目录或默默换存储根。用户收到具体外盘共享前提，待合适窗口提供后再验。

此外，已有标准API/media/render镜像内容落后当前源码，不能当本轮代码运行。此时没有构建镜像，没有完整产品服务、URL、Project或Revision。源码检查点可回退至6cb58b2；这不是已验收B1运行状态。

## 接续验收

外盘共享就绪后先核验精确路径及pin，再按独立Beta标签分别构建必要3目标，正常启动同一持久数据环境、核对实际只读mount/loopback/livecapability/四谱目录；将真实URL/Project/Revision交回原前端session浏览器验收。之后才是同环境真实模型连续修改、Undo、关开、同Revision导出及新目标恢复。模型配置仍受具体凭据授权限制，不用fixture回执或人工完成Job冒充真实链。

本轮新增模型调用0/费用0；旧累计公开价上界0.059998元是估计、不是账单，同一累计10元不重置。main/Guide未改，无公开部署。[机器证据](2026-10-21-beta-b1-source.json)。完整独审、RED/GREEN及原挂载失败保留在任务workspace，没有公开共享容器清单或秘密。
