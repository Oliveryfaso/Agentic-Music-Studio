# P2.3 目录与确定性规则路径集成

Base 4a7c43d；Guide last revision d68b900/clean。覆盖 MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21。

目标：用户在真实目录选择审核片段、逐曲确认，导入正确的原谱/工作分支，按真实小节/拍号添加规则伴奏；保留/撤销及导出复用原Parent与Worker。新曲semantic v2尚未实现，因此新曲自然语言和两轨局部生成明确禁用；旧谱v1语义保持。

输入为固定版本score IDs和已核对资源，不接受路径/URL。输出为不可变IR/Revision、来源报告与现有候选/导出合同；无新增运行时、模型、迁移或数据下载。新增真实meter/key/bpm DTO字段由OpenAPI生成，禁止手写冲突DTO。

- [x] RED：目录选曲/确认/key-body绑定、未知回执重试/刷新身份、同ID元数据变更使确认失效；C02规则F、new source semantic禁用；Studio经典来源路由。
- [x] 复用已验证27文件后端候选；从4a7c43d重算差异，不叠加旧35文件patch。接既有ReviewedScorePicker/reviewKey概念和最小作用域样式。
- [x] 聚焦Python/Eval/Web、OpenAPI、完整TS/mypy/Ruff和workspace外置生产build。旧v1语义回归保持；无paid调用。
- [x] 正式审批精确写入真实仓库，再真实repo相同聚焦检查；新build始终输出workspace，禁止覆盖当前固定试听dist。
- [x] 一次隔离PostgreSQL实际目录/三曲导入/重放/来源报告/保护/回滚；Worker Job0，不重跑旧26Job；有意义的新增边界只验证新目录UI与实际API请求。
- [ ] 一次fresh独审、至多一次修复复核。更新状态/证据/技术演进，Guide diff与试听固定build哈希复核；scope storage、正常dev commit/push，main不变、不部署。

回执未知时锁曲目/确认/请求体，显式同key重试并在sessionStorage保留身份。只有确认发生在写入前的失败可重选。失败/空目录/载入/来源消失各有真实状态，不自动重试或假完成。

现有3曲/26Job与后段6Job的候选证据保留，不冒称本次重跑；人工听感、semantic v2/0030、实时EQ和主题仍独立未完成。当前只读验收入口与10:36:58UTC截止时间保持，不延长/替换用户正在听的固定构建或音频。
