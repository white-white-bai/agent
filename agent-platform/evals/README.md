# Agent 轨迹评测数据

- `agent_cases.example.jsonl`：评测用例，一行一个 JSON。
- `agent_traces.example.jsonl`：录制轨迹，一行一个 JSON；`id` 与用例对应。

用例字段：

- `id`：用例标识，必须与轨迹 `id` 一致。
- `query`：原始任务，供 LLM judge 使用。
- `expected_tools`：标准工具调用顺序；默认要求完全一致。
- `forbidden_tools`：一旦出现即失败。
- `answer_contains`：回答必须包含的关键字。
- `min_path_score`：路径得分下限（0–1，默认 1.0）。
- `max_tool_calls`：工具调用次数上限。
- `require_status`：期望状态（如 `completed` / `interrupted`）。
- `judge` / `judge_min_score`：是否启用 LLM judge 及其通过线。

轨迹字段：

- `id`、`tool_calls`、`plan`、`reflections`、`answer`、`status`、`token_chars`、`error`。
- 也可用 `events` 直接放 `stream_agent` 的 SSE 事件列表，评测器会自动抽取轨迹。

运行：

```bash
python scripts/eval_agent_traces.py --cases evals/agent_cases.example.jsonl --traces evals/agent_traces.example.jsonl
```
