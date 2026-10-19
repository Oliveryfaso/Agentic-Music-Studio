# Motif Forge P2.2：自然语言钢琴伴奏与局部修改

2026-10-19；起点/Guide `5dbbc6aabf08b9a6e2d4fbfece810afc23fe5564`，开始工作区与Guide clean。用户明确授权实施、使用既有DSAPI Flash、本轮累计≤10元（含失败/重试），验收后正常推开发分支；不合main、不部署。开发分支 `codex/motif-p0-piano-preparation`。这是新P2.2，不能以旧P2.1验收代替。

## 已实现的用户路径

描述“低音区，前8小节稀疏、后8小节稍活跃，不改旋律”→Flash有界逐bar计划→确定性音符编译/约束校验→新增候选轨→真实前后试听→明确勾选、hash绑定保留。保存后选新增第二轨连续1–4小节，用描述改变密度/音区/gate/力度；原和声、原谱和选区外音符精确保留，再次试听/保留/重开/Undo/导出。原有手动规则入口保持可用，不是模型失败时的隐形回退。

仅固定Mutopia528的16小节旋律、G大调4/4及同审核小钢琴包两轨。新资源包三曲尚未并入，通用MusicXML、第三轨、自由配器/和声改写、完整P2/P3与音乐质量未宣布完成。单有效力度层、无踏板/释放触发、现有合成包边界保留。

## 真实模型与费用

实际配置白名单核对：已配置，official endpoint `https://api.deepseek.com`，保留原请求名 `deepseek-v4-flash`；四次响应均报告 `deepseek-flash`。官方2026-10-19价格页说明旧名称仍可调用、由V4.1-Flash-1017服务；这是官方映射说明，响应本身没有报告精确权重版本。没有切换Codex手动模型，也没有读取/打印密钥。凭据仅由项目Settings/Provider内部使用。

| 提交 | Prompt | 输入/输出/总tokens | 验收结果 | 高峰且输入全部按未命中计算的费用上界 |
|---|---|---|---|---|
| 1 | v1 | 1304 / 585 / 1889 | 加轨工程通过 | ¥0.007288 |
| 2 | v1 | 1454 / 196 / 1650 | 独立审查发现未请求的和弦变化，语义验收失败，保留反例 | ¥0.004476 |
| 3 | v2 | 1346 / 587 / 1933 | 修复后加轨通过 | ¥0.007388 |
| 4 | v2 | 1558 / 198 / 1756 | 和声锁定的局部修改通过 | ¥0.004700 |

**累计4次、7228tokens，费用上界¥0.023852，含前轮未通过语义验收的调用。** HTTP/Schema失败0、自动重试0，没有额外Critic或修复请求。此金额是按公开费率计算的保守上界，未查询账户账单，不冒充实际扣款；缓存命中/空闲时段可能更低。官方来源：[模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，查询2026-10-19。按高峰输入2/输出8元每百万tokens计算，全部忽略缓存优惠。

每Run1提交/12000总tokens/3072输出、输入UTF8字节≤8000、non-thinking JSON、max_attempts1、schema repair0。阶段harness调用前逐次落预算账本，最多8提交的最坏预留0.768元；任何未知usage停止后续真实调用。API Run中的美元cost继续unknown，不凭空换汇；本轮prompt/completion/total已报告，缺少完整reasoning细节所以usage_status为partial，未知不写0。

## 实际验收与审查

最终built UI+自有真实PG+Chromium：2个AI Run、2份持久计划，每Run仅1请求；6Jobs（两轮前后试听、Master、Bundle），8导出文件bytes/SHA核对；模型规划刷新恢复、错误hash409、真实播放/同位置切换、保留、重开、390px、原谱/范围外exact、Undo恢复精确父hash并播放。每次Worker完成后重建应用，通过生产Outbox publisher双投递恢复；不是Redis/Celery传输、完整Compose或掉电持久性验收。

最终音乐字段：前后8小节伴奏音数16/32、音高36–52；9–12bar从16音减为4音、平均velocity57→38，和弦G/Am/D/G逐项不变。说明本例遵从密度/力度/低音区/选区；不是普遍音乐智能或听感偏好达标。Master40.79998秒、48k stereo PCM24、11,750,438 bytes；sample peak约−13.30dBFS、满幅样本0，非true-peak/LUFS/审美测评。

最终Python unit/Eval+root **747**、Web **102**、Audio **61**、真实PG/Inspector联合 **6**、Mypy **131源**、两宿主build、Ruff/diff通过。数据/音源/依赖/锁文件没有扩增。一次fresh审查发现2Important：I1局部换和声、I2待回执伪known0；一次作者修复，限定复核关闭两项，无剩余阻塞。独立初审51离线测试；修复复核另9通过，PG证据独立阅读而非冒称重跑。

I1用当前/祖先Revision的source_run_id找可信Plan，要求当前所选NoteEvents/trackID与该历史版本完全相等；人工规则只认已记录Append及严格roots/brokenrecipe。最多64祖先；不可验证在付费前拒绝。fixed_harmony进入Prompt，保存前/重放后硬比对，绝不静默clamp或额外付费repair。I2在同一SQL snapshot判断RESERVED，权威读者与Inspector统一unknown/None；observed合法0保持known0，不污染底层真实累计。

## 仍需如实保留的边界

- 规划请求已提交后不提供即时取消；最多单次45秒读取时限，返回到Worker边界后可取消试听，审批时可放弃。网络失败同key重试；pending POST identity可跨页面恢复。费用预算不是任意未来任务的无限授权。
- Minor延后：旧通用Adapter在响应缺少model字段时默认请求别名。此轮四次都有真实reported model，不受此缺口影响；下次升级Provider诊断或公开发布前补缺失标识测试/unknown，不再用默认值冒称服务端身份。
- 旧宏观付费Planner仍只收synth_ambient；四风格Fallback/策略和新默认古典/爵士入口不能推成四风格付费LLM全通。旧通用AI Edit仍有Fallback边界；本次完成的是专用钢琴语义路径。
- 原谱仍锁定，当前Mixer/保存MP3与未来实时混音存在独立合同缺口，见另交的基础混音只读报告。没有借此解除原谱锁或扩成完整DAW。
- 当前没有CI配置的历史事实不变；这里报告的是已运行本地/隔离验证，不称CI通过。未迁移用户库、未部署或合main。

最终媒体/模型计划/费用/原始失败和审查证据保留。自有临时PG、生成凭据、Mock渲染产物与启动器按精确身份关闭；共享Colima、历史服务/镜像/混合缓存不动。清理具体数量由storage证据记录。

存储关闭实测：自有PG/tmpfs与生成凭据移除，最终17文件重核SHA；回收过期Mock/启动器逻辑文件15,204,270 bytes，保留live Artifact及全部试听/导出证据；共享容器身份集合不变，未prune共享Builder，未迁移用户库。见 `2026-10-19-p22-storage.json`。
