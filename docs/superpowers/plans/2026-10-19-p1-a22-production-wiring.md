# P1-A2.2 生产动态导出接线

Stage P1-A2.2；MF-P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。BASE cd15bde，Guide 历史 e3d9438、无 diff、工作区 clean。用户明确“行，继续做”，授权按既定成熟化计划继续 A2.2/B/C/D；保留 Sol xhigh，不换语言、不付费、不扩包、不 push。

Spec 为已批准 ADR-019 和 2026-10-19-p1-minimal-piano / p1-a2-versioned-export 计划。之前 A2.1 仅内部合同；C1 仅真实音源边界。UnityWorkspace 同映像读写重挂已成功、现仍可写，Colima 原配置运行；旧临时 PG 已删除，本轮新建唯一标签/随机库/本机端口/缓存镜像 tmpfs 库。不得读 .env 或连接旧库。

## Task 1: A2.2生产动态导出

### 本纵切步骤

1. Cursor/Application：保留旧 v1 字段/七步/key；v2 显式双读并绑定权威 Revision/hash/实际轨道。Enqueue/Collect 只创建计划中的 master/可选 stem/可选 MP3/bundle，重放不多建 Job，所有新旧路径共用原 UoW/Outbox。
2. Bundle/Worker/PG：新增显式 v2 Artifact 身份与真实文件集合，Worker 解析 v1/v2 并验证 plan/revision/输入 lineage，实际 writer 使用已有 v2。旧 Artifact 表/reader 的限制必须通过迁移和 downgrade guard 明确处理，再启新写；保留原 v1 byte/hash/恢复消费者。
3. Parent/生产入口：同一个 Parent Graph 使用双读 checkpoint，新请求显式生成 v2；旧运行仍 v1。复用已存在的持久投递/恢复，不新建第三 Graph，不通过只测 helper 冒充生产接通。
4. 权威读模型/API/必要前端：步骤和就绪文件来自对应 plan；未请求 stem 不报缺失，下载按 manifest+DB 身份/hash 校验。DTO 从真实 OpenAPI 生成，保持现有 UI 结构和旧读模型。
5. 真实隔离 PG + 短 Worker 链：单轨 master-only 和显式一个 stem 两种请求、重复完成/刷新/新进程或 checkpoint 恢复、旧 v1 七步恢复；元数据文件全 checksum。对实际产物运行，不用填三条空轨或 mock WAV 冒充 canonical 音乐链。

## 接口预检与决策账本

CursorV2 已有 plan/plan_hash，但现有 Application 直接取 project/revision/seed 且按 role 找轨，需显式分派。Bundle Job/Request v2 已有，Artifact/DB/read 模型/Worker 仍固定 6 audio/13 files，不能只放宽计数。Graph 两个 producer 和一个 reader 当前 v1，必须一起接。

同 Revision 不同计划的 Bundle 唯一性、音频去重和 source_job 归属要用真实边界确定；不能降低 lineage 检查来绕过冲突。若需限制初版只允许每 Revision 一个导出配置，必须明确结构化冲突和 UI 行为，不能静默覆盖旧包。

Ruling：使用现有 feature branch 和独立任务测试/Artifact 目录，不创建第二源码副本 — 分支非 main、用户明确续做、当前 clean — 代价是保持一次顺序实现，严禁并行实现者写同仓库。

Ruling：按用户刚确认的风险分层运行针对改动的 RED/GREEN 和必要短真实链，组合回归只在消费者切换点/阶段末，不因 ledger 或文档重复全量 — 用户要求优先于技能默认裸 pytest 全量 — 代价是未触及的全量/压力矩阵明确列为未重跑。

完成 A2.2 后继续 B（IR/performance/profile/canonical 双读、版本能力/迁移 guard、命令/Undo）、再把 C1 审核钢琴挂入共享生产 compiler 和 D 最小选择/编辑入口。踏板仍不支持，不能按原计划旧文案伪报。每个消费者启用前必须有对应真实恢复/兼容证据；不扩大到 P2–P5。

## 验证和交付

针对新分支先失败再实现；窄 Application/domain/Worker/reads/API 测试，真实临时 PG 的迁移/幂等/恢复，必要 TS UI/编译。一次新上下文审查，至多一次阻塞修复复核，遵循仓库已批准 Portfolio Engineering Mode。性能压力跑不重复；不把真实发声当审美通过。收尾保留 accepted/hash，删除仅自有临时库/凭据/失败产物，不停共享 VM。
