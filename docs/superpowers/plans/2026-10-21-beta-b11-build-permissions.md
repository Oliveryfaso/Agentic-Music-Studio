# B1.1：外置盘源码构建的渲染镜像非 root 读取权限

阶段：个人 Beta B1 实际镜像/运行门；MF-P16/P17/P18/P21。基线6e5e7c5、worktree clean；Guide last d68b900，核对 diff、不计算内容 hash。继续原开发 session 和三线职责。

真实失败：专用 render-worker 构建成功，但默认 UID10001 读取 page-entry.js 得到 EACCES。只读 stat 证明宿主 dist/package.json 是0700，镜像中对应文件 root 所有且0700；上层目录755。公开代码内容、音源 pin 没有变化。API/media已独立校验157文件一致，不重建。

1. 保留首次真实失败和失败镜像 ID；添加显式选择测试镜像才运行的实际 Docker 边界测试，默认跳过。要求声明的非 root UID读取 package.json/三个构建bundle，容器无网络/不挂宿主数据/退出自动删除。先在原镜像得到RED。
2. 只在 render-worker Dockerfile 编译之后、切换现有非 root USER 之前，将已有 dist 目录设0755、package.json和三个公开JS bundle设0644。保持镜像用户/公开文件内容/业务代码/依赖锁不变；不改仓库、音源、数据权限，不改构建上下文脚本或共享镜像。
3. 检查已有单目标标签回归与新测试 Ruff；一次fresh独审，必要时仅一次限定修复复核。正式受审核应用计划、Dockerfile和边界测试。
4. 只重建专用 render-worker。已有依赖层应复用；若不同则如实记录，不能通过 root 运行掩盖失败。保留旧失败回执；新默认非 root 测试GREEN且三个bundle匹配当前源码宿主独立编译，旧5共享镜像ID保持。
5. 继续正常 Beta 启动、容器层只读挂载/固定pin/实时capability/四谱目录、正式 API 导入与手工队列候选；原前端做浏览器验收。B2自然语言、多轮修订/重开/导出和听感不由此测试代替。

不涉及 creative slice、Schema/DB/Graph/IR/DSP/新依赖、模型或密钥；费用累计不变。仅回收已确认任务所有的临时探针，不清来源不明的共享BuildKit。临时“规范化整个构建context”的宿主实验不是最终方案，保留在任务workspace但不集成、不当作本方案通过证据。
