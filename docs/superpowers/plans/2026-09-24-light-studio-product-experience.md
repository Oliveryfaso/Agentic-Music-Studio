# Light Studio — 产品体验升级计划

**目标：** 将现有 Motif Forge 升级为明亮、清晰、可持续创作的音乐工作台，并重写面向使用者和作品集读者的 README。

**基线：** main `b2b5d58`。用户授权系统性前端改版，明确保持底层实现和核心功能；此次不新增 Graph、API、依赖或付费调用，不启动 Docker，不提交或推送。

**方法：** 当前会话直接实施。使用 find-skills、frontend-design、redesign-existing-projects，交互变化先写 RED 测试，集中运行现有前端测试和浏览器验证。无需逐 Task 独立审查。

## 设计合同

- 浅色工作台：雾白画布、白色面板、深青绿操作色、墨色正文；音轨使用柔和紫/青/赭色。废止深色科幻外观，不改变数据或业务合同。
- 中文为主，保留 Studio、Graph、BPM、MIDI 等必要术语。主要操作写用户结果，ID、版本、来源证据渐进展示。
- 不使用虚假播放波形、假的运行进度或服务在线灯。所有作品与任务状态仍来自现有 API。
- 保留两次人工确认、版本冲突、重试/取消/恢复、外置存储错误和移动端只读编辑边界。
- 首页是创作入口，不是研发看板；创作流程解释清楚，Studio 是工作空间，Inspector 保留工程深度。
- 不新引入字体/CDN/图标库。用系统字体、CSS 和少量项目专属 SVG。避免过度稀疏，正文有足够信息。
- 涉及 MF-P01/P02/P03/P07/P11/P13/P15/P20 的呈现层；任何后端行为均保持原样。

## 执行步骤

### 1. 共享外观与创作入口

- [x] AppShell 统一导航、当前位置、跳至正文；导入页复用同一外壳。
- [x] 首页重组为创作入口、最近作品、工程说明。创建语义不变。
- [x] Brief 保留原 DTO 与验证，说明风格与后续步骤，支持中文列表分隔符。
- [x] 建立浅色 CSS tokens，修改 favicon 和 Canvas 色板，保证全部旧页面仍有可读的颜色。
- [x] RED：AppShell 当前导航/跳转目标、Brief 中文分隔符。验收：`npm run test:web -- AppShell BriefForm BriefPage ProjectHomePage`。

### 2. 审批、Studio 与交付

- [x] Run 显示任务阶段与下一步；计划摘要、候选证据和审批表单分层，不移除安全检查。
- [x] Studio 工具栏、选区、侧栏、底部面板与浅色 Canvas 协调，明确保存/试听对象。
- [x] RED：StudioDock 的选中面板与键盘导航。验收：`npm run test:web -- StudioDock StudioPage RunPage CandidateCompare`。
- [x] 导出区先展示文件，再展开步骤与技术标识；Inspector 让图和详情可读，保留证据。
- [x] 统一导入、About、Eval 的文案及视觉。验收：完整 `npm run test:web` + `npm run build:web`。

### 3. README 与产品合同

- [x] 参考 OpenMAIC 的信息顺序，原创重写：产品定位 → 截图 → 能力 → 快速启动 → 正式流程 → Agent 架构 → Eval/限制 → 开发文档。
- [x] 保留准确的启动前提、默认无模型回退、Key 安全、stop 数据保留与既有技术文档入口。无未经验证的性能/质量宣称。
- [x] 真实渲染应用的演示数据截图；明确标注演示数据，不伪称真实模型产物。
- [x] 更新 PROJECT_GUIDE 的视觉约束、决策记录和实施状态，不改变最终功能目标。

### 4. 浏览器验收与收尾

- [x] 采用隔离 HTTP mock 展示现有 API DTO，不新增产品 mock 模式。检查首页、Brief、审批、候选、Studio、导出、Inspector、导入、About、Eval。
- [x] 检查 1440px 桌面、390px 手机：无页面横向溢出、长标题可换行、关键操作可达、键盘焦点清晰。
- [x] 检查空/载入/失败/部分成功状态；断连不能被误报为完成，隐藏证据仍可展开。
- [x] 查看最终 diff，运行 `git diff --check`；记录验证结果与局限；关闭任务启动的浏览器和 Vite。

## 验证边界

前端交互与渲染是本次验收对象。既有 API、Graph、数据库、音频引擎、Worker 未变，不重跑 S1–S7 全套故障矩阵或付费验收。浏览器演示数据不能证明新一轮端到端音乐生成成功。

## 验收记录

- `npm run test:web`：36 个文件，82 个测试通过；新增交互已先观察到预期 RED。
- `npm run build:web`：TypeScript strict 与 Vite 通过。
- `.venv/bin/python -m pytest tests/test_local_launcher_contract.py::test_readme_leads_with_one_command_launch_and_current_product_status -q`：1 passed。
- `node scripts/run_product_ui_smoke.mjs --docs`：28 个桌面/手机页面状态通过；真实前端、隔离 HTTP 示例，不接触后端与模型；四张文档截图注明示例。
- 已查看实际截图并修正 Studio 面板位置、导出卡片密度、手机控件边界、Graph 标题排版与全页截图滚动位置。
- 后端/Graph/Schema/Worker/音频引擎和依赖无 diff；所有功能门保持，只有 Brief 中文分隔符、导航与键盘面板等小型呈现交互改进。
- 未提交或推送；无 Docker/Colima/付费调用。浏览器与 Vite 已由脚本关闭，真实端到端音乐生成不在此轮验收声明中。
