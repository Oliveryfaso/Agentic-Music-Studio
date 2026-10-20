# P2.3 首批三曲接入合同

日期2026-10-20；BASE d68b900，干净。MF-P05/P06/P08/P09/P11/P13/P15/P16/P17/P18/P21。

用户已授权主线继续三曲导入→加轨→试听→保留/放弃→重开/Undo→完整导出及正常开发分支push；不合main、不部署。主线唯一代码集成者，资源和交互线独立交付。本授权覆盖历史仅研究限制，不重复询问。

## 来源与范围

- `c01-minuet-g-a16.v1`：16小节、3/4、G大调、100 BPM、64音。
- `c02-la-candeur-a8.v1`：8小节、4/4、C大调、112 BPM、61音及1个谱内休止。
- `j01-bethena-a-first8.v1`：8小节、3/4、G大调、120 BPM、26音。

只接入固定principal MusicXML。原LilyPond只作文本不执行。保留旧欢乐颂ID、原manifest与schema。未知ID/伪造hash/来源失配/装饰音版本拒绝。

ZIP SHA256 `6b559878b4ce92ce3342084f76deebfd8f37aae77a4723d514793e5d444edb49`。资源复核2026-10-20核对30 checksum、5谱源、32小节、151音及1休止一致；无新增素材缺陷。不是独立审谱/人耳验收。界面与导出保留声部/小节选取、改速、装饰音/重复/其他声部省略说明，Public Domain不称CC0。Bethena三份源文件分别hash。

## 不变量和版本

复用同一Parent Graph、不可变Revision、hash绑定HITL、持久计划和现有钢琴/Worker。PPQ480，每份导入另加1小节尾音释放；不与谱内休止混淆。无新音频引擎/IR版本，旧v1-v5声音不改写。新伴奏是创作，不是原左手声部复原。C02原谱G7/B、D7等超出当前能力，不能静默近似并称忠实还原。

领域registry固定ID/XML hash/拍号/调/小节数；应用按固定打包路径检查所有源文件、rights及conversion哈希。新语义请求`piano-semantic-request.v2`带`beats_per_bar`，新`accompaniment-plan.v2`支持C/Dm/Em/F/G/Am或G/Am/Bm/C/D/Em（按原调）；120 ticks/步，3/4每bar12步、4/4每bar16步。旧request/plan v1只用于旧16小节4/4来源，默认和声/哈希保持。新record v2与旧record v1同时可读；0030显式扩展并阻止存在新来源、新请求或新record时降级。

## 用户行为与失败

目录可选三曲与旧例，换曲清空来源确认和旧请求意图，导入名字来自当前曲。规则/语义伴奏按实际拍号、小节数编译；局部修改仅新增第二轨连续1–4小节，保留原和声和范围外音符。请求拍号失配、越界、coverage不足、3/4 gate越界、未知和弦、不能证明和声、旧格式冒充新来源，均在模型前或持久结果前拒绝。候选仍需试听确认；reject不推进head，Undo精确返回父版。

## 验收与预算

新增付费调用0，使用离线planner fixtures验证接线，不声称真实模型质量或审美验收。累计¥10及每Run1请求/12000tokens、无隐式重试不变。先RED/GREEN，再相关回归，真实PG/正式Worker三曲闭环，一次fresh独立审查及至多一次修复复核、storage gate、文档、开发分支push。刷新/重放不重复支出。短选区实时EQ在三曲稳定后另开顺序阶段。
