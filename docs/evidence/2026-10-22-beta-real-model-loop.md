# 2026-10-22：同一正常 Beta 的真实模型多轮闭环

P2.3 / 个人 Beta B2，MF-P04/P05/P06/P11/P13/P15/P16/P17/P18/P21。源码基线 dev `d12dc6e`，工作树 clean；main `bebef9f`、Guide 最近提交 `d68b900` 保持。此次没有产品代码/数据结构变更，仓库仅记录实际验收事实；原前端、资源线职责保留。

## 已证实的结果

在同一个正常运行、持久数据库与媒体根的 Beta，通过正常 API → Parent/Outbox → 队列 Worker → HITL approval 完成：审核 C02 导入、确定性双钢琴 R0、两轮真实模型局部编辑保存 R1/R2、新进程重新读取、精确 Undo 新版本 U，以及同 U 完整导出。没有直接写业务表、人工标记 Job 成功或拼接历史不同项目冒充整链。

独立测试项目为 `cbc1c479-a90e-4730-9231-d63cf5cd6d81`（个人Beta 多轮验收 C02 · c14dd11a），分支 `309eac3d-1ba9-5c18-9eed-ba763184db5f`。原三个 HITL/保存项目逐一对照保持。

| 版本 | UUID | canonical content hash | 关系 |
|---|---|---|---|
| R0 | da526cc2-5087-498d-bb97-e2102f982214 | 94493a2f65647bec73f5a1265304339b7bf440d0c7caab6459935b1bb6c53ba6 | 已保存规则伴奏基底 |
| R1 | 59a26b49-96c5-4172-97ba-4b04abf70781 | 4f01c68d2186bfbc0f1be342d68f879518c09a98a8d7541893ee9aecf8ffd4eb | parent R0，真实第一轮 |
| R2 | 8bbac301-7f44-405c-9710-3630ae36ab2f | a017f8235137fd7d5b62634b9aa1c876094f6be572a640427165d96b2fb23ff0 | parent R1，真实第二轮 |
| U | 8afd8b30-aafd-4fbd-94b9-8970d77e7990 | 4f01c68d2186bfbc0f1be342d68f879518c09a98a8d7541893ee9aecf8ffd4eb | 新 UUID、parent R2、完整 IR 精确等于 R1；当前 head |

第一轮仅第二轨5–8小节：起音16→6、velocity40、gate240ticks；和声符合已保存默认和弦，主旋律全 Track、目标非 Notes 元数据、选区外完整 NoteEvents 精确保持。第二轮仅6–7小节：起音3→8、每拍一次、velocity50、gate240ticks，chord/octave 与 R1 原始模型 Plan 保持；5/8小节保留第一轮成果。这些是意图和保护代理检查，不是人耳“更好听”验收。

两轮各有真实 baseline/candidate 预览 Job，校验同 project/thread/base、独立 Job 与 Snapshot、输入/产物 arrangement hash、验证质量、真实 bytes/SHA、正时长和非静音。Hash-bound approve 各生成一个 immutable Revision，source_run_id、parent、保存完整 IR 与候选一致。

第二独立客户端进程 PID95205（模型保存进程95100）重读历史后正常 Undo。已知成功后的同 key/body 一次回放返回同 U，无重复 Revision/费用。U 的正常队列导出固定 plan `05d24d3ccae18334ed533008641d13a0c0309655aa6e3831a9e8bb4abc03d120`：11文件、17,317,449实际下载bytes，全部大小/checksum匹配；Master WAV/MP3、双Stem、MIDI、project.json、manifest/provenance/credits/license/trace齐全。音频 Job/Artifact 精确属于 U/hash(U)，project.json 是纯 canonical IR，Revision由 plan/manifest/provenance 绑定。第三进程再读 head/历史/线程/用量/固定计划，确认 U=R1，R2未改。该新项目总11个正常 Job 均 succeeded/attempt1；2个 AIRun 各 submitted1，队列没有未发布 outbox。

## 真实调用、用量和预算

仅 **2次真实请求，无重试**。请求 `deepseek-v4-flash`，产品保留的实际 response model 两次均 `deepseek-flash`。当日官方说明旧路由由用户已接受的 **DeepSeek-V4.1-Flash-1017** 提供服务；不是原模型相同权重的别名证明。实际容器设置 endpoint/model 与独立任务 gate 对照，前后官方价格/路由检查通过。[官方模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)（2026-10-22实际读取）。

| 调用 | input | output | total | 峰价且不计缓存折扣的人民币上界估计 |
|---|---:|---:|---:|---:|
| 第一轮 | 2261 | 208 | 2469 | ¥0.006186 |
| 第二轮 | 2137 | 177 | 2314 | ¥0.005690 |
| 本轮 | 4398 | 385 | 4783 | ¥0.011876 |

原批准窗口累计估计 ¥0.059998 加本轮为 **¥0.071874**，不是账户账单；该窗口实际请求总数12、tokens26409，窗口前 legacy4次另记不混入重置。为保留失败账本的完整未冲销预留，后继账本更保守地沿用 ¥0.155998 曝光，最终 **预算 gate 曝光 ¥0.161688，剩余 ¥9.838312**。其中旧预留不是已花费用，不将其说成实付，也不重复累计第一轮观察值；同一累计 ¥10 从未重置。

两次产品 usage 均 `partial`、reasoning_tokens=null、cost unknown。输入/输出/total/cachehit/cachemiss均真实有值且两处和一致。Provider 的 partial 定义正确；原验收脚本把完整六项分解 known 与计费核心可知混同，第一轮即停。独立核对[官方 Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)（2026-10-22）后补窄规则：只允许可选 reasoning 缺失，不填零、不改产品 partial；核心未知、矛盾、身份变化/超限仍停止。Plan、精确 Run、唯一 observed reservation 的所有六项值/类型/状态逐项一致。

产品 Plan 保存远端 completion operation，账本使用本地 `provider-reservation:<reservation UUID>`，二者按生产契约并不直接相等。曾因验收脚本错误相等断言在免费阶段停止；已用真实保存反例修正、独审，无新增模型采样。证据通过 exact Run主键、唯一请求/Run FK及完整用量关联；没有保存原始响应/model_version，不能宣称 raw HTTP 或精确权重身份证明。所有早期停记录保留，第一轮复用原候选，没有重新生成。

## 凭据与运行边界

依主 dots 的新明确授权，仅读项目既有目标 DeepSeek key，在受审核工具内以子进程环境/内存 stdin overlay 临时送入本任务 api、resume-dispatcher。Docker 配置元数据可被本机管理员读取的风险已批准。没有写新增秘密文件、日志或提交，没有发给其他服务；外发为官方认证及已批准审核曲谱的有界符号/文字上下文，**包含全部8小节主旋律和相关选区结构，不是仅发送两个小节**，无原始音频或私文件。

两个窗口的 finally 均恢复空配置、ready/capability验证成功；第三进程独立确认两个容器 configured=false、全部4个曾携密钥的临时容器已不在 Docker。当前 tracing=false。api/resume 都固定现有 API 镜像7dad581e；仅 owned resume 从旧8aae对齐，未构建/下载镜像，其他本任务服务ID/配置保持。12个关键文件和70个已安装Python包版本匹配，不声称取得了容器lockfile证据。Colima/旧项目未操作，服务保留给前端。

无凭据配置阻塞或未决执行回执；当前按授权主动恢复空密钥，因此日常入口的模型配置提示应为未配置，已保存试听与导出仍可用。持久凭据接入与更广运行权限没有悄悄建立。

## 检查、存储与剩余验收

17项原准备检查、8项最终窄回归、实际正常API/队列/PG和两次模型边界通过。各新发现均先保留实际失败/RED、再窄修复和受限独审；没有为任务脚本改动重跑历史164项Web。最终命名空间修正 fresh审查0 Critical/current-path Important。未改产品实现，无需产品重新构建或迁移。

所有原始/失败账本、实际回执、A/B MP3和11下载保留在任务 workspace `research/beta-model-loop-20261022`。卫生检查冻结当前镜像、卷、媒体/包pin与唯一运行Beta；两任务证据目录约20.8MB logical，无tmp/partial待清理。清理0bytes、新build/cache0，不全局prune共享builder/删用户数据。不把本地文件说成Library已交付。

正常本机入口为 http://127.0.0.1:15173/ 。准确作品/版本/固定导出与原前端交接见本地 `final-model-loop/FINAL-HANDOFF.zh-CN.md`。使用原变量化Beta启停流程，停止器只操作本任务；不重启Colima。此次 fresh process 重读不等于整机重启、模型运行中断或新的备份还原演练，旧B2b事实保持独立。

**仍待原前端/用户真正浏览器验收：播放切换、下载、键盘/小屏与本轮人耳契合度。** 旧DevTools原生审批unknown且无可转发编号，没有再次触发或绕过。API/byte/解码通过不标记UI或整个个人Beta最终通过，不扩新功能。
