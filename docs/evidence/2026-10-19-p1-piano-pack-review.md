# P1 包合同独立审查记录

2026-10-19；piano_contract_review；范围为823c4e7之后的本轮合同/适配准备，一次只读审查。审查者未改文件或运行浏览器/VM/模型。

1. Important：startSeconds=1、gateSeconds=.005，planner通过，但scheduler计算1.005-1=0.004999999999999893后误拒PIANO_PLAN_INVALID。实施方新增非零起点最短gate用例先RED，再改绝对时间比较，GREEN。
2. 原评Minor：probe的NaN可绕过比值断言。实施方基于“非loop声音失声时也可能通过本轮验收”重评为影响证据可信度，在同一次修复处理。先将旧断言原样抽到测试helper，再以静音/NaN输入RED，修为命名数值字段有限/正值校验。实际浏览器重跑暴露fixture描述字符串被Object.values误拒，另补RED回归后使用明确字段列表，GREEN。

最终实施方验证48条音频suite、tsc、宿主构建、短离线实际probe通过。未再要求第二轮审查；按一次修复约定用复现测试和完整相关回归关闭。无其他未处理Minor。真实源包许可/SFZ受解压能力阻塞，未将其从review范围排除后冒充已验：该资产门明确未完成。
