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
│   ├── core/                # 配置、DB、Redis、日志、账号（角色/权限/口令）、监控汇总
│   ├── domain/              # ORM 模型（应用/租户/图/会话/护栏）
│   ├── graph/               # 图定义 schema（pydantic）
│   ├── importer/            # Dify DSL → 中台图定义（导入器 + CLI）
│   ├── engine/              # LangGraph 执行器与节点
│   ├── models/              # 模型适配器（云智网关 / OpenAI 兼容）
│   ├── knowledge/           # 检索适配器（内置向量库 / 外接平台）
│   ├── tools/               # MCP（内置 HTTP→MCP 桥 + MCP Client）
│   ├── checkpoint/          # 自研 MySQL checkpointer
│   ├── observability/       # Langfuse 节点级 trace（未配置降级为 no-op）
│   ├── worker/              # 异步任务（Redis 队列 + 任务处理器）
│   └── api/                 # FastAPI + 兼容接口
├── scripts/                 # 内网冒烟脚本
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

- 应用：`GET|POST /apps`、`GET|PUT|DELETE /apps/{uuid}`。删除为软删除；`app_id` 全局唯一，再次注册同 `app_id` 会
  原位复活该应用（沿用原 `uuid`，既有图与会话记录一并恢复），同 `app_id` 在用或属其他租户时返回 409。
- 图：`GET /apps/{uuid}/graph`、`PUT /apps/{uuid}/graph/draft`、`POST /apps/{uuid}/graph/publish`、
  `GET /apps/{uuid}/graph/versions`、`POST /apps/{uuid}/graph/rollback`、`POST /apps/{uuid}/graph/import`
  （Dify DSL 导入，见下；运行态只跑已发布版本）。
- 配置：`/sensitive-words`、`/mcp-servers`、`/documents`（内置向量库）。
- 账号：`POST /login`（免鉴权）、`GET /me`、`/users`、`/roles`（见下）。
- 看板：`GET /metrics/overview`（见下）。

健康检查：`GET /healthz`。

## Dify 导入

把 Dify 导出的 DSL（JSON / YAML）转成中台图定义，供存量应用平滑迁移。CLI：

```bash
python -m agent_platform.importer app.yml -o graph.json   # 缺省打印到 stdout
python -m agent_platform.importer app.yml --llm-provider openai --retriever light_rag
```

管理端：`POST /admin/apps/{uuid}/graph/import`，body 二选一 `dsl`（对象）或 `content`（JSON/YAML 字符串），
其余可选 `name`（覆盖应用名，缺省取应用注册名）、`llm_provider`、`retriever`、`save`（默认 `true` 直接存草稿）；
返回 `{stats, warnings, definition}`，`warnings` 逐条说明降级与需人工复核项。应用不存在 404，DSL 非法 400。

- **可映射节点**：`start` / `end` / `llm` / `knowledge-retrieval` / `if-else` / `code`(python3) / `tool` /
  `variable-aggregator` / `answer`。
- **降级**：其余节点（如 `http-request`、`template-transform`、非 python3 的 `code`）旁路丢弃并提示，其前后边按
  DFS 传递重连；`all of` / `any of` 等 Jinja2 无法表达的比较降为常量 `false` 并提示。
- **变量引用**：Dify `{{#node.var#}}` 按目标字段语义改写 —— 模板字段（LLM 提示词、知识库 query、answer）还原为
  `{{ }}` 模板，表达式字段（end 输出、条件、code 入参、tool 参数）还原为裸表达式。
- **LLM 适配**：Dify 的模型 provider 不映射，统一落到 `--llm-provider`（默认 `cloud_gateway`），模型名沿用 DSL，
  参数取 `completion_params`（缺省 temperature 0.7）。`tool` 节点落到 MCP，需按 `server` 名在中台注册 MCP Server。

## 数据库与迁移

```bash
mysql -h host -P 3306 -u user -p agent_platform < sql/ddl.sql                    # 建表（幂等）
mysql -h host -P 3306 -u user -p agent_platform < sql/migrate_history_summary.sql # 老库补记忆摘要列（幂等）
mysql -h host -P 3306 -u user -p agent_platform < sql/migrate_legacy_app.sql      # 存量 ai_monitor_app 导入
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
默认 `0` 表示关闭，此时图输入与改造前完全一致。

`AP_HISTORY_SUMMARY_ENABLED`（默认 `false`，需同时开启窗口）把窗口之外的历史压缩成摘要，以 `summary`
变量注入图输入，供提示词长期记忆用：摘要落在 `ap_conversation.summary` + `summary_upto_id` 水位线，
每轮只压缩水位线之后、窗口之外的新增消息并与上一轮摘要合并，失败（模型不可用 / 空回复）静默降级为上一轮摘要，
不阻断对话。`AP_HISTORY_SUMMARY_MAX_CHARS` 限制单轮送入模型的字符数，超出部分留待下一轮，不会丢消息；
生成用 `AP_HISTORY_SUMMARY_PROVIDER` / `AP_HISTORY_SUMMARY_MODEL`，temperature 取 0.2。

老库需执行 `sql/migrate_history_summary.sql` 补列（幂等），新建库直接用 `sql/ddl.sql`。

## 幂等与并发（默认关闭）

`/v1/chat-messages` 与 `/api/transfer/one/chat-messages` 共用一条入口，支持幂等键与 per-app 并发上限，两者默认关闭、
行为与改造前逐字节一致。

- **幂等**：`AP_IDEMPOTENCY_TTL_SECONDS`（默认 600，`<=0` 关闭）。仅在调用方显式传 `Idempotency-Key` 头或 body
  `idempotency_key` 时生效，命中则复用首次结果且不重复落库；置 `AP_IDEMPOTENCY_DERIVE_KEY=true` 后按
  `app+user+conversation+query` 自行推导（同会话内正常重复提问会被判为重放，慎开）。
- **并发**：`AP_MAX_CONCURRENCY_PER_APP`（默认 0 表示不限）。超限时按 `AP_CONCURRENCY_WAIT_SECONDS`（默认 0，立即拒绝）
  轮询等空位，仍拿不到槽位则返回 `error` 事件；槽位带 TTL 兜底，进程异常退出不会永久占位。

两者共用 Redis 计数/键值，Redis 不可用时降级为进程内存储（单实例语义）。

## 独立账号体系（默认关闭）

`AP_ADMIN_AUTH_ENABLED=false` 时 `/admin` 免鉴权（匿名全权），行为与改造前逐字节一致；置 `true` 后管理端
需 `Authorization: Bearer <token>`，且启动时幂等播种内置角色与种子管理员。

- **口令**：PBKDF2-HMAC-SHA256（20 万轮）+ 每账号随机 16 字节盐，单向存储；SM4 可逆，不用于口令。
- **令牌**：复用兼容层 JWT 签名，额外带 `typ=admin` 与角色/租户声明。云智 `client_credentials` 令牌与
  管理端令牌互不冒充：前者过不了 `/admin` 的 `typ` 校验，后者在兼容链路查不到 app `api_key`。
- **角色**：内置 `admin`（`*`）、`editor`（读写应用/图/护栏/MCP/知识库 + 看板与 provider 只读）、`viewer`（只读，含看板与 provider），可自建 / 删除自建角色，
  内置角色不可删。权限点形如 `app:read`、`graph:write`，路由级 `require_permission(...)` 校验。
- **租户隔离**：账号绑定 `tenant_code` 后，列表/新增接口只能看到与写入本租户数据（`scope_tenant`）；
  未绑定（空）表示全局，与改造前一致。

```bash
curl -X POST localhost:8900/admin/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'          # → {"data":{"token":...}}
curl localhost:8900/admin/apps -H "Authorization: Bearer <token>"
```

种子账号名/口令与令牌有效期由 `AP_ADMIN_SEED_USERNAME`、`AP_ADMIN_SEED_PASSWORD`、`AP_ADMIN_TOKEN_TTL_SECONDS`
配置；**上线前必须改掉默认口令**。

## 监控看板

`GET /admin/metrics/overview?tenant_code=&app_uuid=&days=7`（权限点 `metrics:read`；`days` 取 1..90，`0` 视为缺省 7）。
数据全部取自中台自有表，不依赖 Langfuse（未配置时其已降级 no-op）：

```json
{"data": {
  "range": {"days": 7, "start": "2026-10-08", "end": "2026-10-14"},
  "conversations": {"total": 12, "series": [{"date": "2026-10-08", "count": 1}, ...]},
  "messages": {"total": 40, "user": 20, "assistant": 20},
  "satisfaction": {"like": 3, "dislike": 1, "rate": 0.75},
  "tokens": {"total": 1200, "series": [...]},
  "errors": {"total": 2, "rate": 0.1, "series": [...]}
}}
```

- 会话量 / 每分钟消息 / token 取自 `ap_conversation`、`ap_message`；满意度取 `ap_message.feedback`（`like`/`dislike`），
  `rate = like / (like + dislike)`；错误率 `rate = 错误数 / 用户提问轮数`。
- 错误事件写在 `ap_metric_event`：对话链路抛异常时由 `core/metrics.record_error` 落一条 `kind=error`（旁路写入，
  失败不影响主流程），不落 assistant 消息，故不影响会话/消息分页等既有兼容输出。
- 序列按天零填充（缺数据的日期补 0），可直接画图；租户维度由账号 `scope_tenant` 收口。

## provider 与护栏配置（只读）

供管理端展示，不落库、不可改（改配置走 `.env`）：

- `GET /admin/providers`（权限点 `provider:read`）：返回 `llm` / `retriever` / `embedding` / `observability`
  四类的 `{name, label, configured, detail}`，`configured` 由当前 settings 是否配齐凭据推导。
- `GET /admin/guard/config`（权限点 `guard:read`）：返回进程级护栏开关与阈值（总开关、敏感词、额度、频率、轮数、
  日 token 配额、每分钟速率、最大轮数、默认回复）。

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

# 依赖外部实例：先在 .env 填好 AP_DB_DSN（MySQL）、AP_REDIS_URL，再启动
python -m uvicorn agent_platform.api.main:app --reload --host 127.0.0.1 --port 8900
```

不接外部依赖、只跑本地演示时，把 DSN 指向文件库即可跑通全链路（建表由启动时的 `init_db()` 完成，
`sql/ddl.sql` 无需手工执行）：

```bash
# .env
AP_ENV=dev
AP_HTTP_PORT=8900
AP_DB_DSN=sqlite+pysqlite:///./.run/agent_platform.db
AP_DEFAULT_TENANT=changzhou

python -m uvicorn agent_platform.api.main:app --reload --host 127.0.0.1 --port 8900
```

健康检查与对话入口（两条路由叠在同一 handler 上，鉴权用 `Api-Key` 头或 `Authorization`）：

```bash
curl -s http://127.0.0.1:8900/healthz                        # {"status":"ok"}
curl -s -X POST http://127.0.0.1:8900/v1/chat-messages \
  -H 'Api-Key: <api_key>' -H 'Content-Type: application/json' \
  --data-binary @payload.json                                # {"query":"...","user":"u","response_mode":"streaming"}
```

Windows 下 `curl -d` 直接传非 ASCII 体会被控制台编码破坏，请求体写成 UTF-8 文件用 `--data-binary @file`。

管理端为独立前端 `../agent-platform-ui`，`npm run dev` 在 5199 起 Vite 并把 `/admin` `/v1` `/api` `/healthz`
代理到 `AP_UI_PROXY_TARGET`（默认 `http://127.0.0.1:8900`）。

## 内网冒烟

```bash
python scripts/smoke_e2e.py                                    # 进程内 ASGI，读 .env，连真 MySQL / 云智 / 模型
python scripts/smoke_e2e.py --base-url http://127.0.0.1:8900   # 打已部署实例
python scripts/smoke_e2e.py --app-id smoke-e2e --api-key <存量 api_key>
```

建表 → 注册/复用应用 → 保存并发布图 → 依次打原始 Dify `/v1/chat-messages`、云智
`/api/transfer/one/chat-messages` 两条链路，断言 SSE 事件序列与各 Envelope 形状（会话/消息分页、
`listConversationDirect`、工作流三重嵌套），并按需校验幂等重放。固定 `app_id`（默认 `smoke-e2e`），每次运行新增一个
图版本，**只应在开发/测试库执行**。不可用项以 `[skip]` 标出、失败以 `[FAIL]` 标出并返回非零退出码。
