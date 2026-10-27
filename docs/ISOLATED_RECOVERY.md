# 隔离 PostgreSQL 与媒体恢复

阶段：个人单用户 Beta 恢复，覆盖 MF-P13/P16/P17/P18/P21。

`scripts.personal_beta_restore` 将可信的 v2 备份恢复到一个已另行安全准备的全新临时 PostgreSQL，并核对媒体文件、数据库表与序列。默认只检查合同和目标路径；普通 clone 用户不能直接加 `--execute` 获得可用的恢复环境。

前序冻结实现已完成一次真实 PG 与媒体恢复。本轮公开适配将个人固定摘要改为必填 `archive_sha256`，验证范围为合成回归，未重新执行真实恢复。恢复后启动 Motif Forge 应用、API 读取、播放与导出仍未验证；`RESTORED_PG_AND_MEDIA` 不能解释为完整应用恢复通过。

## 支持边界

- 使用项目要求的 Python 3.12；下列命令显式使用 `python3.12`，避免误用 macOS 自带旧版 Python。这组工具只使用 Python 标准库。
- 宿主为 macOS，恢复目标位于可写 APFS。执行时通过 `df` 与 `diskutil` 重核实际设备；不承诺 ExFAT 上的恢复。
- Docker context 固定为 `colima`。工具不会安装或启动 Docker、Colima、镜像或数据库。
- 只接收 `motif-beta-maintenance-backup.v2` 单文件归档，ZIP 成员须为未压缩的 `ZIP_STORED`；这不是通用 ZIP 导入器。
- 数据库版本固定为 `20261020_0030`。不执行迁移，不支持 `0031` 或跨版本恢复。
- 归档上限 195 MiB，媒体总量上限 128 MiB、文件数上限 256，数据库 dump 上限 64 MiB。恢复父目录还须保留媒体与 dump 之外至少 512 MiB 可用空间。
- 只处理合同指定且通过归属检查的临时 PG；不向生产数据库恢复，不启动应用、Worker 或队列，不创建或删除容器、网络。显式执行会创建全新恢复目录，但不自动删除它。

## 先确认归档可信

执行前先核对可信备份清单及 manifest 的来源、版本与内容范围，并从独立可信来源取得整包 SHA-256。`archive_sha256` 是调用者明确提供的信任输入，必须为 64 位小写十六进制字符串；缺失、格式错误或与实际归档不匹配都会拒绝。

归档内 manifest 与成员 hash 自洽只证明完整性，不认证归档来源。对未知归档临时算一次 hash，再把该值填回合同，不能使它成为可信备份。工具不会发现一个摘要并自动信任它，也不会用归档完整性检查代替数据库恢复证明。

如需先读取并检查归档结构与成员完整性，可在仓库根运行：

```sh
python3.12 -m scripts.personal_beta_backup verify \
  --backup "$MOTIF_ARCHIVE" \
  --allowed-root "$MOTIF_ARCHIVE_ROOT"
```

这里的 `MOTIF_ARCHIVE` 是已确认的归档绝对路径，`MOTIF_ARCHIVE_ROOT` 是其已确认的允许根目录。此命令会读取备份，不连接 Docker、不恢复数据库。结果中的 `database_restore_tested=false` 和 `db_artifact_consistency=not_proven_by_integrity_check` 保留各自含义。

## 恢复合同

先自行设置仓库根 `MOTIF_REPO`、归档根 `MOTIF_ARCHIVE_ROOT`、恢复根 `MOTIF_RESTORE_ROOT` 和合同文件绝对路径 `MOTIF_RESTORE_CONTRACT`。允许根与目标父目录应已存在；本批 `target` 必须不存在，且不得与备份或 manifest 记录的源目录重叠。路径检查拒绝不合法的链接与越界路径；源目录仍存在时，还按设备号和 inode 核对目标祖先，拒绝大小写别名，无法确认身份则停止。

以下 JSON 仅说明结构。`${...}` 是需要预先展开的路径占位，JSON 不会展开环境变量；所有摘要和身份字符串均为虚构占位，必须替换后才能使用。

```json
{
  "archive": "${MOTIF_ARCHIVE_ROOT}/trusted-backup-v2.zip",
  "archive_root": "${MOTIF_ARCHIVE_ROOT}",
  "target": "${MOTIF_RESTORE_ROOT}/restore-attempt-001",
  "target_root": "${MOTIF_RESTORE_ROOT}",
  "archive_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "owner": "11111111111111111111111111111111",
  "daemon_id": "daemon-id-from-docker-info",
  "pg_id": "3333333333333333333333333333333333333333333333333333333333333333",
  "pg_image": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
  "expected_db_revision": "20261020_0030"
}
```

合同只允许上述字段。`owner` 为本批独立的 32 位小写十六进制归属值；`daemon_id` 必须与当前 `docker --context colima info --format '{{.ID}}'` 返回的完整值一致（可能为 UUID），`pg_id` 为完整 64 位小写十六进制容器 ID，`pg_image` 为 `sha256:` 加 64 位小写十六进制镜像 ID。不能用名称、短 ID、tag 或其他环境的回执代替。

## 默认预演

在仓库根使用模块入口：

```sh
cd "$MOTIF_REPO"
python3.12 -m scripts.personal_beta_restore --help
python3.12 -m scripts.personal_beta_restore --contract "$MOTIF_RESTORE_CONTRACT"
```

`--help` 不读取合同或备份。未加 `--execute` 时会读取合同并检查目标路径，但不读取备份、不连接 Docker、不创建资源。有效预演输出：

```json
{"status": "DRY_RUN", "restore_performed": false, "runtime_verified": false}
```

这只说明合同与本地目标路径检查通过，不证明归档存在、摘要相符、APFS 可用或临时 PG 已就绪。

备份 CLI 的 `restore --dry-run` 是另一个只读入口：

```sh
python3.12 -m scripts.personal_beta_backup restore \
  --backup "$MOTIF_ARCHIVE" \
  --target "$MOTIF_ARCHIVE_ROOT/unused-plan-target" \
  --allowed-root "$MOTIF_ARCHIVE_ROOT" \
  --dry-run
```

它会读取并校验备份，输出 `restore_dry_run_only` 与 `ready_for_real_restore=false`，不会执行恢复。示例计划目标也必须不存在；它不替代恢复执行器的独立合同和临时 PG 门禁。

## 显式执行的临时 PG 门禁

维护者必须在另行批准的准备步骤中创建专用、空白、可丢弃的 PostgreSQL；本工具不承担这一步。PG 与唯一内部网络须带准确的 `io.motif.restore.owner` 标签，网络只能连接该 PG，容器不能带 Compose 归属标签。准备者须记录真实 daemon、容器与镜像身份，并确认只有本批能够操作它。

执行器还要求以下现有配置，任一不符都会拒绝：

| 项目 | 必须满足 |
| --- | --- |
| 新鲜度与状态 | 每次准入时创建不足 120 秒、正在运行、重启次数为 0、重启策略为 `no` |
| 资源 | 内存 384 MiB、内存与 swap 总上限同为 384 MiB、1 CPU、最多 64 个 PID |
| 隔离 | 只读根文件系统、无特权、无发布端口、无 bind mount 或持久卷 |
| tmpfs | 仅 `/var/lib/postgresql/data` 256 MiB、`/var/run/postgresql` 8 MiB、`/tmp` 64 MiB |
| 数据库 | 固定本地 socket、`motif_forge` 用户与数据库；无业务表、序列或其他活动连接 |

只有上述准备、可信归档和准确合同均已核对，才使用同一入口显式执行：

```sh
python3.12 -m scripts.personal_beta_restore \
  --contract "$MOTIF_RESTORE_CONTRACT" \
  --execute
```

执行时先重核目标和归档，验证整包摘要、manifest 与每个成员，再独占写入全新恢复目录。dump 通过 `docker exec -i` 的 stdin 流入临时 PG 的 `/tmp` tmpfs，不使用 TTY，不放宽只读根文件系统。`pg_restore` 仅对该临时数据库执行单事务导入；比对快照查询继续采用只读事务设置。

监督器结束时会再次核验确切归属与身份，并停止已准入的本批 PG。`docker stop --time 8` 提供 8 秒退出宽限，超时可能强制终止该容器；宿主自有子进程也有终止监督。因此这项执行授权必须涵盖停止这个可丢弃 PG，不能指向当前 Beta 或共享数据库。工具不自动删除该容器或网络，恢复目录中的媒体和 dump 会保留。PG 数据位于 tmpfs，停止后的容器不是持久恢复实例。

## 结果与失败保留

成功状态 `RESTORED_PG_AND_MEDIA` 仅表示本批媒体校验、数据库表与序列比对、受监督子进程退出及临时 PG 停止证明通过，`api_verified` 仍为 `false`。它不证明应用已启动、真实 Key 可用、作品能播放或完整导出通过。

失败或退出无法确认时返回 `FAILED_OR_UNKNOWN` 和有界脱敏诊断，保留首个错误、清理错误及已有恢复文件。`restore_performed` 可能为 `null`；不能把 UNKNOWN 当作没有副作用，也不能自动重试、删除目标或另建容器。先根据确切身份与保留证据核对本批状态，后续清理需要独立确认。

备份 CLI 随包保留 `plan`、`verify`、只读 `restore --dry-run` 及显式 `create --execute` 所需依赖，可用 `python3.12 -m scripts.personal_beta_backup --help` 查看参数。备份创建使用另一份维护合同和写入者退出门禁，不会替调用者停止服务。本说明不建立定时维护或日常备份自动化，也不宣称本轮已验证日常备份到完整应用恢复的端到端流程。
