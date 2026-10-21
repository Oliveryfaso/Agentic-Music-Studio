# B2c：重开入口与两个只读状态合同

基线636d4aa；MF-P06/P13/P18/P21。主线唯一集成，前端原session继续负责页面消费与浏览器；不改main/Guide，不接凭据或模型，不变更旧项目容器/Colima，不重写音乐或Agent架构。

1. 核实原前端补丁sha/基线/DTO，先只装新增定向测试，在实际ProjectCard旧代码看到RED，再装唯一一行修正，GREEN及原首页2回归/typecheck。测试只证明渲染/导航/no POST，不冒充浏览器。
2. 去重并确定最小只读合同：ProjectWorkspace暴露项目/activebranch约束的未决钢琴候选发现（手工与semantic）；从已有Preview/MediaRun/AIRun业务记录取有界thread，再只读Graph核验权威phase/身份，明确多个候选、基版本过期、终态/过期排除、索引未覆盖早期阶段的边界。读取不创建Run/Job、不推进Graph或审批。完整具体合同先存工作区/交回前端，再测试先行实现；不增加通用索引平台或无必要迁移。
3. piano-capability新增独立semantic_generation配置投影。只报告本地configured/not_configured/unknown与稳定公开reason，不泄露key/URL/内部配置，不访问Provider，不改变音源available；模型配置不等同可用性认证。默认无配置/未知安全，规则伴奏不受影响。
4. 仅必要Python/SQL/接口/前端类型和OpenAPI校验。新边界用独立测试库，不能在正常Beta项目做fixture业务写入；不启动旧库/Redis/消费者，不接模型。若需新运行资源先限定自有资源和余量，避免与旧项目混用。一次fresh独审/最多一次窄复核，正常dev检查点/远端读回与证据；只有必要目标才构建，不为文档重建。
5. 给原前端准确合同、正常/空/多个/过期/不可用fixture与待消费项；root Undo按钮非阻塞提示仅登记，不擅自吞并前端职责。浏览器权限仍未解决，始终不得标记UI UAT通过。新模型调用和费用0，旧累计估计0.059998/同一10元不重置。
