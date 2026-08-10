# Controlled Agent Loop and Durable Checkpoints

CodeMate 的修复主链路把“模型决策”和“系统授权”明确分开。模型只能返回一个经过 Pydantic discriminated union 校验的下一步动作；本地执行器再次检查动作白名单、参数边界、测试命令白名单、调用次数、Token、总时间和无进展次数。模型输出不会直接变成任意 shell 或文件系统操作。

## Main flow

```text
Inspect Repository
  -> Reproduce Failure
  -> Initialize Agent Loop
  -> Plan Next Action <-> Execute Local Action
  -> Generate Patch
  -> Apply Patch
  -> Targeted Tests
  -> Regression Checks
  -> Reflect / Final
```

`PlanNextAction` 每轮只能选择一个动作：

- `SearchCode(query, top_k)`
- `ReadFile(path, start_line, end_line)`
- `ListFiles(pattern)`
- `FindSymbol(symbol)`
- `FindReferences(symbol)`
- `GetImportGraph(path, direction, depth)`
- `GetCallGraph(symbol, direction, depth)`
- `RunTests(command)`
- `GeneratePatch()`
- `Finish(reason)`

动作类型位于 `backend/app/agent/actions.py`，所有模型都配置为 `extra="forbid"`。真实 LLM provider 在反序列化后使用同一个 Pydantic union 校验；执行器在 dispatch 前再次校验，因此未知动作、额外字段、越界行号和未授权测试命令都会 fail closed。

## Budgets and loop prevention

默认边界由环境变量覆盖：

| Setting | Default | Purpose |
| --- | ---: | --- |
| `AGENT_MAX_LOCAL_TOOL_CALLS` | 12 | 单次 Run 的本地工具调用上限 |
| `AGENT_MAX_PLANNER_CALLS` | 16 | Planner 轮数上限 |
| `AGENT_MAX_PLANNER_TOKENS` | 24000 | Planner 累计 Token 上限 |
| `AGENT_MAX_LOOP_SECONDS` | 600 | Agent Loop 总时间上限 |
| `AGENT_MAX_NO_PROGRESS_STEPS` | 3 | 连续无新证据的停机阈值 |
| `AGENT_MAX_READ_LINES` | 800 | 单次 ReadFile 的最大行数 |

执行器记录 action fingerprint 和 evidence fingerprint。完全相同的搜索/读取/测试动作不会再次执行；相同 patch fingerprint 不会再次应用。连续空结果、重复 evidence 或 guardrail 拒绝会增加 `no_progress_count`，达到阈值后转换为受控 `Finish`。每轮 hypothesis、evidence、action history、预算消耗和 patch fingerprint 都保存在 LangGraph state，并通过 `agent_plan`、`agent_observation`、`agent_guardrail` 事件进入 Timeline。

## Durable checkpoint and recovery

Graph 使用 `SQLAlchemyCheckpointSaver`，每个 Agent Run 的 `run_id` 同时作为 LangGraph `thread_id`。Saver 持久化 checkpoint、channel blob 和 pending write，数据库结构由 Alembic 管理，而不是在 Worker 运行时临时建表。

LangGraph 在每个 super-step 后保存状态。普通 Agent RQ job 配置了三次退避重试；Worker 再次执行同一个 Run 时，如果 checkpoint 存在未完成节点，Agent 使用 `graph.invoke(None, config)` 从该节点继续；若 checkpoint 位于 Apply Patch 之后，系统会在新建的隔离 workspace 中按已保存 patch 重建状态，再继续测试。恢复动作会记录 `checkpoint_resume` Timeline 事件。

MCP 的审批 checkpoint 与普通节点 checkpoint 各自承担不同职责：前者绑定审批参数、策略和完整性哈希，后者用于 LangGraph 节点级故障恢复。远程工具仍经过 MCP Router 的 Schema、预算、策略、审批、幂等与重复调用保护。

## Verification boundary

Agent Loop 只决定如何收集证据以及何时请求生成 patch。Patch 是否可应用、测试是否真实运行、以及最终状态都由确定性验证节点判定。只有修复前确实复现失败，且修复后的 targeted 和 regression 两阶段都满足 `tests_ran=true && exit_code=0`，才会得到 `verified_success`。
