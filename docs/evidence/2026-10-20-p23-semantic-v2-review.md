# P2.3 semantic v2 / 0030 / 三曲自然语言入口：fresh 独立审查

日期：2026-10-20。审查对象为 `${REPO_ROOT}` 的真实 working tree，包括清单所列 untracked 新文件；未以 staging 副本代替实现。BASE 与审查结束时 HEAD 均为 `88c0a074c00765c008a271129f8ebf64ab8ec25c`。

本次为一次 fresh 独立审查；未派子审查、未修改仓库/index/HEAD，未启动 API/PG/Worker/模型或安装依赖，未读取凭据/.env，未操作共享 Colima。临时 probe 与测试缓存仅放本任务 workspace。

遵循根 AGENTS、motif-forge-development 清单、当前状态与本轮计划/原设计。PROJECT_GUIDE 最后修改提交 `d68b900bd8dce6c5786dd0b6c6b531429c9d38a2`，审查前后 working-tree diff 均为空。当前 stage 为 P2.3 的 semantic v2/0030；覆盖计划所列 MF-P02/P04/P05/P06/P08/P09/P11/P13/P15/P16/P17/P18/P20/P21。已提交的三曲目录/规则路径仅作为调用边界阅读。

## 结论

- Critical：无已确认发现。
- Important：无已确认发现。
- Minor：无已确认且需要本轮修复的发现。
- **当前代码路径无已确认阻塞；不要求作者修复或修复复核。** 此结论不是整个 P2.3 已验收，也不替代主线尚在进行的真实 UI/API/Worker 与收尾证据。

## 主要核查结果

- `domain/piano_requests.py:42`、`domain/piano_plan.py:64`：新请求与新计划分别显式版本化，registry 约束 source/meter/谱内小节；旧 v1 不能冒充新来源。新 3/4 的步长/gate 上限为 12，4/4 为 16；C/G 词汇由 compiler 再按来源限制。
- `application/piano_semantic.py:59`：run/project/branch/base/request 先匹配；来源、目标、选区、可证明和声均先于 planner factory。新记录在保存前及重放后重验 request/source/plan；存在持久记录时不构造新的付费客户端。
- `domain/piano_plan.py:180`、`domain/commands.py:778`：选区使用实际 bar ticks；拒绝跨选区音符与所选 performance 覆盖冲突；原轨及选区外 NoteEvents 保持。v4/v5 继续走既有范围命令，不隐式改写混音/EQ。
- `application/piano_harmony.py:40`：历史语义计划与现有音符匹配；规则配方按真实 bar ticks 识别；新词汇下单个 D 根音的 D/Dm 歧义明确拒绝，旧六和弦行为保留。没有把猜测和声当作已验证和声。
- `providers/piano.py:25`、`:194`：新 prompt v3；3072 output、8000 UTF-8 input、1 request、12000 total tokens、schema repair 0、transport attempts 1。既有持久预算 reservation 在网络请求前落账，未知用量不能作为零或新预算。
- `domain/piano_record.py:22`、`infrastructure/persistence/piano_plans.py:60`、`infra/migrations/versions/20261020_0030_piano_semantic_v2.py:13`：v2 source/request/plan 绑定；不可变 insert 冲突比较；迁移/table check 一致且外层 `IS TRUE` 拒绝 SQL unknown。危险降级检查 record、AI Run request、新来源 Revision 与 Candidate。
- `apps/web/src/features/studio/PianoPanel.tsx:39`、`:73`：三曲按权威 source report 构建 v2；8bar 初始 5–8、16bar 初始 9–12；新来源首次创建及丢回执重挂测试均保持同 body/key。审批仍需显式试听确认、candidate hash 与原有真实 Artifact 检查，未见新自动提交入口。
- Source stale：workflow 在模型前锁定/校验 base branch，候选创建与保留仍通过现有事务边界；UI 只允许当前 base 对应候选确认。

以上后端相对路径均位于 `services/api/src/motif_forge/`，除另行列出的 migration/UI。

## 独立执行证据

1. 真实仓库聚焦 Python：**31 passed in 1.06s**。包含 v2 request、v2 plan/compiler、semantic service/Provider fixture/replay、和声、v2 Eval。使用现有 `.venv`，`PYTHONDONTWRITEBYTECODE=1`，pytest cache 在本 workspace。
2. 真实仓库 `PianoPanel.test.tsx`：**16 passed**，Vitest 4.1.10，单 worker，3.39s。自定义 config 仅改变缓存位置与测试选择，仍导入真实仓库组件/测试/依赖；未复制实现。
3. `reviewer_probe.py`：把 `git show HEAD:.../piano_plan.py` 的旧 compiler 与真实当前 compiler 同进程对比。旧 G/C/D/Em/Am/Bm 六种计划的 **plan JSON bytes、Track JSON bytes、最终候选 ArrangementIR hash 6/6 完全一致**。此为确定性声音输入/hash 兼容证据，不是新录音听感证据。
4. 同 probe 的额外 **10/10** 反例被拒绝：source/request/plan JSON null、错误 source ID/hash、request meter/version、plan meter/version、缺少小节 coverage。
5. `git diff --check` 通过；结束 HEAD 不变、PROJECT_GUIDE diff 为空。

测试配置：`reviewer-vitest.config.mjs`。独立 probe：`reviewer_probe.py`。二者与本报告同目录。

## Declined to judge / 未扩张的判断

1. **真实 PostgreSQL 本轮执行**：只读审查了 0030/table/store 和作者 PG/guard 测试，没有启动或接入数据库；作者所报 PG4 与 guard 通过不是本审查独立执行的结果。未声称独立验证所有 populated downgrade 或直接 SQL 损坏组合。
2. **实际 Mac UI/API/新语义 Worker**：主线仍在执行，本审查没有把 mock transport、jsdom 或持久化测试当作实际三曲音频闭环。应由主线验收日志单独闭合。
3. **真实付费模型音乐质量、人耳审美、canonical PCM 实测**：没有新增模型请求、音频渲染或听感判断。源码/确定性输入保持不等于新曲音乐质量已验收。
4. **完整 Python 全绿**：不作此判断。委派信息明确为 878 通过、1 个既有启动器测试失败（stub 未记录 `docker compose down`，主线核查中）；本报告仅认领自己的 31 项聚焦测试。
5. **全崩溃/取消/并发矩阵、生产负载/多租户/部署**：本切片没有新增证据，不以本审查结论覆盖这些后置门。
6. `PianoPanel.tsx:48` 的 mode-change effect 仍使用 9–12。单独复用同一组件实例并把 8bar arrangement 从一轨改为两轨可触发不合适默认值；但实际 `App.tsx:45` 按 project+revision key 重挂 Studio，且 `ClassicalAccompanimentPanel` 读取来源完成后才挂 PianoPanel，当前保存/打开/Undo 导航没有证明能走到该分支，因此不把这一孤立实现观察升级为当前路径缺陷。若以后改为原地切换保存版本，应同步使用 `defaultStart/defaultEnd`。
7. 历史缺失 reported-model 的回退身份属于已登记后置项，本轮没有新证据证明它升级为当前阻塞。

未发现需要本轮唯一作者修复的项。主线仍需完成其已授权验收、真实结果与状态/演进记录、存储收尾及正常开发分支 checkpoint；本审查没有提交或推送任何内容。
