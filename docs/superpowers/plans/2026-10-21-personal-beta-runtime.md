# 审核曲库双钢琴个人日用 Beta：分阶段执行计划

2026-10-21；基准 dev21dbd8dc34e745deef5e0bde97e997a753ab2965。声音沿用获认可的36d2a3e及本次局部结果。
范围 P2.3→个人Beta；关联 MF-P01/P02/P04/P05/P06/P08/P09/P10/P11/P13/P15/P16/P17/P18/P20/P21。

## 不变量

- 主线唯一集成人；前端与资源线仅独立目录交patch，不写共享工作树、不启停共享服务。
- main/PROJECT_GUIDE不改、不公开部署；不扩曲库、乐器、Agent或重写音乐算法。
- 只管理本次明确拥有的进程/容器/网络，保留数据卷；不停止共享Colima/用户容器，不重启整机。
- 不读取无关凭据，不复制/写入/持久化现有模型密钥。保留默认付费禁用；涉及新持久凭据或权限的具体步骤单独说明并求确认，离线工作继续。
- 原官方已批准DeepSeek替代身份/符号音乐数据范围/累计人民币10元不变。旧估计0.059998非账单，不重置。付费先有界批次、逐次身份/数据/预算gate，无隐式重试。
- 真实全链仅正常进程、队列和用户API；可以自动化UI，不用fixture回执、人工完成Job或直接改库冒充用户链。
- 每一独立里程碑TDD→代表性边界→一fresh独审→最多一次有限修复复查→证据/状态/清理→正常dev提交推送。若仍有当前路径阻塞按AGENTS停。

## B0：资源所有权与安全启停（首先执行）

目标：停止器永不停止默认Colima；Compose与Web缺少精确所有权时拒绝操作，不能凭仓库名认领既有共享服务。

- [x] 核对现有启动/停止脚本与测试，定义持久但不含秘密的运行所有权记录。
- [x] RED覆盖共享Colima不被调用、无记录/错误上下文或资源身份不操作、合法自有资源精准停止、重复停止保留作品。
- [x] 最小实现与明确诊断；避免全局compose down、prune或按名称模糊杀进程。
- [x] Stub/代表性独立资源边界验证，独审及唯一有限修复复查，checkpoint与正常dev推送。

## B1：标准本机运行档位与审核资源

- [ ] 仅loopback暴露用户入口；定义独立Compose project、可复用持久测试数据与隔离媒体根，不借用用户数据库。
- [ ] 缺Docker/依赖/挂载/审核包/配置明确失败，不自动管理共享VM，不偷偷采用其他声音或内部盘。
- [ ] 审核钢琴包只读挂载，版本与manifest pin验证；不自动下载。整合资源线只读核验产物。
- [ ] 模型默认禁用不删除；提供无秘密模板与明确启用边界，区分产品内置gate和任务附加gate。遇持久凭据/权限需求停在具体动作。
- [ ] 正常启动/就绪/停止与保留存储代表性验收，给真实可打开入口；无服务不得声称E2E。

## B2：统一用户主路径与同环境恢复/交付

- [ ] 集成前端独立patch，保留已有默认/请求身份/许可/保护语义；不重写成熟组件。
- [ ] 先离线配置与边界守卫，不把模拟回执当最终实链；审查后制定最小实际调用批次预算。
- [ ] 同一持久环境正常启动→审核曲谱导入→真实加轨→连续局部修改→实际A/B→保留/放弃→精确Undo。
- [ ] 正常关闭并重开相同数据，恢复作品和恰当任务状态，不重复模型花费；不进行整机重启。
- [ ] 导出同一保存Revision的Master/MP3/真实分轨/MIDI/工程与来源文件，核对内容身份与已允许的宿主PCM容差，不追渲染碰严格SHA。
- [ ] 仅独立测试数据库与媒体副本做备份/还原演练，恢复到新目标，不覆盖用户作品。
- [ ] 区分自动化UI、真实模型、端到端、人工尚未验收；保留原始失败。

## B3：个人Beta交付

- [ ] 汇总已做/未做/待用户项，精确费用、开启关闭最小步骤、可打开入口和恢复边界。
- [ ] 每里程碑仅必要回归/独审，更新当前状态与路线，不把限定Beta写成任意曲谱/全曲库/多用户成熟。
- [ ] 精确关闭不需常驻的自有资源，保留声明的持久数据和可信回退点；清理前保留/删除清单。
- [ ] dev正常推送并远端SHA回查；main/Guide/共享游戏环境保持。

普通小步骤沿已有授权继续。阶段可验收结果即时简报，具体审批只用于确实越过已批准凭据/权限/付费服务范围的动作。

B0 implementation scope: scripts/motif_runtime_owner.mjs (Node builtin only, nonsecret ownership receipt +exact Docker IDs), startup/stop wrappers and Compose ownership label. Stable per-checkout project/runtime namespace; no unowned-stack adoption; no VM start/stop. Web PID now also pins process start time. No frontend/API/credential changes in B0. Meaningful runtime ownership tests replace old assertions that required global Colima shutdown; no full music regressions for this shell-only slice.

B0 boundary note: initial real Docker reopen exposed a missing literal JSON brace hidden by the old fake. B0.1 separate tiny defect closure passed focused RED/GREEN, one narrow review and the real two-cycle boundary; original failure retained. B0 checkbox checkpoint/push is completed by the resulting Git checkpoint, not evidence of B1/B2 acceptance.
