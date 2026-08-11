# Motif Forge Web Studio 与视觉规范

> 状态：首版 UX/UI 合同
> 制作端：桌面浏览器
> 移动端：试听、查看与审批

## 1. 产品体验原则

1. 时间线是主角，AI 是侧边协作者，不用聊天窗口遮住作品。
2. 用户始终知道当前 Branch、Draft、Committed Revision 或 PreviewCandidate；Preview 不是已提交版本。
3. 播放、拖动、选择等本地操作即时响应；服务器生成与渲染显示真实持久进度。
4. 简单 AI 修改自动落地但可 Undo；创意性变化先展示范围、差异和试听。
5. 科幻感用于解释声音与 Agent 状态，不牺牲密集工作区的可读性。
6. 空、加载、部分成功、失败、冲突、取消和恢复都是正式页面状态。

## 2. 设计参考与转化

- [Bitwig Studio](https://www.bitwig.com/overview/)：采用中央 Arranger、上下文 Browser、Inspector 和可切换编辑面板的结构思想。
- [Ableton Live 12](https://help.ableton.com/hc/en-us/articles/12243771208092-Navigation-and-View-Options-in-Live-12-FAQ)：采用高信息密度、可折叠 Mixer/轨道控制和键盘工作流。
- [Arturia Pigments](https://www.arturia.com/products/software-instruments/pigments/overview)：采用颜色编码、音频响应动画、拖拽关系与清晰调制反馈。
- [Vital](https://vital.audio/)：采用波形、频谱、包络、LFO 的实时可视化以及提交前预览思想。

Motif Forge 不复制这些产品的控件外观；它将专业 DAW 的稳定结构与轻度“光谱实验室”语言结合。

## 3. 视觉系统

### 3.1 色彩

| Token | 值 | 使用规则 |
|---|---:|---|
| `surface.canvas` | `#0B0E14` | 全局背景 |
| `surface.panel` | `#121722` | Header、Inspector、Track header |
| `surface.raised` | `#182130` | Modal、Popover、选中面板 |
| `surface.hover` | `#202A3A` | hover/active row |
| `border.subtle` | `#202838` | 次级网格 |
| `border.default` | `#293346` | 面板边界 |
| `text.primary` | `#E8EEF7` | 主文字 |
| `text.secondary` | `#93A1B3` | 描述/时间 |
| `text.muted` | `#647286` | 禁用/低优先级 |
| `accent.primary` | `#62E6FF` | Playhead、主按钮、链接 |
| `accent.agent` | `#9B7CFF` | AI、Graph、生成状态 |
| `accent.creative` | `#FF65C3` | Preview、创意差异、选区 |
| `semantic.success` | `#55DDA4` | 成功/已就绪 |
| `semantic.warning` | `#FFB45E` | 低置信度/质量警告 |
| `semantic.danger` | `#FF6B7A` | 失败/高风险 |

轨道颜色使用独立的可区分类别色板，不能复用 success/warning/danger 表示乐器，否则状态与身份混淆。

### 3.2 科幻效果边界

允许：

- 播放头的窄幅柔光。
- AI 选区的紫—洋红细线渐变。
- 生成/分析时的低频率光谱动画。
- Run Graph 的细线连接和脉冲状态。
- Modal/Inspector 的轻微背景噪声与深度阴影。

禁止：

- 大面积持续闪烁、强 Bloom、不可关闭的动态星空。
- 在 Clip 文本和网格后放高对比渐变。
- 仅用霓虹颜色表达审批、危险和错误。
- 长时动画影响播放、拖拽或 Canvas 帧率。

尊重 `prefers-reduced-motion`；音频可视化可暂停但播放不能因此停止。

### 3.3 字体与密度

- UI 使用清晰的无衬线字体；数字、BPM、bars:beats、dB 使用 tabular numerals。
- 正文最小 13px，关键按钮/表单不小于 14px。
- 默认 dense 布局，但可点击目标至少 28×28px；移动审批目标至少 44×44px。
- 采用 4px 基础间距，面板主要间距 8/12/16px。

## 4. 信息架构

| 页面 | 主要任务 | 关键状态 |
|---|---|---|
| Project Home | 新建、导入、恢复 Run | 空项目、最近版本、失败 Run |
| Import Review | 检查音频、BPM/key、对齐 | 上传、分析、低置信度、拉伸 |
| Brief / Plan | 输入需求并批准计划 | 验证、知识来源、Plan diff |
| Compare | A/B 同步试听与选分支 | 候选部分失败、指标差异 |
| Studio | 时间线编辑与 AI 局部操作 | Branch、Draft、Committed、PreviewCandidate、冲突 |
| Export | 选择格式并获取产物 | 排队、渲染、质量警告、下载 |
| Run Inspector | 查看 Graph/Tool/Job/成本/失败 | checkpoint、retry、partial |
| Eval Lab | 跑 Eval/Baseline、看失败分类 | dataset/version/report |

## 5. Studio 布局

```text
┌──────────────────── Transport / Project / Revision / Run status ────────────────────┐
├──────────────┬──────────────────────────────────────────────┬───────────────────────┤
│ Track Header │ Timeline Canvas                              │ Inspector / AI Panel  │
│ mute/solo    │ ruler / sections / clips / selection         │ properties / request  │
│ gain/pan     │ playhead / automation overlay                │ impact / diff / HITL  │
├──────────────┴──────────────────────────────────────────────┴───────────────────────┤
│ Bottom Dock: Sound Catalog | Piano Roll Canvas | Mixer | Run / Versions             │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

- Transport 和 Track Header 在横向滚动时固定。
- Timeline 是唯一主滚动区域；底部 Dock 可折叠、可调整高度，但不使用固定页面高度导致窄屏溢出。
- Inspector 可折叠；AI 请求始终绑定当前 selection，并在发送前显示作用范围。
- 面板尺寸保存为项目外的本地 UI preference，不进入 ArrangementIR。

## 6. 前端状态分层

### 6.1 Server State

TanStack Query 管理 Project、Branch、Revision、Run、PreviewCandidate、Asset、Export。Query cache 不是事实源；SSE 触发投影更新或 invalidation。`current_revision_id` 只展示 active branch head 的服务端投影。

### 6.2 Editor Draft

Zustand Store 建议拆为：

- `base_revision_slice`
- `target_branch_slice`
- `draft_commands_slice`
- `selection_slice`
- `viewport_slice`
- `history_slice`
- `playback_projection_slice`
- `conflict_slice`

Draft 保存命令而不是任意深度修改后的第二份 IR。渲染投影可以缓存，但必须能由 Base IR + Draft Commands 重建。

### 6.3 Audio Runtime

`AudioEngine` 是 React 外部服务：

- `load_revision_projection`
- `apply_draft_projection`
- `play/pause/stop/seek`
- `set_loop`
- `preview_asset`
- `dispose`

React Component 不创建或持有 Tone Node。Tone Context、Transport、Buffer cache 和调度生命周期由 AudioEngine 管理。

## 7. Canvas/DOM 边界

### Canvas

- Timeline grid、Section、Clip body、波形 peaks、playhead、selection。
- Piano Roll grid、NoteEvent、velocity overlay。
- 高密度 automation curve。

### DOM

- Track Header、Transport、菜单、按钮、输入框、Inspector。
- Canvas 对象的焦点代理、ARIA label、键盘操作提示。
- Context menu、Tooltip、Toast、Modal、审批卡片。

WaveSurfer 只用于 Import Review 和选中 Audio Clip 的详细 waveform/region 编辑。Canvas 时间线使用 Worker 预生成的降采样 peaks，不为 12 轨各创建 WaveSurfer 实例。

## 8. EditorCommandBus

所有人工操作转换为领域命令：

```text
pointer gesture
→ interaction controller
→ snap/selection calculation
→ EditorCommand
→ local validation
→ draft reducer
→ AudioEngine projection
→ debounced/manual command batch commit
```

拖拽过程中只更新 ephemeral preview；pointer up 后生成一次 `move_clip`，不能每个 mousemove 都写命令/API。

### 8.1 保存与 Undo

- 连续旋钮/拖动在交互结束时折叠成一个 Command。
- Draft 可本地 undo/redo。
- 已提交版本的 Undo 发送 `POST /projects/{id}/undo`，创建新的反向 Revision，不移动数据库历史指针假装没有发生。
- Autosave 只提交通过本地 Schema 的 Command Batch；离线/网络失败时保留 Draft 并显示未同步状态。

## 9. AI 编辑交互

### 9.1 请求前

AI Panel 显示：

- 选中轨道和 bars 范围。
- 锁定材料。
- 当前 key/chord/rhythm 摘要。
- 用户意图。
- 预测 ChangeImpact 和审批预期。

### 9.2 L0/L1

- 显示真实运行进度。
- 服务器提交后播放新的 Revision。
- Toast 展示“修改了什么”、作用范围、Undo。
- 如果真实 diff 升到 L2/L3，不自动应用，自动切换 Preview UI。

### 9.3 L2/L3

- 使用洋红/紫色 Overlay 标出改变范围。
- 展示 before/after 结构 diff、试听和依据。
- 操作为 Approve、Reject、Keep as Branch；批准后 UI 等待新的 `revision.committed`，不把 Preview ID 当作 Revision ID。
- 不显示原始 chain-of-thought；只显示结构化证据、知识来源和规则命中。

## 10. Import 与 Time-stretch UX

Import Review 分阶段显示：上传 → 校验 → 解码 → 波形 → 分析 → 用户确认 → 拉伸。

- BPM/key 低置信度使用 warning，并允许用户输入/拍点确认。
- 拉伸开始后，原始音频仍可按原速度试听，并明确标记“尚未对齐”。
- Derived Artifact 完成并通过质量检查后才提供“对齐后试听”。
- 质量异常显示 ratio、检测结果和恢复原始 Clip 选项。
- 绝不通过改变音高的 playbackRate 冒充首版 pitch-preserving 功能。

## 11. Run 状态组件

全局 Run Indicator 显示：

- 当前 phase、已完成/总步骤的语义进度。
- 正在运行的模型/Worker 类别，不暴露内部 reasoning。
- queue wait、render progress、重试次数。
- Cancel、Resume、View details。

Run Inspector 使用 Graph 视图，但节点颜色必须有文字状态：queued、running、waiting human、retrying、partial、completed、failed、cancelled。

## 12. 页面状态矩阵

| 状态 | Studio 行为 |
|---|---|
| 空项目 | 显示 Create from Brief / Import Audio 两个主入口 |
| API unavailable | 保留 Draft，禁用服务器写入，提供重试 |
| SSE disconnected | 显示 reconnecting；用 Last-Event-ID 恢复 |
| Worker delayed | 显示 queue wait，不伪造百分比 |
| 单候选失败 | 保留可播放候选并显示 partial |
| Revision conflict | 冻结提交、展示新 Base 与本地命令 |
| License rejected | 不加入项目，显示来源与原因 |
| Budget exhausted | 展示最佳可播放版本与未解决问题 |
| Run cancelled | 保留已提交版本和可复用 Artifact |
| Time-stretch failed | 回退原始 Clip，不破坏项目 |

## 13. 响应式与移动端

桌面最低目标宽度建议 1280px；低于该值：

- Inspector 和 Bottom Dock 互斥显示。
- Track Header 可缩窄但保留 mute/solo/名称。
- Timeline 保持横向滚动，不压缩所有小节到屏幕内。

移动端只实现：Project 列表、试听、Plan/Preview、A/B 选择、审批、Run 状态和下载。不承诺 Canvas 精细编辑。

## 14. 无障碍与键盘

- 播放/停止、撤销/重做、缩放、移动选择、分割、删除、打开 Inspector 有键盘命令。
- Canvas selection 有 DOM live region/属性面板同步说明。
- 焦点顺序不随 Canvas 重绘丢失。
- 对比度、非颜色状态、Reduced Motion、屏幕阅读器标签进入 UI 验收。
- AudioContext 首次启动必须由用户手势触发，并给出可理解提示。

## 15. 性能门槛

在代表性设备上测试 5 分钟/12 轨：

- Timeline 拖动/缩放保持可用，不因 waveform 解码阻塞主线程。
- peaks、IR 解析和大型 diff 可移入 Web Worker。
- 不为未展开轨道创建昂贵 WaveSurfer/频谱实例。
- 音频调度使用 Tone/Web Audio 时间，不使用 UI animation timer 作为音乐时钟。
- 科幻动画在播放或拖拽压力下可自动降级。

## 16. UX 验收清单

- 用户能区分 Branch、Draft、Committed Revision 与 PreviewCandidate。
- L0/L1 有清晰 Undo；L2/L3 不会未经批准落地。
- 导入、生成、渲染、恢复显示真实事件。
- 所有错误都有下一步，终态能在刷新后恢复。
- 长轨道名、空库、窄屏、横向 overflow 和大缩放范围正常。
- 色彩和动画没有降低时间线可读性。
