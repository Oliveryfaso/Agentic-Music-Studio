# P2.3 质量收尾独立审查

### Strengths

- 生产修复保持最小范围：`scripts/stop_motif_forge.sh:46–62` 在 deadline 前已经完成、以及重新判活后/TERM 前完成的路径上读取 `wait` 的真实退出码。0 才进入 Compose；7 等非零状态不会误入成功分支。仍运行的测试子进程沿原 TERM/124 路径退出，未延长原 3 秒 deadline，也未改动 Web 所有权判定、Compose 参数或 Colima 范围。
- `tests/test_local_launcher_contract.py:209–297` 覆盖两个窗口各自的成功、非零完成和仍运行，共六种情况。hook 必须实际触发、完成标记和命令日志必须吻合；不是仅凭重复绿测试推断修复。旧 Web fixture 在 `:110–148` 将相同环境传给自有进程，并在 TERM trap 安装后握手，移除原忙循环。
- 所有会执行停止器的合同测试均通过自有 PATH stub 覆盖 docker/colima，并使用自有 runtime。旧 Web PID 指向测试自行创建的进程；异常清理局限于自有进程或其独立 session。stale-PID 测试核对其自有“无关进程”未被停止。没有发现新增通往真实共享 VM/容器的测试路径。
- 真实模型验收文档正确区分 9 个案例与最多 7 次真实提交。Q1 明确在保留前同 key 重放；Q4 明确放弃后不复活终态 Run；Q5/Q6 保留、重开、精确 Undo。Q4–Q6 依赖相应加轨成功且和声可证明，失败不补调用。Q8/Q9 明示零调用守卫，Q7 模型拒绝不冒充音乐生成成功。
- CNY1/7 次/12000 total/3072 output/8000 bytes/0.672 元均被写为待批准的新阶段计划。`12000 × 8 / 1000000 = 0.096`，七次 `0.672` 算术一致；失败和超时计次数及可能费用。每次调用前落账/预留，unknown usage 或缺真实 reported-model 后暂停，批次金额门明确属于未来 harness，未冒称现有 Provider 已实现全局 CNY 闸门。
- 音频文档保留严格重复 SHA 失败，并把宿主样本最大 1 PCM24 LSB 限定为数值比较；没有放宽 Artifact bytes/SHA、IR/Revision、原轨或 HITL 身份。低电平 Master/Stem 求和不推广到 limiter 的一般非线性行为，主观音质与真实模型质量仍待验。

### Issues

#### Critical (Must Fix)

无已确认发现。

#### Important (Should Fix)

无已确认发现。

#### Minor (Nice to Have)

无已确认发现。

### Review scope and evidence

- 当前阶段：P2.3 质量收尾，不是新增功能。覆盖 MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P21。
- 审查范围：当前工作树相对 BASE `97d7a201bc482e390aab896dbc849920f8599236`，包括六个 tracked 修改和五个新计划/证据文件；HEAD 在审查开始与结束均为该 BASE。
- 已按 AGENTS 顺序读取 Decision Log、Project Guide、Implementation Status、Roadmap、项目 Skill 与对应 checklist，随后读取活动计划、钢琴语义/EQ 专项合同以及请求的四份计划/证据文档，核对完整本 slice diff。按照 requesting-code-review 的 code-reviewer 模板审查，没有派发其他 agent。
- `PROJECT_GUIDE.md` 开始/结束 diff 均为空；其最后修改提交为 `d68b900`。没有计算文档内容 hash。Guide 的 M2 历史顶栏未被误解为当前活动阶段；本次以最新状态/路线及明确委托的质量收尾范围判断。
- **本人独立运行**：
  ```text
  DEEPSEEK_API_KEY='' LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python -m pytest -q -p no:cacheprovider \
    --basetemp=${TASK_WORKSPACE}/research/p23-quality-closure/independent-pytest-tmp \
    tests/test_local_launcher_contract.py
  ```
  结果：`11 passed in 4.02s`。另运行 `/bin/bash -n scripts/stop_motif_forge.sh`、`git diff --check`、Guide diff，均通过。
- **仅阅读主线证据，未冒称独立重跑**：`controlled-before.json` / `controlled-after.json` 显示相同已完成子进程在 3.2 秒调度间隔下由缺少 Compose 变为包含 Compose；`red-result.json` 与 `red-second-window.json` 分别记录准确失败；`parallel-before.json` / `parallel-after.json` 各 12 次通过，不提供因果证明。`pcm-audit.json`、`storage-gate.json` 与报告的 14 份保留文件、1 LSB、严格身份不等陈述一致。
- 本人未运行真实停止服务、数据库、模型、渲染、下载或账户查询；未读取 .env、密钥或账单。仅报告与 pytest 临时 fixture 写入授权 workspace，repo/index/HEAD 未作修改。

### Recommendations

收尾时将计划待勾选项与证据中的 pending review 状态同步到实际完成结果；这是当前交付流程的最后记录步骤，不是新产品修复。真实付费验收仍须取得新授权，并在第一次发送前落实计划要求的持久批次账本/预留及真实响应身份核验。

### Declined to judge

- 真实模型在三首曲目上的意图表现、拒绝可靠性和音乐偏好：本轮未授权且没有真实调用；计划/fixture 不能证明这些结果。
- 实际账单、剩余额度及请求最终对应的精确模型权重：禁止读取账户/密钥；未发 HTTP 请求；预算仅核对所列公开费率的算术与守卫约束，不独立重验当前线上定价。
- PostgreSQL、UI/正式 Worker、历史 26 Jobs 的新一轮端到端运行结果：本 slice 没有这些产品改动，明确禁止重跑；历史结果仅作为继承证据。
- pinned Docker/跨平台字节确定性、普遍 Master/Stem 线性和人耳音质：本次没有重渲染或试听验收，既有 1 LSB 样本不能支撑这些扩张结论。
- 原历史偶发并行失败是否必然由本次竞态造成：没有该事件原始 trace；当前证据证明可控机制，不能倒推历史唯一根因。
- 任意忽略 TERM 的命令、内核不可中断进程及整套 Docker/Colima 的硬 wall-clock 上限：现有 helper 在 TERM 后仍有 `wait`，本修复没有新增强制 KILL/整栈 watchdog。独立测试证明的是当前 TERM 响应 stub 的有界路径和完成交错修复，不应读成所有进程的绝对结束保证；此类全停止矩阵未作为本 slice 已验收能力。
- 共享默认 Colima 的实际停止安全性：生产停止范围是已有行为，本次只审查没有扩大它及测试确实隔离；没有执行真实关闭，不把本审查当作共享 VM 下允许运行停止器的授权。

### Assessment

**Ready to merge? Yes — 就当前质量收尾 slice 而言可形成开发分支 checkpoint；本结论不授权 main 合并、部署或付费调用。**

**Reasoning:** 两处完成交错修复与目标一致，独立 11 条合同测试及 Bash/diff 检查通过，测试隔离和证据边界清楚。未发现当前路径阻塞；真实模型质量与新预算仍是明确待授权的后续验收，不属于本轮已完成结论。
