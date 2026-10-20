# P2.3 质量收尾 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; one fresh whole-slice review before push.

**Goal:** 给真实模型质量验收准备可批准的9例/预算，修复已复现停止器截止竞争，澄清宿主1LSB证据边界。
**Architecture:** 保留单Parent Graph/硬预算/HITL/不可变Revision/权威hash；不改模型、音频、IR、DB或UI。仅修scripts/stop_motif_forge.sh及其隔离合同测试；真实调用待独立授权。
**Tech Stack:** Bash兼容现有Mac Bash、Python/pytest，现有环境。
**Spec:** 用户本轮质量收尾指令、P2_SEMANTIC_PIANO_CONTRACT.md、PIANO_EQ_CONTRACT.md与本计划约束。

## Global Constraints

BASE97d7a20，Guide最后d68b900/start diff空，main/Guide不改，不强推/部署，不安装工具/下载模型，不重跑旧26Job或旧媒体。MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P21。现有开发分支正常push已授权；本轮付费调用未授权。旧账本保持4次/7228tokens/上界0.023852元（非账单），CNY10不重置。

## Review Focus

- 子命令成功完成与超时检查交错时，必须返回真实成功，不漏停Compose。
- 同一交错下非零退出不得误当成功；当前响应TERM的未完成探针仍按截止门停止。
- 测试只能调用自有docker/colima stubs，不能停止共享VM、容器或不相关进程。
- 预算文档不能冒充新授权或现有全局CNY闸门，未知usage/身份与失败必须暂停。
- 1LSB音频比较不能取代Artifact/Revision/HITL精确身份，严格SHA失败保留。

## Task 1: 验收与费用准备

Files: docs/evidence/2026-10-20-p23-live-model-acceptance-plan.md / .json。
- [x] 白名单Settings核对当前模型/官方endpoint/超时/局部单次门，不打印SecretStr/环境/配置对象。
- [x] 9例矩阵：三曲append+局部modify六例，unsupported模型拒绝1例，和声歧义/越界零调用2例；原轨/外域/Undo和人工评价分列。
- [x] 提出本轮CNY1、最多7次、每次12000total/3072output/8000bytes，最坏峰值预留0.672元；单独申请、不自动执行。

## Task 2: 停止器截止竞争 RED→GREEN

Files: scripts/stop_motif_forge.sh；tests/test_local_launcher_contract.py。
Interfaces: run_quiet_with_timeout(seconds, command...)返回真实命令状态或真正超时124；不得在已完成时返回124。
- [x] 系统调查：真实脚本仅自有stubs，受控父调度延迟复现“info已成功→误124→跳过down→成功文案”；普通并行12/12通过，不作为修复。
- [x] 写确定性完成/失败/仍运行三类截止交错测试，先观察成功类在旧脚本RED。
- [x] 截止路径重新确认child，已完成则wait返回真实status，不延长deadline；修正旧测试env/ready握手，不运行真实停止器服务。
- [x] 窄pytest、受控原探针、普通小批并行/root回归；禁止用反复通过率代替确定性红绿。

## Task 3: 证据/独审/交付

Files: docs/evidence/2026-10-20-p23-quality-closure.md / .json / -review.md；IMPLEMENTATION_STATUS、NEXT_DEVELOPMENT_ROADMAP、TECH_EVOLUTION。
- [x] 核对M1/M2既有1LSB比较和Master两Stem2LSB门；补精确适用边界、严格重复SHA失败及单次Artifact身份不得放宽。不重新渲染。
- [x] 一次fresh独立审查当前slice；根因机制与原历史失败因果分开，最多一次限定修复复核。
- [x] 精确自有缓存/进程/保留媒体检查，Guide/main差异，正常提交推送并核对远端；验收计划与预算交父端批准。

## Ledger / Rulings

- Task1 complete：Settings白名单/公开价/历史账本/9例矩阵与独立预算草案；无真实调用。
- Task2 complete：两窗口先后1RED/2GREEN与1RED/5GREEN，最终合同11/完整Python885；Bash/Ruff-format/diff、3.2s探针修前漏Compose/修后执行，普通并行前后各12绿不作因果证明。
- Final review：fresh无确认Critical/Important/Minor，独立11合同/Bash/diff/Guide；无作者修复复核。
- Task3：数值只读审计与14保留文件hash完成；自有stub/测试进程关闭，未产过时构建可清，无prune。开发分支Git checkpoint与remote HEAD由任务回执记录。

- Ruling: 新阶段CNY1/7次只是待批准提案，不用旧CNY10自动授权，不把真实音乐质量/偏好、账单/额度/精确响应权重当已验（review D1/D2）— 当前0真实调用且只核公开价格/白名单 — 若错会未经批准花费或误报质量/费用。
- Ruling: 只称已证明的deadline竞态，不倒推原无trace偶发事件必然同因（review D5）— 缺少历史事件数据 — 若错会漏掉另一个并行缺陷。
- Ruling: 1LSB只限宿主样本数值比较，strict SHA失败保留，不放宽身份/推pinned Docker、普遍线性或人耳质量（review D4）— 只读现有低电平样本 — 若错会误报确定性/音质。
- Ruling: 复用指定checkout/开发分支，workspace保存少量原始失败/审查证据，不新建worktree或删当前证据 — 逐文件SHA保护并发且用户需要可复查交付 — 若错可能遗漏并发改动或多保留约0.3MiB，可从manifest复核。
- Ruling: 不为shell修复重跑PG/UI/Worker/旧26Job（review D3）— 无这些业务改动且用户禁止重复 — 若错将缺少跨层新证明，出现实际跨层故障再单独验证。
- Ruling: 不扩展TERM-ignoring/内核不可中断命令的强杀或整栈watchdog（review D6）— 继承helper在TERM后仍wait，当前只证明TERM响应child和完成竞争 — 若错极端命令仍可能卡住，不承诺绝对3秒退出。
- Ruling: 默认Colima既有停止范围保持，不实际执行/授权共享VM关闭（review D7）— 本轮真实脚本测试全部stub隔离 — 若错共享VM实际停止安全性仍未验证，后续运行必须按所有权和用户范围处理。

Deferred minors: 无新确认Minor；既有Provider缺model回退等历史项不在本轮修复范围。
