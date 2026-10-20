# 身份门禁独立限定审查

日期：2026-10-20。结论：**本次限定范围内未确认 Critical / Important / Minor 缺陷；当前待批准状态有效，仍不得外发真实模型请求。** 这是身份修复的离线审查，不是新调用授权，也不追认此前七次调用获得了替代模型的身份批准。

## 范围与证据

只读审查 `identity_gate.py`、`model-identity-evidence.json`、`test_identity_gate.py` 及 `probe-live.py` 中身份检查的绑定。未修改生产代码或 gate；未联网、读取凭据、启动 runner、服务、数据库或容器。测试仅运行离线测试文件；没有导入或执行 `probe-live.py`。

受审文件 SHA-256：

- `identity_gate.py`: `eb73e76759047cadf82f6b0e46641b617c4043b65e0c04c81f501e2223809cc7`
- `model-identity-evidence.json`: `5989bd8ddf71d73a73a3f95ea23bcf30acdfd97856050ec09651152b3f2cfa4e`
- `test_identity_gate.py`: `7b4b65bd31207b9b5de09175cfeb6b8c9c89e09d126d50317326eca9a64a7510`
- `probe-live.py`: `f3541aea63a1aaa475621f64d4d9e9fafdecd0b3feb6712eb1c0dacce242e0fe`

## 已核验的身份边界

1. **官方映射不等于人工批准。** `model-identity-evidence.json:5–12` 把请求名、响应名、替代服务版本分别记录，明确 `human_identity_approval: null`，状态为等待人工明确确认。`identity_gate.py:30–35` 要求批准对象包含匹配的三个身份字段和非空批准引用；当前 null 无法通过。独立对当前真实证据文件执行前置检查，结果为 `MODEL_IDENTITY_REPLACEMENT_NOT_APPROVED`。
2. **每次前置检查都重新读取证据。** `identity_gate.py:11–29` 拒绝缺失、无法解析、非对象或符号链接证据；检查官方来源地址、endpoint、当天核验日期及请求名，并要求三个映射字段为非空字符串。没有缓存父端曾作出的放行决定。旧批准与变更后的映射字段不匹配时拒绝。
3. **付费路径实际绑定前置门禁。** `probe-live.py:80–100` 中，目标官方 endpoint 进入 `require_before_send`（第 89 行），成功后才可能 `gate.reserve`（第 97 行）并执行真正 `original_post`（第 100 行）。身份错误会先暂停钱账并抛出异常；不会落入外发。第 83 行的另一路 `original_post` 属于仅允许本机 URL 的分支，不能以该分支访问目标付费 endpoint。
4. **每次响应重新读取并核对证据。** `identity_gate.py:39–48` 重新读取文件并比较请求前固定的全文件 SHA-256，故调用间映射/批准变化会拒绝。缺失、非对象或不匹配的响应 model 会拒绝；显式返回但不匹配的 `model_version` 也会拒绝。
5. **响应身份失败不会进入成功记账流程。** `probe-live.py:101–110` 在 JSON 解析后调用 `require_after_response`，通过后才 `gate.observe`。身份失败会暂停并抛出，外层也暂停；不会返回该响应给本地正常验收流程。此检查独立于父端异步暂停通知。
6. **单元测试批准是虚构夹具。** `test_identity_gate.py:12–18` 的 `human:fictional-unit-test-only` 仅写入临时测试证据。当前真实证据仍为 null。代码中的批准引用属于人工维护的授权记录，不是对人类同意本身的自动认证；没有把该夹具视为本次真实批准。

## 独立离线验证

运行：

```text
/Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/Users/oliver/Documents/Codex/2026-10-18/task-2/research/p23-real-model-validation/independent-identity-review-tmp /Users/oliver/Documents/Codex/2026-10-18/task-2/research/p23-real-model-validation/test_identity_gate.py /Users/oliver/Documents/Codex/2026-10-18/task-2/research/p23-real-model-validation/test_spending_gate.py
33 passed in 0.07s
```

其中身份 13 项、钱账 20 项。身份测试覆盖无人工批准、精确匹配的虚构批准、不完整或不匹配批准、缺失/变更响应名、请求至响应间证据变化、下一次请求重新验证批准、过期/缺失证据及错误 endpoint。钱账测试只作为相关回归运行，不重开此前已关闭的问题。

直接检查当前证据，额外得到：

```text
CURRENT_EVIDENCE_BLOCKED: MODEL_IDENTITY_REPLACEMENT_NOT_APPROVED
```

## Declined to judge 与当前状态

- 本次未联网核验官方文档或服务商的实际路由，未验证真实权重。该 helper 固定本地记录并检查响应标签；相同通用响应名不构成权重身份的证明。缺失 `model_version` 仍允许匹配 `model` 的响应，这是当前标签/官方映射边界，而非精确权重认证。
- 未把证据文件中的 source URL、当天日期或任意非空批准引用视为外部真实性的独立证明；正式批准仍须来自用户对具体替代模型的明确确认。
- 未独立重验此前七次的用量、金额、服务关闭或 PG 清理；这些是委派方提供的已完成背景，非本次审查结论。
- 当前 `human_identity_approval=null`，因此保持 **hold**。将来取得明确身份批准也不自动解除已永久 pause 的本轮钱账，更不自动获得新批次调用授权。

当前身份边界修复可接受；没有需要追加真实调用才能完成的验证，也没有理由为本次审查重新启动服务。
