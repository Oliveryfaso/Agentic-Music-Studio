# 审核曲库双钢琴个人日用 Beta：分阶段执行计划

2026-10-21；基准 dev21dbd8dc34e745deef5e0bde97e997a753ab2965。声音沿用获认可的36d2a3e及本次局部结果。
范围 P2.3→个人Beta；关联 MF-P01/P02/P04/P05/P06/P08/P09/P10/P11/P13/P15/P16/P17/P18/P20/P21。

## 当前收口（2026-10-23）

B0/B1及B2限定客观链已通过，B3技术交付与运行说明本轮收口；真实浏览器播放/刷新返回/下载等仍为原前端工具依赖，没有新产品缺陷或新patch。今天真实GET/SELECT/空配置/11文件流式SHA及启动器--check通过，新增模型/POST/启停0；原10/21失败与更早记录保持历史。见[当前证据](../../evidence/2026-10-23-beta-current-closure.md)与[统一运行说明](../../PERSONAL_BETA_RUNBOOK.md)。下方按实际执行更新checkbox，不把UI或本轮模型append混入已过项。

## 不变量

- 主线唯一集成人；前端与资源线仅独立目录交patch，不写共享工作树、不启停共享服务。
- main/PROJECT_GUIDE不改、不公开部署；不扩曲库、乐器、Agent或重写音乐算法。
- 只管理本次明确拥有的进程/容器/网络，保留数据卷；不停止共享Colima/用户容器，不重启整机。
- 不读取无关凭据，保留默认付费禁用。用户后续另行明确授权过两个指定容器的临时模型测试窗口，10/22已结束并清空；本轮不读取/启用密钥。涉及新持久配置或权限仍停在具体步骤，不能沿用临时授权建立常驻访问。
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

- [x] 仅loopback暴露用户入口；定义独立Compose project、可复用持久测试数据与隔离媒体根，不借用用户数据库。
- [x] 缺Docker/依赖/挂载/审核包/配置明确失败，不自动管理共享VM，不偷偷采用其他声音或内部盘。
- [x] 审核钢琴包只读挂载，版本与manifest pin验证；不自动下载。整合资源线只读核验产物。
- [x] 模型默认禁用不删除；提供无秘密模板与明确启用边界，区分产品内置gate和任务附加gate。遇持久凭据/权限需求停在具体动作。
- [x] 正常启动/就绪/停止与保留存储代表性验收，给真实可打开入口；无服务不得声称E2E。

## B2：统一用户主路径与同环境恢复/交付

- [x] 集成前端独立patch，保留已有默认/请求身份/许可/保护语义；不重写成熟组件。
- [x] 先离线配置与边界守卫，不把模拟回执当最终实链；审查后制定最小实际调用批次预算。
- [x] 同一持久正常Beta：审核C02导入→规则伴奏R0→两轮真实模型局部修改R1/R2→后端A/B媒体及正常保留→新进程精确Undo U。10/22已执行，10/23当前重读/11文件验证；不是本轮新的模型append或放弃回合。
- [ ] 真浏览器实际播放/A-B切换、刷新/返回/重开、下载及键盘/窄屏：原前端工具尚不可用，无新patch；不要求用户先试听才继续工程。
- [x] 10/21 B2b正常关闭并重开相同数据，恢复作品/待审批状态与已知成功回放，无新模型；今天当前重读保持。不是新冷启动、整机重启或运行中模型崩溃验收。
- [x] 导出同一保存Revision的Master/MP3/真实分轨/MIDI/工程与来源文件，核对内容身份与已允许的宿主PCM容差，不追渲染碰严格SHA。
- [x] 10/21仅独立测试数据库与媒体副本恢复到空目标，39表/IR/容器内API读取通过；宿主18100入口失败保留，未覆盖原作品。其他三个worker历史额外重启原因/任务影响未决，不宣称共享环境全程无影响。
- [x] 区分自动化UI、真实模型、端到端、人工尚未验收；保留原始失败。

## B3：个人Beta交付

- [x] 汇总已做/未做/待用户项，精确费用、开启关闭最小步骤、可打开入口和恢复边界。
- [x] 每里程碑仅必要回归/独审，更新当前状态与路线，不把限定Beta写成任意曲谱/全曲库/多用户成熟。
- [x] 已清空临时模型配置并移除四个曾携key容器；本轮没有新临时运行资源或需清退目标。冻结保留数据/包/现存作品与唯一Beta供原前端验收，删除0bytes，不prune共享builder/卷或停仍需使用的服务。
- [ ] 待本次真实提交、正常推送与远端SHA回查后，以交付回执更新Git交付结果；不预写未来SHA。main/Guide/共享游戏环境保持。

普通小步骤沿已有授权继续。阶段可验收结果即时简报，具体审批只用于确实越过已批准凭据/权限/付费服务范围的动作。

B0 implementation scope: scripts/motif_runtime_owner.mjs (Node builtin only, nonsecret ownership receipt +exact Docker IDs), startup/stop wrappers and Compose ownership label. Stable per-checkout project/runtime namespace; no unowned-stack adoption; no VM start/stop. Web PID now also pins process start time. No frontend/API/credential changes in B0. Meaningful runtime ownership tests replace old assertions that required global Colima shutdown; no full music regressions for this shell-only slice.

B0 boundary note: initial real Docker reopen exposed a missing literal JSON brace hidden by the old fake. B0.1 separate tiny defect closure passed focused RED/GREEN, one narrow review and the real two-cycle boundary; original failure retained. B0 checkbox checkpoint/push is completed by the resulting Git checkpoint, not evidence of B1/B2 acceptance.

Historical B1 source checkpoint (2026-10-21; superseded by the later authorized runtime evidence, not the current blocker): nine-file profile/build/preflight patch installed,67focused +17independent pass, no review findings; actual public config6checks and host assets verified. Real bind probe125 fails because VM /Volumes/KINGSTON is ext4 placeholder rather than actual host share. No VM config/restart authorization, no image build/service/URL yet. B1 runtime and B2 checkboxes stay pending; user asked how to supply shared external path. Source checkpoint is explicitly not an accepted full Beta gate.
