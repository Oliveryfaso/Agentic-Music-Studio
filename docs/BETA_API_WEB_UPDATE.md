# API 14ce937 / 独立 Web 候选 / schema0030：无 Key 更新包

**2026-10-27 状态补充：** 本文是10月26日离线维护合同，不能作为当前仍未部署的判断。
既有本机 Beta 现已更新至 API14ce937 / Web f7462dd，数据库仍0030；原4GiB VM完成一次
24.056秒构建和一次身份探针，最终局部切换5.368秒。后续源码与默认pin模板并不自动
改变这个实例。实际覆盖及未验门见[当前状态](IMPLEMENTATION_STATUS.md)和
[本轮证据](evidence/2026-10-27-beta-first-run.md)。以下保留当时预算、旧回退身份与流程；
下次维护必须重新冻结当前身份与授权，不能照搬旧CID / pin。

这是维护准备，不是执行回执。当前发布 pin、镜像、容器、源码运行目录、数据库和音源均未被本包更改。计划器永远输出 `NOT_READY_OFFLINE_PROPOSAL`，不调用 Docker、不更新 pin、不自动回退。

## 唯一范围

- API 构建源固定 `14ce93714123edeb61a6e71a413882e68dd08385`。相对现有 Inspector 应用 a3bfb1a，后端产品只变更 `api/app.py` 和新增 `api/model_settings.py`。
- Web 单独选定完整提交 `MOTIF_WEB_COMMIT`，必须是14ce937的后继、提交内的保护后端源仍与API基线一致，且选中Web目录与提交完全一致；不能把新导航/标题修复记成14ce937。最终提交后另存 API SHA、Web SHA 与 Web tree ID；未冻结前不能维护。两个源码身份分别记录，API pin仍表示API构建源。
- 构建一个 `api` target，独立 tag `motif-forge-beta-api:settings-14ce937`。不构建 renderer/media，不新增服务/队列，不扩容或重启 Colima。
- 正常替换 API 和 Web。保留 PostgreSQL、Redis、dispatcher、resume-dispatcher、media-worker、render-worker；migrate、storage-init 保持原停止状态。
- 未来正常启动的 API/migrate pin 共同采用审核后的新 image ID，兼容声明仍为 `20261020_0030`；本次**不执行 migrate 或全栈启动器**。API 启动仍包含既有 checkpoint 幂等初始化，不能声称完全没有数据库写入。
- 默认不启用 Key、不挂私有 Key 文件、不点击真实连接检查、不调用模型。现有音源/只读挂载/manifest pin 完全复用，不重解包、不新备份。

## 预算与当前未知

| 阶段 | 提议边界 | 仍需实测或确认 |
| --- | --- | --- |
| 构建，Beta尚不停止 | 一次单目标构建，15分钟；干净源副本≤16MiB、暂存构建上下文≤8MiB | 静态普通输入约2.25MiB；不是镜像、缓存或内存峰值。Dockerfile含pip/uv，可能访问既有依赖源。基础层/缓存缺失或资源余量不能确认时停止，不能借旧维护额度扩容 |
| 构建新增磁盘 | 提议≤2GiB，构建前后按本批镜像/上下文核对；不prune共享缓存 | 此值是停止预算，不是已证明足够的最低需求；超过或无法归属就停止，不默默放宽 |
| 安装身份核对 | 一个新建但不启动的临时容器；无网络/端口/挂载/Secret；复制下列两文件及元数据≤256KiB，结束按确切ID删除，不用-v | 尚未创建；新容器及其清理需包含在维护批准中 |
| API/Web停服 | 预留20分钟；每个正常生命周期命令120秒，新版本健康最多等5分钟，失败立即进入旧版回退 | 不强杀；退出/回退UNKNOWN时停止后续动作并报告，异常停服不能保证20分钟内结束 |

不套用未经测量的CPU/RAM限额。最近一次允许的短窗口只读采样发现压缩器实际占用增长153.28MiB，不能证明构建时容量稳定，构建与维护保持HOLD；重连不解除该门。不是永久不可行的结论，也不能把memory_pressure百分比当可分配内存。CPU/内存不足不启动构建，不关闭用户应用或自动暂停其他服务。

## 先完成的现场门禁

1. 重核 daemon、项目/owner、API CID及镜像ID、Web PID/start/cwd、原7运行2停止、端口和所有挂载；只读白名单元数据，不输出 Env。历史值不是当前证明。
2. **已完成一次全表只读活动快照，维护前必须重新确认。** 2026-10-26 12:02:53 UTC，repeatable-read READ ONLY聚合覆盖 `ai_runs`、`runs`、`jobs`、`outbox_events` 全部行后ROLLBACK：2/14/22/46项分别全部成功/成功/成功/已发布，活动任务、lease及未来待投递事件均0。不是永久空闲证明。`/projects`/latest_run/workspace/钢琴恢复目录有范围或分页限制，不能代替该集合；仅计数，不读作品/指令/JSON正文，不打印DSN。不新增全局产品接口。
3. queued/planning/materializing/waiting_worker、queued/running/failed_retryable Jobs、pending/claimed Outbox 或活跃lease均阻断本次静默窗口。稳定的人审等待另行记录并确认保留，不丢弃、重放或当作运行任务取消。用户先完成未保存Web草稿。
4. 保留当前实际旧镜像与源码回退点；当前可见基线来自既有记录，必须重核：API应用a3bfb1a、镜像 `motif-forge-beta-api:inspector-a3bfb1a`、ID `sha256:b133641886492ffeb3a73c3905beda303ad19d07319cb905ca0969841b6aa3d4`；Web/source `81b1cffc8bf8d20686a80bac6d6ae1cf242df9c4`，schema0030。更老7dad镜像不能替代此回退点。

## 构建、身份与提案

从固定14ce937创建**新的干净源码副本**构建，不用带未跟踪文件的运行目录。仅调用已有 `build_compose_images.sh --personal-beta api`，显式选择上述新tag；不覆盖旧tag、不全栈up。构建超时先取消本批构建并核实结束；UNKNOWN时不继续维护。

从本次新构建取得不可变image ID，使用不启动的专用探针容器复制：

```
/opt/venv/lib/python3.12/site-packages/motif_forge/api/app.py
/opt/venv/lib/python3.12/site-packages/motif_forge/api/model_settings.py
```

只计算并记录SHA256，不import app或启动应用。原始报告由执行者核验后，按四个顶层字段 `source_commit`、`reference`、`id`、`files` 写入本次私有证据目录；`files`以 `motif_forge/api/app.py`、`motif_forge/api/model_settings.py`为键，hash与计划器固定值核对。不得从随意现存镜像学习新pin。该JSON没有Secret；计划器只验证**报告的值**，不能认证报告来源或证明容器已被真实检查。

```sh
python3 scripts/plan_personal_beta_api_update.py \
  --repo /chosen/reviewed-integration-source \
  --web-source "$MOTIF_WEB_COMMIT" \
  --image-evidence /chosen/this-build-identity.json
```

stdout包含待审核的新pin、仅API image override、旧ID rollback override和独立Web提交。`--repo`指向含选定Web提交的审核树，API构建仍用上文干净14ce937副本。保存为本次新证据文件，不覆盖现有pin；输出仍为NOT_READY。不同源码、旧/非法ID、错误hash、额外字段、worker/Dockerfile/schema漂移，以及错误/缺失/未冻结的Web身份或目录变化均拒绝。未跟踪检查也包含被Git忽略的内容；因此应使用没有字节码/缓存的全新源码副本，不能把忽略规则当作构建排除证明。

## 获批后的唯一切换顺序（本轮不执行）

1. 先构建及核对新镜像，保留旧ID。记录实际活动/身份门禁，通过后才进入停服阶段；不以离线测试替代。
2. 只正常关闭确认归属的Web，再正常停止旧API，禁止超时自动SIGKILL。退出未知就停止后续。API停止后再次只读聚合任务，避免最后一个请求产生新Job；若有新工作，不取消它，恢复旧API并结束本窗口。
3. 会写已确认的原运行仓库 `$MOTIF_REPO`：先保留指向原81b1cff的独立本地回退分支，再在干净原分支正常快进到冻结的 `MOTIF_WEB_COMMIT`，写入经审核的实测新API pin。会改运行源码文件和 `scripts/personal-beta-release.v1.json`，不修改 .env/Key/作品；Web在此之前必须已停止，避免热重载改变页面。实际绝对目录只进入本机维护确认，不硬编码到公共配置。
4. 使用原项目、原公开env模板、相同compose配置/环境路径和最后一层新ID的API-only override。**仅允许后缀** `up -d --no-deps --no-build --pull never api`；不运行全栈start、migrate、storage-init，不让全局tag顺带更新旧workers。
5. 该API替换会删除旧API容器的可写层/本地日志；不删除旧镜像、数据卷或绑定目录。回退是用旧ID重新创建API，不是恢复原CID。此不可恢复后果必须在维护确认中说明；没有确认则不执行。
6. 用原源码根和原runtime合法恢复Web，更新确切自有进程记录，不复制receipt或由新worktree认领旧服务。API启动后最多5分钟内核对不可变ID、安装文件、OpenAPI设置路径、health、capability/catalog及新增GET返回 `not_configured`；再核对已有保存版/固定导出只读关联和原worker身份。`health.version=0.1.0`不能证明源码版本。禁止真实POST连接检查和生成。

## 回退与收口

新API不健康、安装身份/0030/挂载/既有作品读取不符即回退：正常停止确认的新API，最后一层override改为原b133…完整ID，只重建API；恢复旧pin并切回保留的81b1cff源码分支、原Web。没有DB downgrade、数据还原或重渲染；旧作品、HITL与Job不重置。每步只处理明确自有对象；退出UNKNOWN不重发、不强杀、不继续VM动作。正常回退也需健康与身份核对，不能提前称演练通过。

本轮交付离线合同和同伴测试，另有一次已授权只读现场预检；不据此宣布维护就绪。实际构建/依赖网络、一个停止探针容器、上述运行源码/pin写入、API容器替换及Web停启仍需下一次精确维护确认及技术门通过。0031、整栈冷重建、真实恢复、有Key生成均不在此包内。
