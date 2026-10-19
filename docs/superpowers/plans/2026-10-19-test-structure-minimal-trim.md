# P1 supporting task：测试结构审计与最小精简

2026-10-19；MF-P15/P16/P17/P18/P21；不改变产品功能。Guide 在 e3d9438、当前 HEAD 6099fca，Guide 无 diff。用户要求下一实施阶段前去除为测而测；C1 代码仍为本任务未提交改动，分开提交。

只读 AST 清点 127 个 Python 文件：unit 414、integration 70、eval 17、root 37 个定义；参数化执行数另计，没有完全相同 AST body。read_text/mock 只作人工检查线索，不等于低价值。root 基线实际 38 passed/2 failed，pytest 8.81s、总进程 9.852s；两 fail 分别为过期英文 README 段落位置和已经更新的“只读时间线”文案，并非运行时失败。停止流程隔离 fake-binary 安全测试占 7.29s，保留。

最小批次：删除 S2/S3/S5/S6/S7 五个门禁自登记或 package 别名拼写检查；删除过期 LangSmith 文案位置测试（现行专页人工核实，保留真实 compose 解析密钥隔离及 .env.example 默认关闭测试）；删除 S3 一个过时 UI 字符串断言。S5 node --check 随唯一 metadata test 移除，实际 browser stage 仍执行脚本；不替换成另一组镜像实现断言。

S7 阶段脚本移除两处确切重复：S7 Eval 不先单跑再全 eval；build:web 只在 generate:openapi 后执行一次，其他门不删。run_s7_eval_report 是报告生成，不是重复执行测试，保留。

保留缺陷历史、安全边界、版本/hash/幂等/取消恢复/真实文件/真实 PG 回归。保留现有 unit、web、eval、browser journey，不声称新钢琴持久 Undo/古典新轨隔离已实现。长音频探针独立脚本按需调用，不加入日常 pytest。未做广泛删测试/改音乐逻辑/换语言。

验证：同一 root 范围各一次 before/after，记录绝对耗时及噪声；不据单对样本宣称提速。Ruff 仅变更测试、bash -n 阶段脚本、独立一次 diff 审查；C1 音频回归单独记录。无需为文档重跑全 suite/旧 Compose。


完成：after34 passed/7.91s（进程8.819s），Ruff/bash/diff通过，一次独立审查无阻塞。额外测试隔离修正为compose --env-file /dev/null，保留真实配置检查但不自动加载.env。C1先独立提交a6fd5ba；本批单独checkpoint，不含新音乐功能。
