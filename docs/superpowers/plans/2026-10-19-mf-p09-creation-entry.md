# MF-P09：古典/爵士新建入口与 legacy 兼容

Stage P1-MF-P09；关联兼容/界面 MF-P10/P13/P15/P16/P18/P21。BASE `a44bbf3580385102dae97be3d17fc41db94a5017`，Guide同revision/clean。依据已批准ADR-019、P1最小钢琴计划TaskD.4与用户明确继续指示。保持当前手动Sol/xhigh，不新增产品取舍、权限、语言、模型调用或发布。

这是现有BriefForm/Home的有限调整；复用已批准设计而不重复审批：新建只提供classical_chamber/jazz_harmony_improvisation，默认第一项古典；原四个后端StylePack ID/旧Run/Revision/Artifact/播放/导出保留。固定钢琴入口与原作品/导入路径保留。只整理新增入口与相关文案，不把新建Brief自动升级为真实钢琴/IRv2，不声称音乐质量改变。

## Task 1

1. RED：改现有Brief页面行为测试，验证仅两项、默认古典无需重新选择也正确提交、爵士可显式提交；保留纯器乐/约束/预算/错误逻辑。首页现有测试核对古典/爵士聚焦及旧作品打开路径，避免新建重复布局/元数据测试。
2. GREEN：只收窄BriefForm本地new-composition类型/选项/default及解释；首页能力说明和高级乐器示例同步。共享Schema/StylePack enum/PlanReview/CandidateCompare/Studio/Export不删legacy分支。
3. 必要验证：目标Vitest、现有legacy风格domain/Eval与Studio/Export回归、tsc+web build；一次真实Chromium访问built UI（task-local静态server/API fixtures），桌面/390px新建两项/默认/爵士payload，旧作品路由/播放/导出显示。无PG/Provider/队列/新渲染，明确fixture不等于后台音乐生成。
4. 一次新上下文独立审查/最多一次有界修复，针对入口与legacy消费者，不重复P1音乐长链或全阶段635检查。Guide只同步原批准方针的当前实施状态；更新Status/TECH及本地checkpoint。
5. 清理只限本Task临时server/browser/脚本中间物；保留accepted报告/screenshots/currentwebdist、音源/WAV/其他任务资源。没有Docker缓存/DB mutation，不prune共享资源；记录before/after与source范围。交付剩余限制，P2+不自动开始。

Preflight：BriefForm local StyleId/option/default→CreateAIRunInput仍为原schema，后端四ID及persisted PlanReview/CandidateCompare仍读四类，不能改共享type来过滤新建。首页“4种风格”与默认入口收敛冲突，同步为“古典与爵士”；AdvancedBriefFields默认乐器示例改为钢琴/弦乐/低音提琴。已有入门钢琴不代表生成器音源升级。

验收记录：作者RED3→focused21/Web93/Python19/build通过；一次fresh review无findings（独立UI25/Python14/tsc），无修复回合。built-UI fixture与legacy真实旧媒体消费、390px检查见docs/evidence/2026-10-19-mf-p09-entry.md；后台/模型/新渲染未运行。当前状态同步、本地checkpoint与最终窄门由作者收口，不启动P2+。
