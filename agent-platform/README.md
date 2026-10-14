# agent-platform（agent 中台）

基于 LangChain / LangGraph 的图编排引擎与统一管理平台，用于替换 `gov-service-ai-assistant` 现有 Dify 编排能力。

需求与决策见 `../.trellis/tasks/10-14-agent-platform/prd.md`；兼容契约见同目录 `research/dify-cloud-contract.md`。

## 定位

- **引擎优先**：LangGraph 图引擎 + 核心节点集 + MySQL checkpointer + 流式。
- **协议兼容**：对外模拟云智封装层与原始 Dify `/v1`，Java/前端零改动（M2）。
- **统一管理**：应用注册、可视化编排（AntV X6）、模型/工具(MCP)/知识库、监控与观测（M3）。

## 目录结构

```
agent-platform/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── sql/                     # 建表 / 迁移脚本（人工执行，仓库无 DDL 目录）
├── src/agent_platform/
│   ├── core/                # 配置、DB、Redis、日志
│   ├── domain/              # ORM 模型（应用/租户/图/会话/护栏）
│   ├── graph/               # 图定义 schema（pydantic）
│   ├── engine/              # LangGraph 执行器与节点
│   ├── models/              # 模型适配器（云智网关 / OpenAI 兼容）
│   ├── knowledge/           # 检索适配器（内置向量库 / 外接平台）
│   ├── tools/               # MCP（内置 HTTP→MCP 桥 + MCP Client）
│   ├── checkpoint/          # 自研 MySQL checkpointer
│   ├── observability/       # Langfuse 节点级 trace（未配置降级为 no-op）
│   ├── worker/              # 异步任务（Redis 队列 + 任务处理器）
│   └── api/                 # FastAPI + 兼容接口
└── tests/
```

## 接口

**兼容层**（Java/前端零改动，`api/main.py` + `api/compat_api.py`）

- Dify `/v1`：`/v1/chat-messages`（SSE）、`/v1/conversations`、`/v1/messages`、`/v1/messages/{id}/feedbacks|suggested`、
  `/v1/conversations/{id}/name`、`/v1/parameters`、`/v1/workflows/run`、`/v1/files/upload`。
- 云智封装层：`/api/oauth2/token`、`/api/transfer/one/chat-messages`（含 `/conversations`、`/messages`、`/feedback`、
  `/suggested`、`/stop`、`/rename`）、`/api/open/dify/*`（`difyApp`、`getDifyAppInfo`、`listConversationDirect`、
  `listConversationMessageDirect`、`listConversationMessageFeedbacksDirect`、`listDifyEndUser`、`runWorkflow`、`parameters`）。
- SSE 事件：`message` / `agent_message` / `message_end` / `error`；云智响应体为 `{code,msg,data}` 嵌套 Envelope。

**管理接口**（`api/admin.py`，前缀 `/admin`）

- 应用：`GET|POST /apps`、`GET|PUT|DELETE /apps/{uuid}`。
- 图：`GET /apps/{uuid}/graph`、`PUT /apps/{uuid}/graph/draft`、`POST /apps/{uuid}/graph/publish`、
  `GET /apps/{uuid}/graph/versions`、`POST /apps/{uuid}/graph/rollback`（运行态只跑已发布版本）。
- 配置：`/sensitive-words`、`/mcp-servers`、`/documents`（内置向量库）。

健康检查：`GET /healthz`。

## 数据库与迁移

```bash
mysql -h host -P 3306 -u user -p agent_platform < sql/ddl.sql               # 建表（幂等）
mysql -h host -P 3306 -u user -p agent_platform < sql/migrate_legacy_app.sql  # 存量 ai_monitor_app 导入
```

迁移脚本沿用现有 `app_id` / `api_key`，按区域分表逐个设置 `@tenant_code`，可重复执行。

## 异步任务（worker）

```bash
python -m agent_platform.worker.main
```

任务类型：`knowledge_ingest`（知识入库）、`graph_batch_run`（工作流批处理）、`report_generate`（报告汇总）。
队列走 Redis（`AP_REDIS_URL`），队列键 `ap:jobs`；Redis 不可用时降级为进程内队列。

## 护栏（先上不启用）

`AP_GUARD_ENABLED=false` 时整条护栏链短路，行为与现状一致；下线后按 `AP_GUARD_*` 逐项开启敏感词/额度/频率/轮数，
默认回复由 `AP_GUARD_DEFAULT_REPLY` 配置。双跑期 Java 侧护栏不动。

## 记忆

`AP_HISTORY_WINDOW` 控制注入图输入的历史消息条数（按会话取最近 N 条，倒序取正序注入 `history` 变量）；
默认 `0` 表示关闭，此时图输入与改造前完全一致。摘要（summary）未实现。

## 观测

配置 `AP_LANGFUSE_HOST` / `AP_LANGFUSE_PUBLIC_KEY` / `AP_LANGFUSE_SECRET_KEY` 后按节点上报 trace；
未配置或 Langfuse 不可用时自动降级为 no-op，不阻断执行。

## 本地运行

```bash
cd agent-platform
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env
pytest
uvicorn agent_platform.api.main:app --reload --port 8900
```
