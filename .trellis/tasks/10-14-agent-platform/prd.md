# agent 中台：基于 LangChain 的图编排引擎与统一管理平台

> 本文由 `/grill-me` 式逐分支访谈收敛而成（一条决策链、parent 先行）。所有「已确认决策」来自用户逐题确认；「拟定默认」为未逐题确认、但已具合理默认值、可在实现中调整的项。

## Goal

现有 `gov-service-ai-assistant` 以 **Dify**（经「云智平台」`kdsmart/prod-api` 封装，及部分直连 Dify）作为 agent 编排引擎。
目标：在本仓库内**新建一个独立的 agent 中台**，用 **LangChain / LangGraph** 自建编排引擎与统一管理平台，
替换 Dify 的编排能力，实现 agent 的集中注册、可视化编排、运行执行、监控与观测。

中台对本仓库现有的 Java 后端与前端应做到**协议兼容、对外无感替换**（Java/前端零改动）。

## Current State（本会话亲自勘查）

- **后端**：Java 8 / Spring Boot 多模块（`kd-api`、`kd-system`、`kd-common`、`kd-job`），MyBatis-Plus、MySQL、Redis，
  Jenkins + Docker Swarm 部署（独立 deploy 仓库 ansible），鉴权走云石/KDCore（`SecurityUtils`、`@PreAuthorize`）。
- **Dify 编排**：`AiController`（常州，`KdsmartDifyConfig`）与 `XBAiAgentController`（新北，`XBAiDifyConfig`）
  经 `WebClient` 透传 SSE 到云智 `/api/transfer/one/chat-messages`；另有 `DifyConfig` 直连原始 Dify（`ai.kingdonsoft.com:5001`）。
- **模型**：藏在云智「通用大模型调用器」工作流后（`generic_llm_app_id`，入参 `llm_name`/`system_prompt`/`user_prompt`，见 `KdsmartDifyLlmUtil`）。
- **知识**：知流平台（`ai_knowflow_*`、`dataset_id`）、LightRAG、知识图谱（`knowledge-graph`）。
- **注册表**：`ai_monitor_app` / `xb_ai_monitor_app` / `ai_intelligent_agent_item`（含 `app_id`/`api_key`/`agent_picurl` 等）。
- **护栏（Java 侧，Dify 之前）**：敏感词 `SensitiveCheckUtils`、额度 `AiAssistantTokenLimitService`、频率/匿名轮数限制、
  默认回复、会话保存 `ai_assistant_conversation`、流标题过滤 `LogTitleMarker`。
- **监控链路**：`kd-job` 定时任务经云智 `listConversationDirect` 等同步 `ai_monitor_*`；前端 `ai-monitor` 页面呈现。
- **前端**：Vue 3.3 + Element Plus 2.4 + Vite 4（`frontend/`），另有 `frontend-digital-human/`。
- **约定**：字段级 SM4 加密（`encryptInterceptorEnabled` + `databaseSM4Key/IV`）；避免解释性注释；变更尽量最小、向后兼容。
- **流程**：仓库使用 Trellis 工作流（`.trellis/`）。

## 已确认决策（grill 收敛，逐题确认）

### 架构 / 引擎
1. **技术栈**：Python 独立中台服务（FastAPI + LangChain/LangGraph）。
2. **集成边界**：**两层 100% 协议兼容** —— 同时模拟云智封装层（`/api/oauth2/token`、`/api/transfer/one/*`、`/api/open/dify/*`，
   含 JWT + Api-Key 鉴权与嵌套响应体）与原始 Dify `/v1/*`；Java 只改 base-url 指向中台，前端与业务代码零改动。
3. **编排能力**：**可视化图编排**（对标 Dify）。
4. **图定义**：**自建 schema**（基于 LangGraph 状态图），编辑器用 **AntV X6**；仓库内自研；**后续**再做 Dify 导入工具；
   存量编排图**先手动重建少量**。
5. **引擎**：**LangGraph 图引擎** + **核心节点集**：start/end、LLM、知识检索、条件分支、代码、HTTP/MCP 工具、变量聚合、回答。
6. **checkpointer**：**自研 MySQL checkpointer**（实现 `BaseCheckpointSaver`，图状态与会话消息同库，复用现有 MySQL；Redis 做热缓存/锁）。
7. **执行模型**：对话流式请求走 FastAPI **API 直出 SSE**；长任务（工作流批处理、知识入库、报告生成）交 **worker 异步**（Redis 队列）。
8. **记忆**：**窗口 + 可选摘要**（消息落 MySQL，与 checkpointer 协同：checkpointer 管图执行状态、消息表管历史）。

### 模型 / 知识 / 工具
9. **模型接入（混合）**：默认复用云智「通用大模型调用器」工作流，**封装为自定义 LangChain ChatModel**（`llm_name` 映射模型）；同时支持配置 **OpenAI 兼容的私有 provider**，按 agent 选择。
10. **知识/检索（混合）**：**内置向量库** 为主，同时提供**外接**（知流 / LightRAG / 知识图谱）**Retriever 适配器**。
11. **工具**：**MCP 协议为主**；中台**内置 HTTP→MCP 桥**，自己托管 MCP Server 把声明的 HTTP/OpenAPI 工具暴露为 MCP 工具给 agent；
    同时中台作 **MCP Client** 可接外部真 MCP Server。（现有 Java 8 政务接口零改动。）

### 数据 / 存储
12. **存储**：**复用现有 MySQL 实例**（中台新建独立 schema）+ **Redis**。
13. **图存储**：**JSON document 整存**一张表（nodes/edges/node_config 内嵌），关键字段（app_id/tenant/状态）冗余成列。
14. **版本**：**草稿 + 发布版本**（每次发布生成不可变快照，运行态只跑已发布版本，支持回滚）。
15. **加密**：**复用现有 SM4** 密钥/IV 实现同款字段级加解密，与现有库兼容。
16. **注册表**：**中台新表**（`app_id`/`api_key` 沿用现有值）+ **迁移脚本**导入存量 `ai_monitor_app`。

### 安全 / 租户 / 账号
17. **鉴权/账号**：中台**独立账号体系、完全自建**，**不动 Java 侧**。
18. **租户**：**单实例多租户**（`tenant_id` = 区域/appCode）；不同区域用不同 Api-Key 绑定 tenant，共用一套引擎。
19. **护栏**：**全部下沉中台**，但**过渡期双跑** —— Java 护栏暂不动，中台护栏代码先上**不启用**，后续切换。

### UI / 部署 / 运维
20. **管理 UI**：**独立中台前端**工程（基础栈 Vue3 + Element Plus + Vite；图编辑器 **AntV X6**）。
21. **部署**：**独立 docker-compose 单机多容器**（中台 API + worker + **Langfuse**），复用内网 MySQL/Redis，nginx 配域名与 Java 互通。
22. **监控**：**中台新做监控**；旧 `kd-job` 同步任务与 `ai-monitor` 页面**不动**（Dify 并存，新老并存逐步切换）。
23. **观测/追踪**：**Langfuse 自托管**，**节点级 trace**（输入/输出/token/耗时/工具调用/检索命中）+ 汇总看板。

### 里程碑 / 布局
24. **首个里程碑（引擎优先）**：先做 **LangGraph 图引擎 + 节点体系 + 执行器（checkpoint/流式）**，再补前端编辑器。
25. **代码布局**：仓库内**新增顶层目录**（与 `backend/`、`frontend/` 平级）。

## 已确认的实现细节

- **变量系统**：类 Dify（每个 agent 定义 inputs schema：类型/必填/默认；节点输出经变量引用；区分全局/会话/节点输出变量），
  但**条件与表达式用表达式引擎**（Jinja2/JMESPath）。
- **条件分支**：**表达式引擎**驱动。
- **代码节点**：**受限 Python 沙箱**（限定内置库/禁网/超时/内存限制），代码随图配置存储。
- **流式实现**：内部用 LangGraph `astream_events` 统一事件流，**出口适配器**映射成云智/Dify 事件序列
  （`message`/`agent_message`/`message_end`/`error` 等），字段严格对齐（`answer`/`conversation_id`/`message_id`/`metadata.retriever_resources`）。
- **文件/多模态**：中台提供兼容上传接口；文件**作变量由节点消费**（文档→RAG 检索，图片→透传视觉模型）；存现有文件中心或中台存储。
- **并发/限流/幂等**：内置限流（按 app/tenant/用户）、幂等键（conversation+message 去重）、并发上限与排队；双跑期与 Java 限流并存。
- **护栏配置源**：**中台自建**敏感词/额度/轮数配置（中台管理端维护），双跑期与 Java 各持一份。
- **测试策略**：分层 —— 引擎/执行器单测 + 节点集成测试（mock LLM/MCP/检索）+ 端到端冒烟（真实模型）+ 关键契约（SSE 事件/兼容接口）回归。
- **Dify 导入器**：**后续里程碑**做完整映射（节点类型/变量/知识库/工具），不支持的高级节点降级并给提示。

## 拟定默认（未逐题确认，实现中可调）

- 中台托管 MCP Server 的 transport 用 **Streamable HTTP**；工具声明支持从 **OpenAPI 导入**或手填，鉴权头可配。
- `conversation_id` / `message_id` 由中台生成（对前端不透明），格式与现有兼容。
- Python 工程用 `pyproject.toml` + 依赖管理（如 uv/poetry）；代码风格与测试框架在实现时定（pytest + ruff 为默认）。
- 中台前端工程目录名与 Python 服务目录名在实现时定（拟定 `agent-platform/` 与 `agent-platform-ui/`）。

## Requirements（按里程碑）

### M1 引擎优先（首个里程碑交付）
- [x] 仓库内新增中台顶层目录骨架（Python 服务 + 配置 + 迁移脚本目录）。
- [x] 图 schema（JSON document）定义 + **草稿/发布版本**存储（中台 MySQL 新表）。
- [x] **核心节点集**执行器：start/end、LLM、知识检索、条件分支、代码（沙箱）、HTTP/MCP 工具、变量聚合、回答。
- [x] **LangGraph 执行器**：`astream_events` 流式 + **自研 MySQL checkpointer**（断点续跑/human-in-loop 基础）。
- [x] **变量/表达式系统**：inputs schema + 变量引用 + 表达式引擎（Jinja2/JMESPath）。
- [x] **模型适配器**：云智「通用大模型调用器」自定义 ChatModel + OpenAI 兼容私有 provider。
- [x] **知识适配器**：内置向量库 Retriever + 外接（知流/LightRAG/知识图谱）Retriever。
- [x] **MCP**：内置 HTTP→MCP 桥（托管 MCP Server）+ MCP Client 接入。
- [x] **记忆**：窗口已实现（`AP_HISTORY_WINDOW`，历史以 `history` 变量注入图输入）；**可选摘要**已实现
  （`AP_HISTORY_SUMMARY_ENABLED`，窗口之外的历史压缩为 `summary` 变量注入，见「M1 续批（2026-10-14）· 记忆摘要」）。

### M2 兼容与集成
- [x] **两层兼容接口**：云智封装层（`/api/oauth2/token`、`/api/transfer/one/*`、`/api/open/dify/*`）+ 原始 Dify `/v1/*`。
- [x] **SSE 出口适配器**：事件与字段严格对齐前端解析器（`LogTitleMarker` / `trimMessageEndMetadata` 语义不变）。
- [x] **应用注册表 + 迁移脚本**：导入存量 `ai_monitor_app`（`app_id`/`api_key` 沿用）。
- [x] **护栏**：敏感词/额度/频率/轮数/默认回复（先上不启用，双跑）。
- [x] **限流/幂等**：按 app/tenant/用户 —— 限流已随护栏实现（`AP_GUARD_RATE_ENABLED`，默认关闭）；幂等键
  （`AP_IDEMPOTENCY_TTL_SECONDS`，默认只在显式传键时生效）与 per-app 并发上限（`AP_MAX_CONCURRENCY_PER_APP`，
  可配排队 `AP_CONCURRENCY_WAIT_SECONDS`）已接线，均默认关闭，行为与改造前一致。

### M3 管理与观测
- [x] **独立中台前端**：agent 列表、图编辑器（AntV X6）、模型/工具(MCP)/知识库/provider 配置、账号/角色、护栏配置。见「M3 续批（2026-10-14）· 独立中台前端」。
- [x] **监控看板**：会话量/满意度/token/错误率（中台 MySQL + Langfuse 汇总）。
- [x] **Langfuse 自托管**集成：节点级 trace 上报。
- [x] **独立账号体系（后端）**：种子管理员 + 自管理角色/权限；租户维度隔离。见「M3 续批（2026-10-14）· 账号」。

### M4 迁移工具（后续）
- [x] **Dify 导入器**：Dify DSL → 中台 schema 映射；不支持节点降级 + 提示。见「M4 续批（2026-10-14）· Dify 导入器」。

## Acceptance Criteria

- [x] Java 后端仅改 base-url/鉴权即可把对话链路指向中台，前端零改动（兼容接口与其契约回归测试已就位；Java 源码按 Out of Scope 不动）。
- [x] 兼容接口的响应 Envelope（如 `data.data.data.outputs`、`data.records` 分页）与云智一致。
- [x] SSE 事件序列与字段使现有前端解析器无回归。
- [x] 引擎能执行一个含 LLM + 知识检索 + 条件分支 + MCP 工具的图，并支持流式输出与 checkpoint 恢复。
- [x] 单实例多租户下，配置与运行数据按 `tenant_id` 正确隔离。

## Definition of Done（团队质量基线）

- [x] M1 引擎单测与节点集成测试通过（mock LLM/MCP/检索）。
- [x] 兼容接口的契约回归测试通过（SSE 事件 + Envelope）。
- [x] 逻辑复查：跨层数据流（图配置 → 执行器 → checkpointer/消息表 → 兼容接口出口）一致。
- [x] 交付物含建表/迁移脚本（仓库无 DDL 目录时随任务交付，人工执行）。

## Out of Scope（显式）

- 不改动现有 Java 后端与前端源码（对外协议优先，Java 内部瘦身不在本任务强制）。
- 不复刻 Dify 的会话 DSL（自建 schema，导入器后续做）。
- M1 不做前端编辑器与监控看板（属 M3）。
- 不做语音识别等外部能力（仍走现有 Java 层）。

## Risks / 待实现时敲定

- **MCP 生态**：Java 8 侧无 MCP 支持 → 依赖中台内置 HTTP→MCP 桥；桥的鉴权/超时/错误映射需细化。
- **MySQL checkpointer**：LangGraph 官方无 MySQL 实现，自研需覆盖 resume / 版本迁移 / 并发一致性。
- **两层兼容**：云智与原始 Dify 鉴权方式不同（JWT+Api-Key vs Bearer apiKey），出口适配器需分别处理。
- **云智网关复用**：以 workflow 形态封装的 ChatModel 在流式/token 统计上可能与原生有差异，需实测。
- **表达式引擎安全**：Jinja2 自由表达式的沙箱与注入风险需评估。
- **多区域口径**：`tenant_id` = 区域/appCode 的具体映射（含溧阳等特例）在实现时对齐现有 `dept-data-source-mapping` 约定。

## Technical Notes

- 现有 Java 关键文件：
  - `backend/kd-api/.../controller/ai/AiController.java`、`.../controller/xb_ai/XBAiAgentController.java`
  - `backend/kd-common/.../util/dify/DifyUtil.java`、`KdsmartDifyLlmUtil.java`、`LogTitleMarker.java`
  - `backend/kd-common/.../config/DifyConfig.java`、`KdsmartDifyConfig.java`、`XBAiDifyConfig.java`
  - `backend/kd-common/.../domain/po/AiMonitorApp.java`、`XbAiMonitorApp.java`
  - `backend/kd-job/.../handler/AutoSyncAi*.java`
- 现有前端：`frontend/src/api/agent-management/api.js`、`frontend/src/views/ai-monitor/`、`frontend/src/views/intelligent-agent*/`
- 配置样例：`backend/kd-api/src/main/resources/application-dev.yml`（`dify-config` / `kdsmart-dify-config` / `xb-ai-dify-config` / `light-rag-config` / `knowledge-graph` / `ai-number` 等）

## 实现状态（M1 首批，2026-10-14）

新增顶层目录 `agent-platform/`（Python 服务），已完成可运行的引擎骨架：

- [x] 工程骨架：`pyproject.toml`、`README.md`、`.env.example`、`Dockerfile`、`docker-compose.yml`（API + worker 占位 + Langfuse）、`.gitignore`
- [x] 配置与基础设施：`core/config.py`（pydantic-settings）、`core/db.py`（SQLAlchemy 2.0 + session_scope）
- [x] 领域模型：`domain/models.py`（`ap_tenant`/`ap_app`/`ap_graph`/`ap_graph_version`/`ap_conversation`/`ap_message`/`ap_sensitive_word`/`ap_checkpoint`/`ap_checkpoint_write`）
- [x] 图 schema：`graph/schema.py`（核心节点集 + 每类节点 config 校验 + JSON model_dump 往返）
- [x] 执行引擎：`engine/`（`expr` Jinja2 模板/表达式、`code_sandbox` 受限沙箱、`context`、`nodes` 9 类节点、`builder` LangGraph 编译、`runtime` 运行 + `astream_events` 流式）
- [x] checkpointer：`checkpoint/mysql.py`（自研 MySQL `BaseCheckpointSaver`，put/get/list/put_writes + async 别名）
- [x] 模型适配：`models/cloud_gateway.py`（云智「通用大模型调用器」封装为 LangChain `BaseChatModel`，含 oauth2 token 缓存）、`models/factory.py`（cloud_gateway / openai）
- [x] 知识适配：`knowledge/retrievers.py`（builtin 占位 + light_rag / knowflow / knowledge_graph HTTP 适配）
- [x] 工具适配：`tools/mcp_bridge.py`（内置 HTTP→MCP 桥，声明式工具调用）
- [x] 兼容出口：`api/compat.py`（SSE `data:` 事件：message / message_end / error）+ `api/main.py`（`/v1/chat-messages` 与 `/api/transfer/one/chat-messages` 别名、`/healthz`）
- [x] 测试：`tests/`（schema、expr、engine、condition、checkpointer、api 共 18 项，全绿；`ruff check` 通过）

**M1 续批（2026-10-14）**：以下已完成并覆盖测试。

- [x] 管理与图 API：`api/admin.py`（应用 CRUD；图草稿保存 `PUT /graph/draft`、发布 `POST /graph/publish`、版本列表、回滚 `POST /graph/rollback`；`/sensitive-words`、`/mcp-servers`、`/documents` 配置接口）
- [x] 会话与消息兼容查询接口：`api/compat_api.py`（云智 `/api/transfer/one/chat-messages/conversations|messages|feedback|suggested|stop|rename` + `/api/open/dify/*` 全量；原始 Dify `/v1/conversations`、`/v1/messages`、`/v1/parameters`、`/v1/workflows/run`、`/v1/files/upload`）
- [x] 护栏：`core/guards.py`（敏感词 / 额度 / 频率 / 轮数 / 默认回复，`AP_GUARD_ENABLED=false` 全链路短路，先上不启用）
- [x] MCP Client：`tools/mcp_client.py`（Streamable HTTP + JSON-RPC 2.0、`Mcp-Session-Id` 会话、SSE `data:` 解析）+ `tools/mcp_bridge.py` 接入外部真 MCP Server（配置 `AP_TOOL_SERVERS` 或库表 `ap_mcp_server`）
- [x] Langfuse 埋点：`observability/langfuse.py`（节点级 trace；未配置/异常时降级 no-op，不阻断执行）
- [x] 内置向量库：`knowledge/embeddings.py` + `knowledge/vector_store.py`（哈希嵌入默认，可配远程 embedding；`ap_document` 增删查 + 余弦检索）
- [x] worker 异步任务：`worker/`（Redis 队列 `ap:jobs`，进程内降级；任务 `knowledge_ingest` / `graph_batch_run` / `report_generate`；入口 `python -m agent_platform.worker.main`）
- [x] 迁移脚本：`sql/ddl.sql` + `sql/migrate_legacy_app.sql`（存量 `ai_monitor_app` / `xb_ai_monitor_app` → `ap_app`，沿用 `app_id`/`api_key`，`INSERT IGNORE` 幂等，人工执行）
- [x] 记忆窗口：`core/config.py`（`AP_HISTORY_WINDOW`）+ `api/services.py`（`load_history`）+ `api/main.py`（`history` 变量注入图输入；默认 0 时不注入，行为与改造前逐字节一致）
- [x] 测试：`tests/` 199 项全绿（schema/expr/engine/nodes/condition/checkpointer/api/admin/compat/knowledge/mcp/worker/observability/guards/crypto/security），`ruff check` 通过

**M2 续批（2026-10-14）**：以下已完成并覆盖测试。

- [x] 幂等键：`core/idempotency.py`（`Idempotency-Key` 头 / body `idempotency_key`，TTL 内命中复用首次结果且不重复落库；`AP_IDEMPOTENCY_DERIVE_KEY=false` 时不自行推导，避免同会话重复提问被误判为重放）
- [x] 并发上限：`core/concurrency.py`（per-app 计数槽 + TTL 兜底 + 可选排队；`AP_MAX_CONCURRENCY_PER_APP<=0` 关闭）
- [x] 接入：`api/main.py`（`/v1/chat-messages` 与 `/api/transfer/one/chat-messages` 共用入口：应用 → 图 → 幂等 → 并发 → 会话/历史 → 护栏 → 执行；槽位与幂等键在 `finally` 释放，覆盖流式异常与护栏拒绝）
- [x] Redis 原语：`core/redis.py` 增 `set_if_absent` / `delete`（沿用既有降级封装）
- [x] 内网冒烟：`scripts/smoke_e2e.py`（真 MySQL + 真云智网关 + 真实模型：建表 → 注册/复用应用 → 发布图 → 打原始 Dify 与云智两条链路 → 断言 SSE 事件序列与各 Envelope 形状，含工作流三重嵌套）
- [x] 测试：`tests/test_idempotency.py`、`tests/test_concurrency.py` 共 23 项（单测 + API 契约），全套 222 项全绿，`ruff check` 通过

**M1 续批（2026-10-14）· 记忆摘要**：决策 8「窗口 + 可选摘要」的摘要部分已完成并覆盖测试。

- [x] 模型与建表：`domain/models.py` 的 `Conversation` 增 `summary` / `summary_upto_id`；`sql/ddl.sql` 同步建表，
  另附 `sql/migrate_history_summary.sql`（存在即跳过，老库幂等补列）
- [x] 配置：`AP_HISTORY_SUMMARY_ENABLED`（默认 `false`，需同时开启窗口）、`AP_HISTORY_SUMMARY_PROVIDER`（默认
  `cloud_gateway`）、`AP_HISTORY_SUMMARY_MODEL`、`AP_HISTORY_SUMMARY_MAX_CHARS`（默认 4000）
- [x] 摘要：`api/services.refresh_summary`（取窗口之外且在水位线之后的消息，与上一轮摘要合并后重新压缩；
  水位线随摘要落 `ap_conversation`，无新增可压缩内容时不调用模型）
- [x] 降级：模型不可用 / 空回复时返回上一轮摘要并保持水位线不动，不阻断对话；`max_chars` 逐条累加截断，
  超出部分留待下一轮，不丢消息
- [x] 接入：`api/main.py`（`summary` 变量注入图输入，默认关闭时图输入与改造前逐字节一致）
- [x] 测试：`tests/test_history_summary.py` 9 项（关闭窗口短路、无溢出短路、溢出压缩与水位线、增量合并、
  截断不丢消息、模型失败与空回复降级、接口注入与默认关闭），`ruff check` 通过

**M3 续批（2026-10-14）· 账号**：独立账号体系后端已完成并覆盖测试。

- [x] 模型与建表：`domain/models.py` 增 `AdminRole` / `AdminUser`；`sql/ddl.sql` 增 `ap_admin_role` / `ap_admin_user`（幂等 DDL，人工执行）
- [x] 核心：`core/accounts.py`（PBKDF2-HMAC-SHA256 20 万轮 + 每账号 16 字节随机盐单向存口令；内置 `admin`/`editor`/`viewer` 三角色；`AdminPrincipal.allows` 通配权限与 `scope_tenant` 租户隔离；`seed()` 幂等播种种子管理员）
- [x] 令牌：复用兼容层 JWT 签名并加 `typ=admin` 与角色/租户声明，`principal_from_token` 拒绝云智 `client_credentials` 令牌，双向不可冒充
- [x] 接入：`api/deps.py`（`get_current_admin` / `require_admin` / `require_permission`）、`api/accounts.py`（`/admin/login|me|users|roles`）、`api/admin.py`（全部路由加权限点与租户收口）、`api/main.py`（挂载路由 + 开启时 lifespan 播种）
- [x] 默认关闭：`AP_ADMIN_AUTH_ENABLED=false` 时 `/admin` 免鉴权（匿名全权），历史契约测试零改动
- [x] 测试：`tests/test_accounts.py` 27 项（口令哈希/校验、角色权限、租户收口、登录与停用、令牌类型隔离、种子幂等、管理端 401/403 与 CRUD），全套 249 项全绿，`ruff check` 通过

**M4 续批（2026-10-14）· Dify 导入器**：Dify DSL → 中台图定义导入已完成并覆盖测试。

- [x] 转换器：`importer/dify.py`（`convert` / `parse_dsl` / `load_dsl`；`_Converter` 完成节点/边/变量映射与降级重连）
- [x] 可映射节点：`start` / `end` / `llm` / `knowledge-retrieval` / `if-else` / `code`(python3) / `tool` / `variable-aggregator` / `answer`
- [x] 降级：其余节点（`http-request`、`template-transform`、非 python3 的 `code` 等）旁路丢弃并按 DFS 传递重连前后边，逐条给出 `warnings`；`all of` / `any of` 等 Jinja2 无法表达的比较降为常量 `false` 并提示
- [x] 变量改写：`{{#node.var#}}` 按目标字段语义改写为 `{{ }}` 模板（提示词/query/answer）或裸表达式（end 输出、条件、code 入参、tool 参数）；Dify 字符串化比较值对关系运算符做数值还原
- [x] CLI：`python -m agent_platform.importer app.yml [-o out.json] [--llm-provider] [--retriever] [--app-id] [--name]`
- [x] 管理端：`POST /admin/apps/{uuid}/graph/import`（body `{dsl|content, llm_provider, retriever, name, save}`，默认存草稿；应用不存在 404，DSL 非法 400）；`api/schemas.py` 增 `GraphImportRequest`
- [x] 依赖：`pyproject.toml` 增 `pyyaml>=6.0`（DSL 支持 YAML）
- [x] 测试：`tests/test_importer.py` 28 项 + `tests/test_admin_api.py` 导入 4 项（节点/边映射、模板与裸表达式改写、条件分支与句柄、工具参数、降级重连、坏 DSL 拒绝、JSON/YAML 解析、导入接口契约），`ruff check` 通过

**M3 续批（2026-10-14）· 监控看板**：中台自有表的看板汇总已完成并覆盖测试。

- [x] 模型与建表：`domain/models.py` 增 `MetricEvent`；`sql/ddl.sql` 增 `ap_metric_event`（幂等 DDL，人工执行）
- [x] 汇总：`core/metrics.py`（`overview`：会话量 / 消息量（user/assistant）/ 满意度（like/dislike/rate）/ token / 错误率，
  按天零填充序列；`record_error` 旁路写入错误事件，失败不阻断主流程）
- [x] 埋点：`api/main.py` 对话链路 `except` 分支落一条 `kind=error`（不落 assistant 消息，既有兼容输出与分页不变）
- [x] 管理端：`GET /admin/metrics/overview?tenant_code=&app_uuid=&days=`（权限点 `metrics:read`，租户由 `scope_tenant` 收口，
  `days` 取 1..90）；内置 `editor` / `viewer` 角色补 `metrics:read`，`seed()` 对既有内置角色做权限补齐（仍幂等）
- [x] 测试：`tests/test_metrics.py` 11 项（空态零填充、聚合与比率、天数窗口收敛、租户/应用收口、错误事件落库与截断、
  存储失败吞掉、接口 Envelope/401/租户隔离、链路异常埋点端到端），`ruff check` 通过

**M3 续批（2026-10-14）· 独立中台前端**：`agent-platform-ui/` 独立工程（Vue 3.4 + Element Plus 2.7 + Vite 5.4 + Pinia + vue-router 4.4 + AntV X6 2.18），只消费既有 `/admin` 协议，不改动 Java 后端与前端源码。

- [x] 工程骨架：`package.json` / `vite.config.js`（`AP_UI_PROXY_TARGET` 默认 `http://127.0.0.1:8900`，代理 `/admin`、`/v1`、`/api`、`/healthz`）/ `eslint.config.js`（flat config）/ `README.md`
- [x] 接口与鉴权：`api/client.js`（token 读写、`{data}` Envelope 解包、401 统一登出、FastAPI `detail` 字符串/422 数组归一为可读信息）+ `api/index.js`（全部管理接口）+ `stores/auth.js`（`can()` 通配权限）+ `router/guard.js`（未登录跳 `/login?redirect=`，越权落 `/403`）
- [x] 页面：登录、应用注册（`AppsView`）、图编辑器（`GraphEditorView`：X6 画布、节点面板/检查器、草稿保存、发布、版本回滚、Dify DSL 导入与降级提示）、模型与检索（`ProvidersView`）、MCP 工具、知识库、护栏配置、账号与角色、监控看板（会话/消息/满意度/token/异常五类卡片 + 三张趋势图）、403
- [x] 图映射：`graph/nodeMeta.js`（9 类节点元数据与默认 config）+ `graph/mapper.js`（图定义 ⇄ X6 cell 纯函数映射，后端 snake_case 原样保留）
- [x] 后端配套：`GET /admin/providers`（四类 provider 配置态）、`GET /admin/guard/config`（进程级护栏开关与阈值，只读）；内置 `editor`/`viewer` 角色补 `provider:read`
- [x] 缺陷修复：`NodeInspector` / `RowsEditor` 克隆前先 `toRaw` —— `structuredClone` 不接受 Vue 响应式代理，选中节点或增删行时必抛 `DataCloneError`
- [x] 测试：`tests/` 10 个文件 150 项全绿（client/api/nodeMeta/mapper/guard/chart/useTable/auth 纯逻辑单测 + 组件挂载 + 各视图冒烟）；`npm run lint` 无告警，`npm run build` 通过。X6 画布与图编辑器依赖真实画布与路由参数，不做挂载测试，其可测逻辑已下沉至 `mapper.js`

**M3 续批（2026-10-14）· 应用注册表缺陷修复**：`app_id` 软删除后唯一键仍占用，重复注册触发未捕获
`IntegrityError` 直接 500，已修复。

- [x] 复活：`api/services.create_app` 命中同租户软删除记录时原位复活（置 `is_deleted=0` 并按入参覆盖字段，
  `uuid` 沿用，既有图与会话记录一并恢复）；`ap_app` 唯一键语义不变，无需改 DDL
- [x] 冲突：同 `app_id` 在用中，或软删除记录属其他租户时抛 `AppIdConflictError`，`POST /admin/apps` 映射为 409
- [x] 测试：`tests/test_admin_api.py` 增 3 项（在用冲突 409 / 删除后复活且沿用 uuid 并回到列表 / 跨租户拒绝 409）

**M3 续批（2026-10-16）· 图编辑器节点内容自动保存与编辑修复**：画板改节点内容不生效、且需手动保存，已修复。

- [x] 根因：`NodeInspector.publish` 直接下发 `draft.value.config`（Vue 响应式代理），`GraphCanvas.applyNode` 里的 `structuredClone(patch.config)` 抛 `DataCloneError`，
  每次输入在写回画布前即中断——节点数据不落画布、`dirty` 不置位、草稿不保存
- [x] 修复：`publish` 改下发 `structuredClone(toRaw(draft.value.config) || {})` 的普通对象；`NodeInspector` 重建草稿的 watcher 由「返回数组的 getter」改为 `id|type` 字符串 key，
  避免父级每次下发新 node 对象都判定为变化而重建草稿（原实现每次输入都重克隆）
- [x] 自动保存：`GraphEditorView` 用 `markDirty()` 收口脏标记（画布 `@change`、增删节点、插入模板），600ms 防抖调用 `saveGraphDraft`；请求期间的新改动在完成后接续保存；
  手动保存 / 发布 / 导入 / 回滚 / 组件卸载时清掉定时器；顶栏显示「保存中…」/「未保存」
- [x] 测试：`tests/components.spec.js` 增 1 项回归（下发的 config 必须能被 `structuredClone`，原实现抛 `DataCloneError`）；`npm test` 173 项全绿，`npm run lint` 通过

**M-续批（2026-10-16）· 知识库完善（对齐 Dify）**：把「一行=一分段」的简陋实现升级为知识库两层模型，补齐入库/分段/召回测试/图节点选择器。

- [x] 数据模型：新增 `ap_dataset`（知识库）+ `ap_document_segment`（分段），`ap_document` 改为文档元数据（`name/file_type/file_size/char_count/chunk_count/status/error` + 原文 `content`）；
  `sql/ddl.sql` 同步三张表，`sql/migrate_knowledge_segments.sql`（`RENAME TABLE` + `information_schema` 守卫）把老「文档即分段」数据按 `(租户,dataset,title)` 归组成文档与分段
- [x] 服务层：拆 `knowledge/datasets.py`（知识库 CRUD + 级联）与 `knowledge/documents.py`（文档/分段 CRUD、分页、按租户隔离删除、重建分段）；`knowledge/vector_store.py` 检索改到分段（join 文档、过滤未删/停用），
  命中保留 `content/document_name` 以兼容 `metadata.retriever_resources`
- [x] 入库：`knowledge/ingest.py`（分块→逐块向量化→落分段→回填状态）；小文件同步、大文件异步——`dispatch_ingest` 在 Redis 可用时入 worker 队列，否则进程内 `asyncio` 任务；`worker/jobs.knowledge_ingest` 改为按 `document_uuid` 入库；
  新增配置 `AP_KNOWLEDGE_ASYNC_THRESHOLD_BYTES`（默认 1MB）
- [x] 管理端 API：`/admin/datasets`（CRUD）、`/admin/datasets/{uuid}/documents`（列表/文本入库/上传）、`/admin/datasets/{uuid}/retrieve`（召回测试）、`/admin/documents/{uuid}`（删/重传）、`/admin/documents/{uuid}/segments`、`/admin/segments/{uuid}`（改/启停/删）；旧 `/admin/documents` 下线
- [x] 前端：`KnowledgeView` 重构为「知识库列表 + 文档表」两栏，新增 `components/knowledge/{DatasetPanel,DocumentTable,SegmentDrawer,HitTestDialog}.vue`；上传走 XHR 进度条（`client.uploadRequest`）；`pending` 文档轮询；图节点 `dataset_ids` 改用新 `dataset-select` 下拉并暴露 `coarse_top_k/hybrid/rerank`
- [x] 测试：后端 `tests/{test_knowledge,test_retrieval,test_worker,test_admin_api}.py` 改配分段语义并新增知识库/文档/分段/召回测试，`pytest` 434 项 + `ruff` 通过；前端 `tests/{api,views,components,nodeMeta}.spec.js` 更新，`npm test` 186 项 + `npm run lint` + `npm run build` 通过

**M-续批（2026-10-16）· 知识库创建向导 + 知识库级处理设置（对齐 Dify）**：分段/清洗/索引/检索设置落到知识库级并在入库与检索时生效。

- [x] 分段与清洗：新增 `knowledge/chunking.py`（`normalize_config` / `preprocess_text`（折叠连续空白、删 URL 与邮箱）/ `split_text`（可配分隔符，泛化原 `chunk_text`）/ `split_qa`（**规则式**问答对切分，无问句标记回退通用）/ `chunk_document`）；`uploads.chunk_text` 改为薄封装
- [x] 数据模型：`ap_dataset` 增 `index_method`（高质量/经济）与 `chunk_config`，`ap_document` 增 `chunk_config`（每文档覆盖）；`sql/ddl.sql` 同步，新增守卫迁移脚本 `sql/migrate_knowledge_config.sql`
- [x] 入库按配置：`resolve_chunk_config`（**文档覆盖 > 知识库默认 > 全局** `AP_DOCUMENT_CHUNK_*`）；`ingest_document` 走 `chunk_document`，`index_method=economy` 时**不生成向量**（分段 embedding 为空）
- [x] 检索模式：`retrieve_hits` 支持 `vector`/`fulltext`/`hybrid`；新增 `resolve_retrieval`（读知识库 `retrieval.mode`，economy 强制 fulltext）；`build_builtin_searcher` 优先级 **节点 > 知识库 > 全局**；`KnowledgeConfig` 增 `mode`
- [x] 管理端 API：`DatasetUpsertRequest` 增 `index_method`/`chunk_config`；新增 **分段预览** `POST /admin/knowledge/preview`（不落库）；上传/文本入库支持每文档 `chunk_config`
- [x] 前端：新增 `KnowledgeWizard`（三步：选数据源 → 分段与清洗含「预览块/预估块」→ 处理并完成）、`ChunkSettingsForm`、`ChunkPreview`；知识库编辑弹窗与上传弹窗支持分段/索引/检索设置与**每文档覆盖**
- [x] 测试：后端 `pytest` 462 项 + `ruff` 通过（新增 `tests/test_chunking.py`，及 `test_knowledge`/`test_admin_api` 的知识库/预览/经济/全文/覆盖用例）；前端 `npm test` 192 项 + `lint` + `build` 通过
- [x] 文档：`agent-platform/README.md`（分段/清洗、索引方式、预览接口、检索模式与优先级、迁移脚本）、`agent-platform-ui/README.md`

**M-续批（2026-10-20）· 向强 Agent 对齐：autonomous 模式**：在既有 `agent` 节点内新增原生工具调用闭环，图编排仍是外层边界。

- [x] Agent 模式：`AGENT_MODES` / `MODES` 新增 `autonomous`（显式选择，默认不启用）；现有 7 种模式与内置智能体不变
- [x] LLM 调用层：`LLMInvoker` 增加可选 `messages/tools/tool_choice/return_message/tags`（旧 5 参数路径不变）；`models/factory.py` 支持 `bind_tools`、返回 `AIMessage`、ChatOpenAI 复用与可配超时/重试
- [x] 自主循环：消息栈（system + summary + history + query）、原生 `tool_calls` → `ToolMessage` 回灌、连续失败重规划、重复调用早停、轮数耗尽禁用工具收口、工具结果截断
- [x] 工具 schema：新增 `tools/schema.py`（`ap_tool.params` / MCP `inputSchema` → OpenAI function schema、点号工具名安全化与映射）
- [x] MCP 运行时发现：新增 `tools/discovery.py`（`tools/list` + TTL 缓存 + 租户隔离 + 上限），`ToolRef.discover` 控制；`AP_TOOL_DISCOVERY_ENABLED` 默认关闭
- [x] 流式过滤：自主循环中间轮与反思轮不下发 token，最终答复轮 flush；对外 SSE 事件不变
- [x] 前端：智能体页与 agent 节点新增 `autonomous` 选项、节点级 `tools/pipeline/prompt_template/reflection_rounds` 字段，`RowsEditor` 支持布尔列
- [x] 测试：后端新增 `test_agent_autonomous.py` / `test_tool_discovery.py` / `test_stream_filter.py`，并补齐 schema/agents/admin 用例；前端补 agent 字段与布尔行用例
- [x] 文档：`agent-platform/README.md`、`agent-platform/.env.example`
- [x] 未纳入本批：用户级长期记忆、checkpointer 接线与 `interrupt/resume` 人在环、运行时改图/动态选子图（已在下一节交付）

**M-续批（2026-10-20）· 用户级长期记忆 / HITL / 动态子图**：三块能力全部默认关闭，关闭时现有链路不变。

- [x] 用户级长期记忆：新增 `ap_user_memory` / `ap_user_memory_state`；`memory/{store,recall,extract}.py` 做 CRUD、去重、水位线增量抽取、向量/全文/混合召回与注入；按租户+应用+用户隔离；管理端 CRUD/召回测试/按用户物理清除；`AP_USER_MEMORY_*` 默认关闭
- [x] checkpointer 修复与接线：补 `ap_checkpoint.metadata_type`、`LONGBLOB`、`ap_checkpoint_write.task_path`；修复 `put_writes` 的 `WRITES_IDX_MAP`/去重/排序、`list(before/filter)`、`delete_thread`、async 不阻塞；`AP_CHECKPOINTER_ENABLED` 控制对话链路接线
- [x] HITL：新增 `approval` 节点与 `interrupt()/Command(resume=...)`；管理端 run 新增 `run_started`/`interrupt` 事件、`ap_run` 运行记录、`/admin/runs*` 列表/详情/恢复接口；前端图编辑器与「运行记录」页支持审批/驳回；对外 `/v1`、云智链路不暴露 interrupt，审批节点自动通过
- [x] 动态子图：新增 `subgraph` 节点/`SubgraphRef`/`SubgraphConfig`；`services.resolve_subgraph/validate_subgraph_refs/pin_subgraph_refs`；builder 递归编译候选子图并复用 `route` 条件边；发布时校验引用/租户/环/深度；`AP_SUBGRAPH_ENABLED` 默认关闭
- [x] 前端：新增「用户记忆」「运行记录」页；图编辑器新增 `approval`/`subgraph` 节点、`graph-select` 字段、运行中断面板与恢复按钮
- [x] SQL：`sql/ddl.sql` 同步新表/列；新增 `sql/migrate_checkpoint_hitl.sql`、`sql/migrate_user_memory.sql`、`sql/migrate_runs.sql`
- [x] 测试：新增 `test_user_memory.py`、`test_hitl.py`、`test_checkpoint_wiring.py`、`test_subgraph.py`；扩展 `test_checkpoint.py`；前端补 run/api/views/components/nodeMeta 用例
- [x] 文档：`agent-platform/README.md`、`.env.example`、`agent-platform-ui/README.md`、`AGENTS.md`/`CLAUDE.md`
- [x] P0 加固（2026-10-20）：HITL 恢复原子抢占、`/admin/runs/{thread_id}/cancel` 与前端取消、`resolved_by/resolved_at` 审计、`AP_HITL_RUN_TIMEOUT_SECONDS` 回收超时 `interrupted`；子图发布递归钉版本、HITL 运行写 `subgraph_snapshot` 并在详情/恢复时优先使用、`inputs/query/output_var` 在编译子图链路生效且不覆盖父图上下文；用户记忆近似去重、按当前 embedding 模型/维度过滤旧向量、`rebuild-embeddings` 接口与管理端按钮
- [x] 2026-10-21 评测/沙箱/安全：`agentapp/eval.py` + `scripts/eval_agent_traces.py` 轨迹标准化、工具路径 Levenshtein 距离、禁用工具/答案/状态约束、可选 LLM judge 与 CI 门禁；代码节点新增 Docker 隔离沙箱（默认 inprocess，docker 模式断网/只读/非 root/资源限制/超时清理）；`core/prompt_guard.py` 对外部工具输出做注入剥离与 `<untrusted_data>` 边界（默认关闭）；HITL Webhook 通知（含 resume endpoint，失败降级）
- [ ] 未纳入：浏览器/电脑控制（Step 3，需要 Playwright/浏览器运行时）、Webhook 侧的审批回调签名校验与幂等重放、用户记忆跨应用聚合的独立 UI（当前用 `AP_USER_MEMORY_SCOPE` 配置）

**M1～M4 决策清单**：无未交付项。

**环境备注**：本机 Python 3.11.1；依赖已 `pip install -e ".[dev]"`；测试用临时 SQLite（`conftest.py`），生产用 MySQL（`sql/ddl.sql` 人工执行）。

**M-续批（2026-10-16）· 真 Agent（新增 Agent 应用类型）**：把「伪 agent（提示词模板 + 正则解析 `Action:`）」升级为「真 agent（LLM 原生 function-calling 驱动的自主循环）」，作为独立应用类型接入现有对话兼容链路。既有 7 模式 agent 节点**保持不动**，与之并存。

- [x] 形态：`App.app_type == "agent"` 的应用走自主运行时（无图），配置为「指令 + 模型 + 工具 + 知识 + 记忆 + 规划/反思 + 子 agent + HITL」；总闸 `AP_AGENT_APP_ENABLED`（默认 `false`，关闭时行为与改造前逐字节一致）
- [x] 定义 schema：`agentapp/schema.py::AgentAppDef`（+ `AgentToolRef` / `AgentMemoryConfig` / `AgentHitlConfig`），复用 `graph/schema.py::KnowledgeConfig`
- [x] 数据模型：`domain/models.py` 增 `AgentApp` / `AgentAppVersion`，`Tool` 增 `description`；`sql/ddl.sql` 同步；`sql/migrate_agent_app.sql`（守卫建表 + `information_schema` 加列，人工执行）
- [x] 服务：`api/services.py` 镜像图那组 —— `save_agent_draft / get_agent_draft / publish_agent_draft / list_agent_versions / rollback_agent / get_published_agent`（发布时 `AgentAppDef.model_validate` 校验）
- [x] 模型接口：`models/factory.py::build_chat_model`（OpenAI 兼容、`streaming=True`、可 `bind_tools`）+ `build_chat_model_builder`；`EngineContext` 增 `chat_model`（带默认值，不影响既有 `llm` 单轮协议）
- [x] 运行时：`agentapp/{builder,tools,runtime}.py` —— LangGraph `StateGraph`（`MessagesState`）：`[plan] → agent ⟲ tools → [reflect] → finalize`，`ToolNode` 原生工具循环；记忆用自研 `MySQLCheckpointSaver`（`thread_id=conversation_id` 跨轮持久，`pre_model_hook` 裁剪 `memory.window` 并注入 `summary`）；规划/反思为可配开关
- [x] 工具：`ap_tool.params → JSON Schema`（`StructuredTool`），执行复用 `tools/mcp_bridge.call_declared_tool`（白拿校验/重试/兜底）；知识检索工具；子 agent 委派工具（`AP_AGENT_APP_DEPTH` 深度受限）；**MCP Server 动态发现**（`mcp_servers` → `tools/list` 的 `inputSchema` 自动转工具，失败降级不阻断）
- [x] HITL：`interrupt` 审批节点（`policy` off/before_all_tools/before_listed），拒绝注入错误 `ToolMessage` 让模型自适配；`resume_agent` 走 `Command(resume=...)`；会话存在待审批中断时新轮不静默续跑；**记忆清理** `DELETE /admin/apps/{uuid}/agent/conversations/{cid}/memory`（`MySQLCheckpointSaver.delete_thread`）
- [x] 入口：`api/main.py::_chat_stream` 按 `app_type` 分叉到 `stream_agent`，产出同一 `token`/`final` 契约（`chunks` 回填 `retriever_resources`），下游幂等/并发/历史/护栏/SSE/落库**复用不变**；非流式兼容（`runWorkflow` / `/v1/workflows/run`）同步分叉
- [x] 管理端：`api/admin.py` 增 `GET/PUT /apps/{uuid}/agent[/draft]`、`POST .../agent/{publish,rollback,run,resume}`、`GET .../agent/versions`；`api/schemas.py` 增 `AgentApp*Request`
- [x] 前端：`AgentConfigView.vue`（配置表单 + 调试对话台，含 HITL 批准/拒绝）、隐藏路由 `/apps/:appUuid/agent`、`AppsView` 行操作按 `app_type` 分叉
- [x] 测试：后端 `tests/test_agent_app.py` 17 项（定义/服务/工具 schema/原生工具循环/规划/checkpointer 记忆/子 agent 深度/MCP 动态发现/HITL 批准与拒绝/待审批不重跑/记忆清理/入口分叉与默认关闭回退/管理端 CRUD 与续跑契约），全套 481 项全绿 + `ruff` 通过；前端 `npm test` 202 项 + `lint` + `build` 通过；`scripts/smoke_e2e.py` 增 Agent 应用对话用例（真模型内网执行）

