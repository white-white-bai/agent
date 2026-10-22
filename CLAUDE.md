# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库布局

本仓库只跟踪两个工程目录（外加 `.trellis/` 与根 `.github/`）：

- `agent-platform/` —— Python（FastAPI + LangChain/LangGraph）agent 中台服务。
- `agent-platform-ui/` —— 中台独立管理前端（Vue 3 + Element Plus + AntV X6）。
- `.github/workflows/ci.yml` —— backend（ruff / pytest / 评测门禁）与 frontend（test / lint）CI。
- `.trellis/tasks/10-14-agent-platform/prd.md` —— 需求与逐条决策（唯一权威来源）；`research/dify-cloud-contract.md` —— 兼容契约。

PRD 中提到的 `backend/`、`frontend/` 属于外部仓库 `gov-service-ai-assistant`，**不在本仓库内**。所有设计都以「不改动 Java 后端与前端源码、只改 base-url」为前提，所以对外协议（SSE 事件序列、Envelope 形状）是硬约束，改动前先读 `research/dify-cloud-contract.md`。根 `.gitignore` 是从别的模板继承来的，其中 `platform/`、`agent/`、`domains/` 等路径在本仓库并不存在。

## 常用命令

### 后端（`agent-platform/`）

```bash
cd agent-platform
python -m venv .venv && . .venv/Scripts/activate     # Windows
pip install -e ".[dev]"
cp .env.example .env
pytest                                               # 全部（pythonpath=src 已在 pyproject 配好）
python -m pytest tests/test_history_summary.py                            # 单文件
python -m pytest tests/test_api.py::test_chat_stream_events                # 单测
python -m ruff check .                                                     # lint（line-length 120, py310）
uvicorn agent_platform.api.main:app --reload --port 8900                   # 起服务
python -m agent_platform.worker.main                                      # 起 worker
python scripts/smoke_e2e.py                                               # 内网冒烟（连真 MySQL/云智/模型）
python scripts/export_agent_queries.py --tenant-code <tenant> --limit 100 --out evals/queries.jsonl
python scripts/record_agent_trace.py --app-uuid <uuid> --cases evals/queries.jsonl --out evals/recorded_traces.jsonl
python scripts/export_agent_traces.py --tenant-code <tenant> --days 7 --out evals/prod_traces.jsonl
python scripts/eval_agent_traces.py --cases evals/agent_cases.example.jsonl --traces evals/agent_traces.example.jsonl
python -m agent_platform.importer app.yml -o graph.json                   # Dify DSL → 中台图定义
pip install -e ".[browser]" && playwright install chromium                 # 可选：真实浏览器工具
```

pytest 用 `asyncio_mode = "auto"`，异步测试直接写 `async def test_...`，不需要 `@pytest.mark.asyncio`。
ruff 忽略 `B008`（FastAPI `Depends()` 默认值），`engine/code_sandbox.py` 逐文件忽略 `S102`（该文件本就执行 `exec`）。

### 前端（`agent-platform-ui/`）

```bash
cd agent-platform-ui
npm install --registry=https://registry.npmmirror.com
npm run dev            # Vite 源码调试；5199，代理 /admin /v1 /api /healthz → AP_UI_PROXY_TARGET（默认 127.0.0.1:8900）
npm run lint           # eslint .（flat config）
npm test               # vitest run
npx vitest run tests/mapper.spec.js        # 单文件
npm run build
```

全栈一键（在 `agent-platform/` 下，需 Docker）：`docker compose up -d --build`（api + worker + ui + mysql + langfuse）；
只改了前端源码时 `docker compose up -d --build ui` 重建管理端；`docker compose stop ui` 腾出 5199 给 `npm run dev`。

**`:5199` 谁在服务要看清**：compose 栈起来时，5199 是 `agent-platform-ui:dev` 容器里 nginx 托管的**打包产物**（页面加载 `/assets/index-*.js`），与 `npm run dev`（页面加载 `/src/main.js`）**互斥同端口**。此时改 `src/` 只是改源码，**必须 `docker compose up -d --build ui` 重建镜像才生效**，光刷新浏览器没用——排查「改了没效果」先看页面加载的是 `assets/index-*.js` 还是 `src/main.js`。

## 架构

### 请求链路（后端）

`api/main.py` 是唯一对话入口：`@app.post("/v1/chat-messages")` 与 `@app.post("/api/transfer/one/chat-messages")` **叠在同一个 handler 上**，两条链路共用 `_chat_stream`。顺序是：解析 api_key → 查 `ap_app` → 取已发布图 → 幂等 → 并发槽 → 会话/历史 → 护栏 → 执行 → SSE 出口适配。槽位与幂等键在 `finally` 释放，覆盖流式异常与护栏拒绝。

`api/compat_api.py` 承载纯查询类兼容接口（会话/消息/反馈/建议/重命名、云智 `/api/open/dify/*`、原始 Dify 的 conversations/messages/parameters/workflows/files）；`api/admin.py` 是管理端（应用/图/护栏/MCP/知识库/看板/provider），`api/accounts.py` 是账号。三者都挂 `/admin` 前缀（除 compat）。

### 执行引擎（`engine/`）

数据流：`graph/schema.py` 的 `GraphDef`（pydantic，含每类节点的 config 校验）→ `engine/builder.py::build_graph` 编译成 LangGraph 状态图（`engine/state.py::GraphState`）→ `engine/runtime.py` 执行。

- `runtime.stream_graph` 走 `astream_events(version="v2")`，产出 `{"type": "token", "content": ...}` 增量，最后一条 `{"type": "final", "answer": ..., "state": ...}`。`run_graph` 是非流式版本。
- 节点实现集中在 `engine/nodes.py`（start/end、LLM、知识检索、条件分支、代码沙箱、HTTP/MCP 工具、变量聚合、回答）；`engine/expr.py` 提供 Jinja2 `render`（模板字段）与 `evaluate`（裸表达式，条件分支用）。
- `engine/context.py::EngineContext` 是引擎的依赖注入点：`llm` / `retriever` / `tools` / `tenant_code` / `tracer`，全是 Protocol，测试里可整体替换。`engine/factory.py::build_engine_context` 由 API 与 worker 共用装配。`api/deps.py` 的 `get_engine_context` 是 FastAPI 依赖，测试通过 `app.dependency_overrides` 注入假实现。

### Agent 应用（`agentapp/`）

`app_type=agent` 的应用不走图，直接进入原生 function-calling 循环：`runtime.py` 编译 `StateGraph`（`plan → agent ⟲ tools → reflect → finalize`，HITL 时可插入审批），`tools.py` 把声明式工具、知识检索、MCP 动态工具、子 Agent 与浏览器工具装配成 LangChain `StructuredTool`。`eval.py` 把 SSE 事件标准化为轨迹并评分；`tools/browser.py` 是基于 Playwright 的可选浏览器工具，默认关闭。

- **工具安全**：声明式工具复用 `tools/mcp_bridge.py` 的参数校验/重试/兜底；MCP 动态工具可用 `mcp_tool_allowlist` 只暴露白名单；工具调用可写 `ap_tool_audit`。
- **多 Agent**：子 Agent 委派返回强类型 `AgentHandoff` JSON；图内 agent 支持 `consensus` 模式（成员独立作答、多数票、平票裁决）。
- **HITL**：审批中断可经管理端或 Webhook 恢复；恢复链路同样自动写生产轨迹。
- **浏览器**：支持 iframe `frame_selector`、坐标点击/滚动、`browser_inspect`、`browser_som`（Set-of-Mark 标注截图）、CAPTCHA 检测；`AP_BROWSER_VISION_ENABLED=true` 时可用 `browser_look` 调多模态模型理解截图。

### 轨迹与评测

`AP_AGENT_TRACE_ENABLED=true` 时，流式 Agent 运行（含 HITL 恢复）把问题、工具路径、`tool_events`、答案、状态与耗时写入 `ap_agent_trace`。管理端 `GET /admin/agent-traces`、`GET /admin/agent-traces/stats` 与「Agent 轨迹」页查询；`core/agent_trace.py` 同时提供导出为评测轨迹的函数，`scripts/export_agent_traces.py` 是 CLI。评测支持工具序列 Levenshtein、`expected_tool_args`、`max_duration_ms`、禁用工具、答案关键字、状态/调用次数与可选 LLM judge。

### 安全与沙箱

- `core/prompt_guard.py`：规则剥离 + PII/密钥脱敏 + `<untrusted_data>` 边界；开启 `AP_PROMPT_GUARD_LLM_ENABLED` 后追加模型语义判定，高风险直接拦截，模型失败降级为规则清洗。
- `engine/code_sandbox.py`：默认 `inprocess`；`AP_CODE_SANDBOX_MODE=docker` 时断网、只读、非 root、cap-drop、资源/输出/超时限制。`AP_CODE_SANDBOX_REQUIRE_ISOLATION`、`REQUIRE_PINNED_IMAGE`、`REQUIRED_RUNTIME` 可把配置错误变成启动/执行失败，`GET /admin/sandbox/status` 返回自检结果。

### 出口适配

`api/compat.py` 把内部事件映射成对外 SSE（`message` / `agent_message` / `message_end` / `error`）与云智 `{code,msg,data}` Envelope。新增/改动输出必须同时过 `tests/test_compat_api.py` 与 `tests/test_api.py` 的契约回归。

### checkpointer

`checkpoint/mysql.py` 是自研的 MySQL `BaseCheckpointSaver`（put/get/list/put_writes + async 别名），落到 `ap_checkpoint*` 表：图执行状态进 checkpointer，会话历史进 `ap_message`，两者靠 `thread_id` 协同。

### 持久化层

`api/services.py` 是所有 ORM 读写的唯一出口（应用/图草稿与发布版本/会话/消息/敏感词/MCP server/摘要）。`core/db.py` 的 `session_scope()` 提交后关闭；`sessionmaker(expire_on_commit=False)`，因此 ORM 对象在 scope 外仍可读（_例如_ `refresh_summary` 会读写脱管的 `Conversation`）。

### 默认关闭的开关（本仓库的核心约定）

护栏、幂等、并发上限、管理端鉴权、历史窗口、历史摘要、MCP 工具发现（`AP_TOOL_DISCOVERY_ENABLED`）、checkpointer（`AP_CHECKPOINTER_ENABLED`）、人在环（`AP_HITL_ENABLED`）、动态子图（`AP_SUBGRAPH_ENABLED`）、用户级长期记忆（`AP_USER_MEMORY_*`）、Agent 应用总闸（`AP_AGENT_APP_ENABLED`）、浏览器（`AP_BROWSER_ENABLED`）、截图理解（`AP_BROWSER_VISION_ENABLED`）、语义注入检测（`AP_PROMPT_GUARD_LLM_ENABLED`）、生产轨迹（`AP_AGENT_TRACE_ENABLED`）与沙箱强制隔离（`AP_CODE_SANDBOX_REQUIRE_ISOLATION`）**全部默认关闭**，关闭时行为与改造前逐字节一致（不进图输入、不落库、不走模型）。`autonomous` agent 模式也只在智能体/节点显式选择时启用。改动这些链路时保持这个性质：新能力一律「配置开启才生效」，不要改变默认路径的输出。

### 配置

`core/config.py` 的 `Settings`（pydantic-settings，`AP_` 前缀）是配置的唯一来源；`.env.example` 是同步维护的清单。管理端有两个只读接口回显当前配置态：`GET /admin/providers`、`GET /admin/guard/config`。

### 数据库

`sql/ddl.sql` 建表（幂等）；`sql/` 下还有 `migrate_legacy_app.sql`（存量 `ai_monitor_app` → `ap_app`，依赖旧表）、`migrate_history_summary.sql`、`migrate_runs.sql`、`migrate_hitl_action.sql`、`migrate_hitl_outbox.sql`、`migrate_tool_audit.sql`、`migrate_agent_trace.sql` 等迁移。**脚本由人工执行**，仓库无自动迁移框架；老库加列必须写成 `information_schema.COLUMNS` 守卫（MySQL 8 不支持 `ADD COLUMN IF NOT EXISTS`，那是 MariaDB 语法），参考 `migrate_history_summary.sql` 的存储过程写法。干净库不要执行 `migrate_legacy_app.sql`。

## 测试约定

- 后端测试用临时 SQLite（`tests/conftest.py` 的 autouse fixture 建表），不依赖 MySQL/Redis；LLM/MCP/检索都用 mock。生产才连 MySQL。新增涉及 DB 的测试请沿用 `seed_app` 等 fixture，不要自建引擎。
- 浏览器测试（`tests/test_browser.py`）默认用 fake page，不要求 Playwright；只有显式安装 `.[browser]` 并 `playwright install chromium` 后才做真实浏览器验证。
- 前端只对纯逻辑模块做单测（`graph/mapper.js`、`graph/nodeMeta.js`、`api/client.js`、`router/guard.js`、`utils/chart.js`、`composables/useTable.js`），外加组件挂载与视图冒烟。`GraphCanvas.vue` / `GraphEditorView.vue` 依赖真实画布与路由参数，**刻意不做挂载测试**——可测逻辑都下沉到 `mapper.js`，改动图编辑器优先在那里加测试。
- 前端老手坑：`structuredClone` 不接受 Vue 响应式代理，克隆前先 `toRaw`（见 `NodeInspector.vue` / `RowsEditor.vue`）。**节点检查器下发的 `config` 必须是普通对象**——`NodeInspector.publish` 要在 `structuredClone(toRaw(...))` 后 emit，否则 `GraphCanvas.applyNode` 里的 `structuredClone` 抛 `DataCloneError`，节点改动静默失败（画布/草稿都不更新）。

## CI

`.github/workflows/ci.yml` 在 push / PR / 手动触发时跑：后端 `ruff`、`pytest`、示例轨迹评测门禁；前端 `npm ci`、`npm test -- --run`、`npm run lint`。CI 不安装 Playwright，浏览器单测使用 fake page。本地实机验证结论见根 `README.md` 与 `AGENTS.md` 的「环境验证」。

## 工作流

任务走 Trellis（`.trellis/tasks/<task>/`，含 `prd.md` / `task.json` / `implement.jsonl` / `check.jsonl`）。完成实现后需把进度回写到 `prd.md` 的实现状态清单里——这是本仓库的既有惯例。
