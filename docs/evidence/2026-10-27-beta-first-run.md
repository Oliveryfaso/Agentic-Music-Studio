# 2026-10-27：新 clone 首跑检查与本机 Beta 状态

阶段：Personal Beta；MF-P01/P13/P16/P17/P18/P20/P21。本文不包含私有作品、
数据库、原始运行日志、凭据、容器ID或个人绝对路径。Guide最近修改仍为
`d68b900bd8dce6c5786dd0b6c6b531429c9d38a2`，差异为空。

## 独立新 clone

从公开HTTPS仓库重新clone main（14ce937），未借用原node_modules；随后将已审
f7462dd源码补丁和本次启动器改动叠加到该一次性副本。Node26.0.0 / npm11.12.1，
支持版本检查使用本机已安装的Python3.12.13；没有安装或改动系统解释器。

| 实际命令 / 边界 | 结果 |
| --- | --- |
| `git clone --depth 1 --single-branch --branch main` | PASS，14ce937；不是本地目录复制 |
| `npm ci --no-audit --no-fund` | PASS，157packages / 12秒；任务独有cache、空npm配置，不用用户认证配置 |
| 候选 `npm ci --offline --no-audit --no-fund` | PASS，从本次cache重装自己的node_modules，lockfile一致 |
| `npm run test:web` | 53files / 203tests PASS |
| `npm run build:web` | 类型检查和139modules静态构建 PASS |
| `npm run test:audio` | 首次108PASS / 16FAIL，原因loopback `listen EPERM`；保持原失败日志。经原生权限允许临时随机端口mock服务后，同套16files / 124tests PASS；没有修改音频代码 |
| `npm run build:audio` | 类型检查与renderer bundle构建 PASS |
| 空配置 `start_motif_forge.sh --check` | 按预期exit78提示缺.env，不建文件 / 服务 |
| 公开.env.example + 新空存储根 + 显式Colima context | 原版Python3.9仍返回ready，确证前提诊断缺口；修复后3.9 exit69，3.12.13 exit0 |

最后一行的.env和空目录由验收准备显式创建；`--check`没有创建它们。只读check
调用daemon身份和Compose配置解析，不运行up、迁移、应用、渲染器、模型或端口服务，
不读取 / 接管原Beta数据与runtime。只有音频单测使用自己的临时loopback mock服务器。

## 最小修复与回归

- 新启动器在私有配置、runtime、存储和Docker操作前检查Node22.12+与Python3.12–3.13；
  `--help`依赖无关。版本不足只给动作明确的错误，不安装软件，不替换系统运行时。
- package / lock的Node声明从`>=20`统一为文档的`>=22.12`，依赖版本无变化。
- 实际shell入口新增11个用例。先观察8FAIL / 3PASS，再最小修复；与既有launcher、
  personalBeta、release、ownedRuntime组合共81PASS。合成工具只替换外部命令边界，
  没有替换待测启动器；验证不支持版本连Key检查和Docker都未触达。
- README使用公开默认main，补准确验证边界；开发排障移除“停止脚本会停Colima”的
  过时说明。该启动器修复当前仅在本次源码候选，运行实例仍保持f7462dd。

## 已完成的本机 API / Web 更新

这是先前已批准并实际完成的局部维护，本次首跑检查没有重复部署：

- API源`14ce93714123edeb61a6e71a413882e68dd08385`；镜像
  `sha256:e16ea99fcd2c182800bccac817cf6ebc0e6b6edd9663c376f4f01f9e83406f39`；
  Web源`f7462dd29355d6e1b1882692f388cb443b1661bc`；schema0030。
- 2026-10-27 UTC03:30:09–03:30:15维护完成，耗时5.368秒；API / Web停机观测上界
  4.216 / 5.098秒。一次API构建24.056秒、一次永不启动的身份探针已退出 / 清理，
  使用原4GiB VM，没有扩容。不是renderer或全组合的内存峰值证明。
- 主线实际比较原保存版、22成功Job、40媒体文件和读取投影不变；7运行2停止，原
  workers / resume / PG / Redis / 音源身份保留。本机运行pin已持久绑定新API，
  支持启动器check成功；公共旧pin模板没有因此自动变更，不能承诺他人已有此镜像。
- 独立源审查核对API源文件 / pin / Web / Guide；另一个窄真实检查确认readiness、
  存储依赖、设置页200和`not_configured`。较大的只读检查因审核超时未启动，
  没有重发；主线的数据hash比较不算独立重复验证。
- 原前端真实浏览器只读验收另见[独立证据](2026-10-27-beta-web-readonly-acceptance.md)。
  无真实Key、连接测试POST、模型请求或新增费用；不是全机网络抓包结论。

首轮维护曾因挂载数组顺序误判回退；完整挂载字段排序比较的最小修复通过后，才在
新的用户批准窗口完成上述切换。原失败 / 回退记录、旧UNKNOWN和旧下载状态保留，
没有用后一次成功改写历史。

## 未被这批证明

完整全新Compose起栈 / 首次生成、固定镜像应用层冷重建、真实数据独立恢复、0031完整
组合、真实Key保存启用鉴权与模型闭环、原生下载及主观音质均不能由本批推断。
只读备份恢复候选及0031发布修复继续隔离，不在本次公共源码改动中。
