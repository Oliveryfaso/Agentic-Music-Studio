---
name: Motif Forge Instrument Workbench
description: 浅灰工作面、石墨控制与烧橙强调的器材质感音乐工作室。
colors:
  canvas: "#e9e7e2"
  surface: "#f9f8f5"
  subtle: "#dedcd6"
  text: "#25262a"
  muted: "#62635f"
  line: "#c5c3bd"
  line-strong: "#7b7773"
  accent: "#b3441c"
  accent-hover: "#943615"
  accent-soft: "#f4e6de"
  selected-channel: "#e2d2c7"
  secondary: "#6b5950"
  warm: "#9a492b"
  success: "#5b5551"
  warning: "#895600"
  danger: "#a52b3e"
  white: "#ffffff"
  button-hover: "#e8e5de"
  disabled-text: "#77736d"
  disabled-surface: "#e6e3dd"
  track-fill-1: "#bfc0c5"
  track-fill-2: "#dec3b1"
  track-fill-3: "#d2c6ad"
  track-fill-4: "#bbb5b2"
typography:
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "32px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.035em"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    lineHeight: 1.55
  numeric:
    fontFamily: "ui-monospace, monospace"
    fontSize: "12px"
rounded:
  compact: "5px"
  field: "6px"
  control: "7px"
  group: "8px"
  panel: "9px"
  card: "10px"
  form: "12px"
  chip: "999px"
spacing:
  xs: "4px"
  control-gap: "8px"
  compact-inset: "12px"
  group-gap: "16px"
  panel-inset: "20px"
  section-gap: "24px"
  page-inset: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.white}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.white}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "44px"
  button-text:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
    padding: "8px 0"
    height: "44px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.group}"
    padding: "10px 11px"
  navigation:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
    height: "44px"
  status-chip:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.chip}"
    padding: "0 9px"
    height: "26px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
  transport:
    backgroundColor: "{colors.subtle}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "8px 12px"
  channel-strip:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
    padding: "12px"
    width: "144px"
  eq-band:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
    rounded: "{rounded.group}"
    padding: "12px"
---

# Design System: Motif Forge Instrument Workbench

## Overview

**Creative North Star: "器材质感创作工作室"**

浅灰工作面承载音乐，石墨文字、明确的控件边缘和烧橙强调帮助用户识别当前动作。材质由浅内阴影、高光边和按压反馈形成；选中的音轨与正在操作的控制组有清晰归属。用户选定的 Midlife 参考已转化为这套实际前端，本文记录隔离源码中的实现，不把提案尺寸当作完成事实。

连续工作面贯穿作品、创建、计划、候选、Studio、设置和导出。信息按作品身份、操作、音乐内容和按需任务展开；版本来源、草稿状态及错误仍留在对应控制附近。现有 React/TypeScript/Vite、DOM 控件和 Canvas 编辑器继续使用，本轮没有新增依赖、纹理资产或外部字体。

**Key Characteristics:**

- 暖灰与石墨组成主体，烧橙用于主要动作和选择标记。
- 分隔线与可操作边界分工明确，浅凹凸只强调控制关系。
- 系统中文字体与等宽数字兼顾密度、轨名和时间读数。
- 混音通道、EQ 与保存版试听明确区分草稿参数和音频事实。

记录日期为 2026-10-28。阶段为个人 Beta 后的前端体验重构；呈现范围覆盖 MF-P01/P03/P07/P11/P13/P15/P20，MF-P06/P18/P21 的版本、恢复、请求与费用语义继续约束界面。实现基于 `af3a31aaef660b89f459681896d55c48b5a015be`；本文件描述源码候选，不代表运行 Beta 已部署。

设计事实来源是 [workbench.css](apps/web/src/workbench.css)、[styles.css](apps/web/src/styles.css)、[displayPalette.ts](apps/web/src/shared/displayPalette.ts) 和抽样组件。`main.tsx` 后加载 `workbench.css`，应按最终层叠读取。已人工查看最终 [1440px 混音图](docs/images/studio.png) 与另行保存的 390px 混音图实际像素；截图为 Mac 上 Chromium headless 渲染、合成 API 数据和静音 PCM，不能证明 Beta 部署、真实模型生成、主观听感或完整可达性。公开素材身份与限制见[截图来源](docs/images/screenshots-20261028.json)。

最终隔离候选验证：55 个 Web 测试文件、233 项通过；9 个首跑 mock 场景通过；TypeScript 与生产构建退出码为 0。修复前的独审发现三项请求归属/提交编辑风险，已通过一次限定修复与独立源码复核关闭。18 张最终页面截图来自用户 Mac 的 Chromium，所有 API 为公开合成 mock、媒体静音；不是 Beta 部署、真实生成或听感验收。外部交付目录保存逐项日志与截图测量。impeccable 本机引擎不可用，未安装或下载；sidecar 依照本机 reference/document.md 的 schemaVersion 2 格式手工生成，没有引擎或官方 schema 验证通过声明。

## Colors

前置 YAML 是实际色值表；下述名称说明用途。Canvas 使用同一份展示色板，颜色不序列化进 ArrangementIR。

### Primary

- **烧橙（accent）**：播放、当前主要确认动作、链接和范围控件；悬停使用 accent-hover。
- **浅赭底（accent-soft）**：轻量状态或选择背景。混音选轨另外使用 selected-channel，并有顶部烧橙标记、轨号及名称。

### Neutral

- **工作台灰（canvas）／面板白（surface）／凹槽灰（subtle）**：分别承载页面、编辑面与 transport 等控制槽。
- **石墨（text）／次级灰（muted）**：正文、刻度与辅助信息。success 为中性状态色，不能据其旧变量别名引入绿色。
- **分隔灰（line）／控件边界（line-strong）**：前者分区，后者定义输入、次要按键和通道组的可操作边缘。旧提案的控件边界及凹槽值已被实现替换，以前置 token 为准。
- **褐灰（secondary）／赭褐（warm）**：保留给已有任务与辅助语义，避免增加新的竞争强调色。
- **警告赭（warning）／危险红（danger）**：警告、失败与放弃等语义，配合文字及状态信息。
- **轨道灰与赭色（track-fill-1…4）**：Canvas 内容分类，始终保留轨号、名称或形状线索。
- **禁用文字与底色（disabled-text／disabled-surface）**：保留实体边界，全局按钮禁用时不再仅靠降低整体 opacity。

**The Control Edge Rule.** 操作边界使用 line-strong；分隔线不承担唯一控件轮廓。该 token 当前为 `#7b7773`，不得回抄旧提案的 `#797a76`。

**The Single Accent Rule.** 新控制沿用烧橙与中性灰。代码中的 `violet`、`cyan`、`mint` 是兼容标识，不是紫、青、绿设计许可。

## Typography

系统 CJK 无衬线栈同时承担标题与正文，没有加载独立展示字体。时间、dB、声像等数字使用系统等宽及适用的 tabular numerals；不用额外字体下载建立器材感。

| 已落地层级 | 使用与差异 |
|---|---|
| headline | 作品页标题；移动端缩为 28px。创建、设置和导出标题为 30px，Run 标题为 28px。 |
| title | 作品条目标题。Studio 名称在桌面最终规则为 20px、移动端 19px，行高 1.25；不套用大页面标题。 |
| body | 基础正文。表单标签与音轨名称主要为 14px；段落可按页面使用 1.6–1.75 行高。 |
| label | 辅助版本、轨道状态及说明主要为 12px；部分控制说明为 13px。 |
| numeric | 通道 dB 与声像读数，保持数字对齐；transport 时间使用现有等宽栈。 |

轨名保持自然英文单词换行，两行收口并保留完整名称的可访问说明；不能靠缩小字体容纳长名。桌面紧凑保存说明在本次精修提高为 12px；不依靠缩小文字压缩工具栏。480px 及以下普通文本输入、textarea 和 select 提升至 16px。

## Layout

全局 main 实际宽度为 `min(1520px, 100%)`；后置的 `max-width:1600px` 不会把它扩大为 1600px。常规桌面内边距为 24px 32px 36px，1099px 及以下为 20px，768px 及以下为 16px。作品、创建、设置、Run/导出内容限宽分别为 1280、960、880、1120px。Studio 单独使用 12px 20px 24px，桌面上侧最终为 8px；移动端为 12px。

间距以 4/8/12/16/20/24 为主要节奏，并保留控件所需的 6/10px 等局部值，不能把它描述为严格单一数学比例。项目栏、工作面切换、transport 与音乐面板连续排列。任务区关闭时不保留空白侧列；打开且空间足够时使用 `minmax(0,1fr) 340px`，1099px 及以下回到单列，任务区不再受 72vh 内滚动上限约束。

混音桌面由通道 bank 与 EQ/主输出邻接组成。每轨固定宽 144px，组内间隔 1px；超出空间时只在 bank 内横滚。768px 及以下，项目栏单列、操作换行、播放来源移到 transport 下方，混音详情接在通道之后。移动端三段 EQ 为逐段纵排，标题与数字同排、说明另起行，隐藏旋钮但保留数字输入。EQ SVG 固定 640×208px，坐标字号 12px，在局部容器横滚，不缩小到手机宽度。

限定精修后的 mock 记录中，1440×1000 页面全高为 1016px，390×844 为 1994px；两者页面宽度均等于 viewport。390px 工作栏从 339px 收为 245px；桌面 EQ 从 642px 收为 518px，主输出由 y971 上移至 y843。390px 图中主输出在 EQ 下方，仍需纵向滚动到达。这是两张样本的事实，不是所有轨数、字体、原生缩放或设备的溢出保证。

## Elevation & Depth

深度以面色、细边、高光和轻阴影组合建立。主工作面保持平稳；transport 像浅凹槽，实体按键和 EQ 旋钮得到局部高光。项目卡、主要 Studio 面板不依靠大外阴影分层。

| 实际角色 | 阴影 |
|---|---|
| 主动作 | `0 1px 2px #25262a26, inset 0 1px #ffffff26` |
| Transport 槽 | `inset 0 1px #ffffff80` |
| Transport 按键 | `inset 0 1px #ffffff55, 0 1px 2px #25262a22` |
| EQ 旋钮 | `inset 0 1px #fff, 0 2px 4px #25262a1a` |
| Brief 表单 | `0 2px 5px #25262a0b` |
| 导航展开层 | `0 8px 20px #25262a12` |

**The Material at Controls Rule.** 凹凸服务于可操作控制与组边缘；音乐、说明和列表不为器材感叠加装饰层。

## Shapes

控件通常为 control 圆角，输入存在 field/group 两档；Studio 面板与 transport 为 panel 圆角，作品卡/设置容器为 card，Brief 为 form。通道条内部保留直边，外层 bank 用 group 圆角统一收边。状态 chip 使用胶囊，EQ 旋钮为实际圆形控制；不把圆形泛化成无功能的仪表装饰。

## Components

### Buttons and navigation

主操作是烧橙填充白字，次要按钮是浅面与明确边界，文字动作沿用烧橙。全局按钮默认最小高度 44px；桌面 Studio 工具键、工作面切换仍有 36px 的紧凑规则，移动端提升为 44px。主/次按钮类保留既有 800 字重，普通按钮为 600。悬停改变底色，按下以 100ms 过渡下移 1px 并加浅内阴影；禁用恢复静态实体外观。

全局导航链接以中性文字呈现，当前页为 subtle 背景；“更多”使用原生 disclosure。导航仍是链接，动作仍是按钮。跳至正文入口与可聚焦 main 保留。项目状态 chip 同时呈现文字与标记，26px 高度表示信息标签，不作为触控按钮尺寸。

### Inputs and focus

Brief 字段使用面板底、清晰边界与真实标签；EQ 保留数字输入。焦点覆盖按钮、链接、summary、输入与可聚焦代理：石墨 2px 外环、3px offset，加 surface 隔离圈。侧车记录完整 focus CSS；前置组件 token 不扩展为不受支持的 focus/shadow 属性。

### Transport and saved audio

播放、停止和原生位置 range 组成紧凑控制组，播放来源和可用状态邻接。按钮至少有 44px 宽度，时间采用等宽数字。当前播放器播放保存版；推子与 EQ 是草稿参数，保存后才渲染。不能从界面旋钮或静音 mock 媒体推断实时调音效果。

### Mixer and EQ

通道按轨号/来源、轨名、EQ、Pan、M/S、音量、输出状态、还原顺序排列。选轨及 M/S 有 `aria-pressed`，输出、静音或 Solo 排除另有文字。声像 range 桌面最小高度为 28px，768px 及以下与 EQ 下拉/数字框提升为 44px；竖推子为原生 range、44×148px，读数带 dB 与可访问值描述。不得把这些实际尺寸概括为全站全部 44×44px。

桌面 EQ 的 76px 旋钮支持键盘与指针，数字输入始终存在；低中高范围为 ±12dB。方向键步进 0.5dB，Shift 方向键 0.1dB，PageUp/Down 3dB，Home/End 到边界，Escape 取消；数字输入提供提交、恢复、无效状态及错误 alert。曲线说明明确为参数响应，不是音频频谱。主输出为保存版的只读状态与导出入口，没有 Master 推子、实时 meter、FX 或插件槽。

### Motion and access evidence

`prefers-reduced-motion: reduce` 关闭动画、过渡和顺滑滚动，按钮同时取消按压位移，保留静态状态差异。已有 mock 键盘记录仅覆盖 Studio 前 22 次 Tab 的焦点外观，未激活编辑；组件键盘处理由静态源码支持。读屏器、原生 200% 缩放、完整触控与全流程键盘验收未由本次记录证明，不能称为 WCAG 全项通过。

## Do's and Don'ts

### Do:

- **Do** 从前置 token 与后加载的 workbench 样式读取当前视觉值，保持 DOM 与 Canvas 的展示色一致。
- **Do** 用轨号、名称、文字状态与按压语义同时表达选择；为旋钮保留数字输入与键盘路径。
- **Do** 把草稿参数、保存版播放、恢复和导出来源放在对应控制附近。
- **Do** 在窄屏纵排工作区，允许通道 bank 和 EQ 曲线局部横滚，并保留保存、任务和主输出入口。

### Don't:

- **Don't** 从旧提案或兼容变量名重新引入绿色、青紫主色或旧控件边界。
- **Don't** 添加假 meter、假频谱、随机波形、虚假进度、无功能旋钮、FX 或未实现的音频能力。
- **Don't** 用纹理图、外部字体、新 UI 依赖或持续装饰动画替代现有边缘和明暗材质。
- **Don't** 把 mock 截图、静音播放、既有测试数字或待完成审查写成 Beta 部署、真实生成、听感或完整可达性结论。
- **Don't** 把局部 11px 说明、桌面紧凑控件或遗留样式注释升级为未来界面的通用规范；这些现状没有在文档任务中修复。

## 限定精修（2026-10-28）

精修基于本地 378b17c，仅改 workbench.css：移动端编辑按钮排成一行，未保存计数与初始版本说明留在下一行，错误仍单独占整行；低于375px回到双列按钮。桌面 EQ 旋钮与数值/标题邻接，曲线仍640×208并可局部横滚。没有改控件文案、命令、API或音频。1440/1024/390/320样本无整页横溢；长标题、脏稿、保存失败与参数错误仍可见。触摸命中结论仅针对本次工作栏、Pan与EQ目标，品牌链接/进度条等既存较小目标不在全站可达性通过声明中。
