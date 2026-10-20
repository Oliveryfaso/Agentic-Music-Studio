# 财务闸门限定修复复核

日期：2026-10-20。结论：**原 Important 已关闭；本次限定范围内没有确认新增 Critical / Important / Minor 财务回归。可以解除该审查对本轮首次真实调用的阻塞。**

本结论限定于任务 helper 的日志恢复修复；沿用已明确的执行约束：正式账本显式初始化一次，实际 runner 只调用恢复构造器，绝不因丢失状态自动 create；首调用仍须先成功 reserve，再由主线 harness 执行一次外发。没有扩大本轮预算、次数或重试授权，也没有执行真实调用。

## 修复证据

- `spending_gate.py:46–55`：构造器要求 journal 和独立 `.head` 都存在，不再隐式初始化。`_locked()` 在 `:80–83` 打开 journal 时也不再使用 `O_CREAT`。
- `:57–76`：新账本通过独立显式 `create()` 初始化；任一文件已存在即拒绝，两个文件都使用 `O_EXCL` 创建。部分初始化失败会留下不可恢复放行的状态，正常构造器不把它当作新授权。
- `:102–106`：持 journal 排他锁检查 `.head` 的序号和摘要必须精确等于完整 journal 末尾。以前能通过的完整 policy 前缀截断，现在与原高水位不匹配并拒绝。
- `:111–132`：事件 append/flush/fsync 完成后，写临时 checkpoint 并 fsync，再原子替换 `.head` 并 fsync 所在目录。reserve 只有整个持久化步骤成功后才返回；journal 已追加而 head 未推进时，后续恢复保守拒绝。
- `test_spending_gate.py:118–134`：新增四种状态丢失回归，覆盖 journal 缺失、清空、有效前缀回退、head 缺失；每种都检查正常恢复和显式 create 均拒绝。
- `:137–149`：新增两个 guard 实例竞争预留的回归，确认只允许一次 reservation。

## 独立验证

独立运行：

```text
/Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/Users/oliver/Documents/Codex/2026-10-18/task-2/research/p23-real-model-validation/independent-guard-recheck-tmp /Users/oliver/Documents/Codex/2026-10-18/task-2/research/p23-real-model-validation/test_spending_gate.py
20 passed in 0.05s
```

另在临时账本中注入 `os.replace` 失败，模拟 reserve 事件已 append+fsync、checkpoint 尚未替换的窗口。reserve 没有正常返回；journal 确有两条完整记录。撤销故障注入后，结果：

```text
same-instance-next-reserve BLOCKED MISSING_OR_ROLLED_BACK_CHECKPOINT
restart BLOCKED MISSING_OR_ROLLED_BACK_CHECKPOINT
explicit-create BLOCKED INITIALIZATION_ALREADY_EXISTS
```

原预算、次数、usage、模型检查和 reserve → receipt → complete 状态门没有因本次修复放宽；保留原 15 项回归并全部通过。未知 usage 仍保留全额预留并暂停，pending 仍阻塞，旧 4 次/7228 tokens/上界 23852 micro-CNY 仍保留。

复核文件 SHA-256：

- `spending_gate.py`: `09c550f59dcfc772321b0b8f669338995b8c611bb4537149fc16bfa1c71fc8a5`
- `test_spending_gate.py`: `eae95d067fa6dc92f5a124051464394e2411c30aa15460935257de8411ce4734`

## 边界 / declined to judge

本次只完成一次限定复核，未审查实际 harness 的网络行为、SDK 重试设置或本地 schema/compiler 验证集成，未联网核实价格和别名。主线仍负责这些既有执行约束。未读取密钥或 `.env`，未调用网络、模型、DB、容器，未修改受审代码，未初始化正式账本。

不主张抵抗恶意同时删除所有独立证据后显式重建，或卷级快照同时回退 journal 与 head；不扩展成产品全局 CNY 闸门。正常运行路径下，单个账本丢失/清空/有效前缀回退和 checkpoint 丢失已按要求 fail-closed。
