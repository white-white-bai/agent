# AGENTS.md

仓库级指令。更完整的中文说明见 `CLAUDE.md`（内容已核对，两者一致时以本文件为快速入口）。

## 仓库形态

- 只有两个平级工程，**没有 workspace/monorepo 工具链**（无根 package.json）；CI 在根 `.github/workflows/ci.yml`：
  - `agent-platform/` — Python（FastAPI + LangGraph），端口 8900
  - `agent-platform-ui/` — Vue 3 + Element Plus + AntV X6 管理端，端口 5199
- PRD 里的 `backend/`、`frontend/` 属于**外部仓库** `gov-service-ai-assistant`，不在本仓库内。
- 根 `.gitignore` 继承自别的模板，里面写的 `platform/`、`agent/`、`domains/` 等路径在本仓库不存在，别据此找目录。
- 权威文档（有冲突时按此顺序）：
  1. `.trellis/tasks/10-14-agent-platform/prd.md` —— 需求与逐条决策的唯一权威来源
  2. `.trellis/tasks/10-14-agent-platform/research/dify-cloud-contract.md` —— 对外兼容契约（SSE 事件序列、Envelope 形状）
  3. `agent-platform/README.md`、`agent-platform-ui/README.md` —— 各工程接口/页面细节

## 命令（均已实测）

```bash
# 后端（在 agent-platform/ 下；pythonpath=src、asyncio_mode=auto 已在 pyproject 配好）
pytest                                    # 全量 626 个用例；临时 SQLite + mock，不依赖 MySQL/Redis
python -m pytest tests/test_api.py::test_chat_stream_events   # 单测/单文件
python -m ruff check .                    # lint（line-length 120, py310）
python -m uvicorn agent_platform.api.main:app --reload --port 8900
python -m agent_platform.worker.main      # 异步任务 worker
python scripts/smoke_e2e.py               # 内网冒烟：连真 MySQL/云智/模型，只在开发库跑
python -m agent_platform.importer app.yml -o graph.json   # Dify DSL → 图定义

# 评测 / 轨迹
python scripts/eval_agent_traces.py --cases evals/agent_cases.example.jsonl --traces evals/agent_traces.example.jsonl
python scripts/export_agent_queries.py --tenant-code <tenant> --limit 100 --out evals/queries.jsonl
python scripts/record_agent_trace.py --app-uuid <uuid> --cases evals/queries.jsonl --out evals/recorded_traces.jsonl
python scripts/export_agent_traces.py --tenant-code <tenant> --days 7 --out evals/prod_traces.jsonl

# 前端（在 agent-platform-ui/ 下）
npm install --registry=https://registry.npmmirror.com   # 公司 nexus 不可达，必须显式指定源
npm run dev        # Vite 源码调试；浏览器用 http://localhost:5199（IPv6 ::1），127.0.0.1 连不上
npm test           # vitest run
npm run lint       # eslint flat config
npm run build      # 产物 dist/

# 可选：真实浏览器工具（不装时浏览器单测仍用 fake page）
pip install -e ".[browser]" && playwright install chromium

# 全栈一键（在 agent-platform/ 下；Docker，需本地 Docker Desktop 运行中）
docker compose up -d --build        # api + worker + ui + mysql + langfuse
docker compose up -d --build ui     # 只重建管理端（改了前端源码后必跑，否则 :5199 还是旧产物）
docker compose stop ui              # 腾出 5199 给 npm run dev
docker compose down                 # 停止并移除容器（数据卷保留；-v 连数据卷一起清）
```

- **先起后端再起前端**：前端把 `/admin` `/v1` `/api` `/healthz` 代理到 `AP_UI_PROXY_TARGET`（默认 127.0.0.1:8900），顺序反了接口 502。
- **`:5199` 谁在服务要看清**：compose 栈起来时，5199 是 `agent-platform-ui:dev` 容器里 nginx 托管的**打包产物**（页面加载 `/assets/index-*.js`），与 `npm run dev`（页面加载 `/src/main.js`）**互斥同端口**。此时改 `src/` 只是改源码，**必须 `docker compose up -d --build ui` 重建镜像才生效**，光刷新浏览器没用——排查「改了没效果」先看页面加载的是 `assets/index-*.js` 还是 `src/main.js`。
- 不接外部依赖时把 `AP_DB_DSN` 改成 `sqlite+pysqlite:///./.run/agent_platform.db`，建表由启动时 `init_db()` 完成，`sql/ddl.sql` 无需手工执行。
- Windows 下 `curl -d` 传非 ASCII 体会被控制台编码破坏：请求体写 UTF-8 文件用 `--data-binary @file`。

## 架构要点（从文件名看不出来）

- `api/main.py`：`/v1/chat-messages` 与 `/api/transfer/one/chat-messages` **两个路由叠在同一 handler**（`_chat_stream`）上，改一处影响两条链路。
- 出口适配在 `api/compat.py`（SSE `message`/`agent_message`/`message_end`/`error`，云智 `{code,msg,data}` Envelope）。**任何输出改动必须同时过 `tests/test_compat_api.py` 与 `tests/test_api.py` 的契约回归**——对外协议是硬约束（Java/前端零改动的前提）。
- 引擎链路：`graph/schema.py::GraphDef`（pydantic，逐类节点 config 校验）→ `engine/builder.py::build_graph` → `engine/runtime.py`（`astream_events` v2）。节点集中在 `engine/nodes.py`，模板/表达式在 `engine/expr.py`（Jinja2）。
- `engine/context.py::EngineContext` 是引擎唯一依赖注入点（llm/retriever/tools/tracer 全是 Protocol），测试用 `app.dependency_overrides` 替换 `api/deps.py::get_engine_context`。
- `api/services.py` 是所有 ORM 读写的唯一出口；`core/db.py::session_scope()` 提交后关闭，`sessionmaker(expire_on_commit=False)` 使脱管对象在 scope 外仍可读。
- **默认关闭开关是本仓库的核心约定**：护栏、幂等、并发上限、管理端鉴权、历史窗口、历史摘要、MCP 工具发现（`AP_TOOL_DISCOVERY_ENABLED`）、checkpointer（`AP_CHECKPOINTER_ENABLED`）、人在环（`AP_HITL_ENABLED`）、动态子图（`AP_SUBGRAPH_ENABLED`）、用户级长期记忆（`AP_USER_MEMORY_*`）、Agent 应用总闸（`AP_AGENT_APP_ENABLED`）、浏览器（`AP_BROWSER_ENABLED`）、截图理解（`AP_BROWSER_VISION_ENABLED`）、语义注入检测（`AP_PROMPT_GUARD_LLM_ENABLED`）、生产轨迹（`AP_AGENT_TRACE_ENABLED`）、沙箱强制隔离（`AP_CODE_SANDBOX_REQUIRE_ISOLATION`）全部默认 `false`/`0`，关闭时输出与改造前逐字节一致。`autonomous` agent 模式也只在智能体/节点显式选择时启用。新能力一律「配置开启才生效」，不要改变默认路径。
- **Agent 应用在 `agentapp/`**：`runtime.py` 跑原生 function-calling 循环（`plan → agent ⟲ tools → reflect → finalize`）；`tools.py` 装配声明式工具、知识、MCP、子 Agent 与浏览器工具；`eval.py` 做轨迹标准化与评分。`app_type=agent` 的总闸是 `AP_AGENT_APP_ENABLED`，默认关闭。
- **MCP 与多 Agent**：MCP 动态工具可用 `mcp_tool_allowlist` 最小暴露；子 Agent 委派返回 `AgentHandoff`；图内 agent 支持 `consensus` 多数投票模式（平票交裁决器）。
- **轨迹**：`AP_AGENT_TRACE_ENABLED=true` 时流式运行（含 HITL 恢复）写 `ap_agent_trace`；`GET /admin/agent-traces` 列表、`GET /admin/agent-traces/stats` 聚合、`scripts/export_agent_traces.py` 导出评测轨迹。
- **安全**：`core/prompt_guard.py` 规则清洗 + PII 脱敏 + `<untrusted_data>` 边界；`AP_PROMPT_GUARD_LLM_ENABLED` 再走模型语义判定，高风险拦截、失败降级。`GET /admin/sandbox/status` 返回沙箱自检结果。
- **代码沙箱**：默认 `inprocess`；`AP_CODE_SANDBOX_MODE=docker` 时断网/只读/非 root/cap-drop/资源与超时限制。`AP_CODE_SANDBOX_REQUIRE_ISOLATION`、`REQUIRE_PINNED_IMAGE`、`REQUIRED_RUNTIME` 不满足时启动与执行都失败关闭。
- **浏览器**：`tools/browser.py` 基于 Playwright，默认关闭；支持 iframe `frame_selector`、Shadow DOM、`browser_click_xy`/`browser_scroll`、`browser_inspect`、`browser_som`（Set-of-Mark 截图）、`browser_captcha` 检测；`AP_BROWSER_VISION_ENABLED` 开启 `browser_look` 多模态截图理解。
- 配置唯一来源：`core/config.py::Settings`（pydantic-settings，`AP_` 前缀）；改配置必须同步 `.env.example`。管理端只读回显 `GET /admin/providers`、`GET /admin/guard/config`。
- checkpointer 是自研 MySQL `BaseCheckpointSaver`（`checkpoint/mysql.py` → `ap_checkpoint*` 表）；会话历史在 `ap_message`，靠 `thread_id` 协同。
- `sql/` 下迁移脚本**人工执行**，无自动迁移框架；MySQL 8 不支持 `ADD COLUMN IF NOT EXISTS`，老库加列必须按 `migrate_history_summary.sql` 的 `information_schema.COLUMNS` 存储过程守卫写法。干净库跳过 `migrate_legacy_app.sql`（依赖旧表 `ai_monitor_app` / `xb_ai_monitor_app`）。

## 环境验证（2026-10-22）

| 项 | 结果 |
|---|---|
| 后端全量 | 626 个用例，退出码 0；`ruff` 通过 |
| 前端 | 233 个测试通过；eslint 通过；vite build 成功 |
| MySQL | compose MySQL 应用 `ddl.sql` 与非存量迁移成功，28 张表；API 直连 `/healthz`、轨迹统计、沙箱状态均 200 |
| 全栈 | api healthy、ui 200、`/healthz` 反代正常；真实浏览器可打开应用页与 Agent 轨迹页 |
| Playwright | 1.64 + Chromium 实机通过 headless/headful、iframe、fill/click、inspect、Set-of-Mark、CAPTCHA 检测 |
| Docker 沙箱 | 强制隔离下真实执行返回预期结果 |
| GitHub CI | 未 push，未在 GitHub 实跑；本地等价项通过 |

未完成：真实 100 条轨迹需要真实 query 数据后再录制；仓库不会伪造运行结果。

## 测试约定

- 后端：DB 相关测试沿用 `tests/conftest.py` 的 autouse 建表 fixture 和 `seed_app` 等 fixture，**不要自建引擎**；LLM/MCP/检索一律 mock。浏览器测试默认用 fake page，不要求 Playwright。
- 前端：只测纯逻辑（`graph/mapper.js`、`graph/nodeMeta.js`、`api/client.js`、`router/guard.js`、`utils/chart.js`、`composables/useTable.js`）+ 组件挂载冒烟；`GraphCanvas.vue` / `GraphEditorView.vue` **刻意不做挂载测试**，改动图编辑器时把可测逻辑下沉到 `mapper.js` 再加测试。
- 前端已知坑：`structuredClone` 不接受 Vue 响应式代理，克隆前先 `toRaw`（见 `NodeInspector.vue` / `RowsEditor.vue`）。**节点检查器下发的 `config` 必须是普通对象**——`NodeInspector.publish` 要在 `structuredClone(toRaw(...))` 后 emit，否则 `GraphCanvas.applyNode` 里的 `structuredClone` 抛 `DataCloneError`，节点改动静默失败（画布/草稿都不更新）。

## 工作流

- 任务走 Trellis：`.trellis/tasks/<task>/`（`prd.md` / `task.json` / `implement.jsonl` / `check.jsonl`）。
- 完成实现后把进度回写到 `prd.md` 的实现状态清单（本仓库既有惯例）。
- CI 在根 `.github/workflows/ci.yml`：后端 `ruff` / `pytest` / 示例轨迹评测，前端 `npm test -- --run` / `npm run lint`。
