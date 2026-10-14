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
- [x] **记忆**：窗口已实现（`AP_HISTORY_WINDOW`，历史以 `history` 变量注入图输入）；**可选摘要**未实现（本条原文标注「可选」）。

### M2 兼容与集成
- [x] **两层兼容接口**：云智封装层（`/api/oauth2/token`、`/api/transfer/one/*`、`/api/open/dify/*`）+ 原始 Dify `/v1/*`。
- [x] **SSE 出口适配器**：事件与字段严格对齐前端解析器（`LogTitleMarker` / `trimMessageEndMetadata` 语义不变）。
- [x] **应用注册表 + 迁移脚本**：导入存量 `ai_monitor_app`（`app_id`/`api_key` 沿用）。
- [x] **护栏**：敏感词/额度/频率/轮数/默认回复（先上不启用，双跑）。
- [ ] **限流/幂等**：按 app/tenant/用户 —— 限流已随护栏实现（`AP_GUARD_RATE_ENABLED`，默认关闭）；幂等键与并发上限已预留配置（`AP_IDEMPOTENCY_TTL_SECONDS` / `AP_MAX_CONCURRENCY_PER_APP`）但**未接线**。

### M3 管理与观测
- [ ] **独立中台前端**：agent 列表、图编辑器（AntV X6）、模型/工具(MCP)/知识库/provider 配置、账号/角色、护栏配置。
- [ ] **监控看板**：会话量/满意度/token/错误率（中台 MySQL + Langfuse 汇总）。
- [x] **Langfuse 自托管**集成：节点级 trace 上报。
- [ ] **独立账号体系**：种子管理员 + 自管理角色/权限；租户维度隔离。

### M4 迁移工具（后续）
- [ ] **Dify 导入器**：Dify DSL → 中台 schema 映射；不支持节点降级 + 提示。

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

**未纳入本批**：M3 的独立中台前端与监控看板、独立账号体系（角色/权限管理端），M4 的 Dify 导入器；记忆的「可选摘要」；`AP_IDEMPOTENCY_TTL_SECONDS` / `AP_MAX_CONCURRENCY_PER_APP` 已预留配置但未接线。

**环境备注**：本机 Python 3.11.1；依赖已 `pip install -e ".[dev]"`；测试用临时 SQLite（`conftest.py`），生产用 MySQL（`sql/ddl.sql` 人工执行）。

