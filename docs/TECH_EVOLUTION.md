# Motif Forge 技术演进记录

## 2026-08-11：阶段 1 实施启动

- 用户明确授权开始编写产品代码。
- 首个实现切片为“领域脊柱 + 框架化最小 Agent 纵切”。
- Python 目标版本为 3.12，使用 uv 管理依赖。
- 从脚手架引入 LangChain Core、LangGraph 和 PostgreSQL checkpointer；不使用黑盒 `create_agent()`。
- 原生 DeepSeek V4 Flash Loop 只作为协议/Baseline，测试默认使用 Fake Provider，不消耗外部 API。
- Docker Compose 当前只包含 API、PostgreSQL、Redis；Celery、Worker、Chromium 和 Web 在对应真实切片中加入，不预建空服务。

### 已落地的第一批代码

- 建立 Python 3.12 + uv 工程、FastAPI 工厂、secret-safe 配置、live/ready 健康接口和 API 镜像。
- 建立严格冻结的 `ArrangementIR v1`、PPQ 时间换算、canonical JSON/SHA-256、typed EditorCommand 纯函数以及不可变 Revision/Branch/Candidate/Preview 值对象。
- 建立首条显式 LangGraph：`ValidateBrief → CompositionPlanner → ValidatePlan → PlanApproval Interrupt → terminal`；测试使用 `InMemorySaver` 验证 interrupt/resume。
- 建立 PostgreSQL Async Checkpointer 生命周期工厂：独立 `motif_forge_graph` schema、受控 schema identifier、LangGraph 自有幂等 setup；本轮只做无数据库副作用的单元契约测试，真实容器恢复测试留在持久化切片。
- 建立原生 DeepSeek V4 Flash JSON Adapter：thinking mode、顶层 `reasoning_effort=high`、严格响应 Schema、usage、finish reason、超时/网络/429/5xx 有界指数退避与安全错误映射；测试不访问真实 API。
- 建立有限手写 planning baseline、版本化 planner prompt 和首条 eval fixture。

### 本轮验证

- `pytest`：39 passed。
- 覆盖率：82%（branch coverage enabled）。
- Ruff：通过；Mypy strict：通过；uv lock：通过。
- `compose.yaml` 已完成 YAML 解析；当前机器没有 Docker CLI，因此尚未执行真实 PostgreSQL/Redis 容器 smoke test。

### 明确未完成

- 阶段 1 仍缺真实 PostgreSQL restart/resume 集成测试、一次 Schema repair、完整 Error Router/预算/Trace，以及 thinking tool-call 的 `reasoning_content` 续传契约。
- 尚未实现 Revision Repository/UoW/API、音频编译/渲染、Celery Worker、四个知识包内容和 Web Studio；这些不会被健康脚手架伪装成完成状态。

## 2026-08-11：阶段 1 PostgreSQL 事务纵切

- 引入 SQLAlchemy 2 async 与 Alembic，业务表使用独立 `app` Schema；LangGraph checkpoint 继续使用独立 `motif_forge_graph` Schema，二者职责分离。
- 创建 Project 时在一个事务中创建空 Arrangement、Root Revision、`main` Branch、active branch、审计事件和幂等结果。
- 人工 L0/L1 Command Batch 使用 `SELECT FOR UPDATE + base_revision_id + CAS` 推进 Branch head；生成不可变 Revision、命令日志、审计记录和幂等结果。
- 变更等级只由服务端 `compute_change_impact` 计算；L2/L3 不直接写入 Revision，统一升级到 Candidate Preview 与人工审批流程。
- 建立 `/api/v1/projects` 与 `/api/v1/projects/{project_id}/command-batches`，补齐成功 Envelope、Problem Details、请求/Trace ID、幂等 Header 和身份边界。
- Docker Compose 新增一次性 `migrate` 服务；API 仅在 Alembic migration 成功且 Redis 健康后启动。
- 增加真实 PostgreSQL 集成测试合同：Project 原子创建/幂等、L1 提交、stale conflict、L2 rollback，以及 LangGraph 断连后 restart/resume 与 Schema 隔离。

### 本轮验证

- 不依赖外部服务的测试：`60 passed, 3 skipped`；3 项明确跳过的测试都要求真实 PostgreSQL DSN，不使用 SQLite 冒充。
- Ruff、Ruff format、Mypy strict、uv lock 均通过。
- Alembic upgrade/downgrade 离线 SQL 编译通过。
- 当前机器尚无 Docker CLI 与 Linux 容器 daemon，因此真实 PostgreSQL/Redis Compose 验收仍待运行。

### 下一实现边界

- 真实容器验收通过后，进入 Candidate Snapshot / Preview / Approval 事务闭环，让 L2/L3 AI 修改在批准后原子落为 Revision。
- 随后再接 Redis Worker、Outbox/Event 与首条渲染 Job；不让 FastAPI 请求承担长音频任务。
