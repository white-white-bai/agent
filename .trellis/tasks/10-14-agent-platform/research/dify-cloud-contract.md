# 调研：现有 Dify / 云智契约（中台兼容目标）

> 来源：本会话亲读 `AiController`、`XBAiAgentController`、`DifyUtil`、`DifyConfig`、`KdsmartDifyConfig`、
> `KdsmartDifyLlmUtil`、`AiConstants`、`frontend/src/api/agent-management/api.js`、`application-dev.yml`。
> 用途：中台「两层 100% 兼容」的契约基线。**实现 M2 前必须复核此文件与最新代码是否一致。**

## 1. 鉴权

### 云智平台（`KdsmartDifyConfig` / `XBAiDifyConfig`）
- 取 token：`POST {baseUrl}/api/oauth2/token`
  - Content-Type: `application/x-www-form-urlencoded`
  - form：`grant_type=client_credentials`、`client_id`、`client_secret`
  - 响应：`{ code: 200, data: { token, expire } }`（token 缓存于 Redis，按 expire 秒）
- 转包请求头：`Authorization: JWT <token>` + `Api-Key: <app 的 api_key>`

### 原始 Dify（`DifyConfig`）
- 会话接口鉴权：`Authorization: Bearer <apiKey>`（各 app 的 `api-key`）
- 控制台登录：`POST {baseUrl}/console/api/login`（email/password → `data.access_token`，用于 `/v1/parameters` 等）

> **中台需同时模拟两套鉴权**：云智（JWT + Api-Key）与原始 Dify（Bearer apiKey）。

## 2. 云智封装接口（baseUrl 例：`.../kdsmart/prod-api`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/oauth2/token` | 取 token |
| POST | `/api/transfer/one/chat-messages` | 对话（SSE 流式） |
| GET | `/api/transfer/one/chat-messages/conversations` | 会话列表 |
| POST | `/api/transfer/one/chat-messages/conversations/rename` | 会话重命名 |
| GET | `/api/transfer/one/chat-messages/messages` | 历史消息 |
| POST | `/api/transfer/one/chat-messages/feedback` | 消息反馈 |
| GET | `/api/transfer/one/chat-messages/suggested` | 下一轮建议 |
| POST | `/api/transfer/one/chat-messages/stop` | 停止响应 |
| POST | `/api/transfer/one/files/upload` | 文件上传 |
| POST | `/api/open/dify/difyApp` | 应用列表 |
| POST | `/api/open/dify/getDifyAppInfo` | 应用详情 |
| POST | `/api/open/dify/listConversationDirect` | 会话（直读库，分页 `data.records`） |
| POST | `/api/open/dify/listConversationMessageDirect` | 消息（直读库） |
| POST | `/api/open/dify/listConversationMessageFeedbacksDirect` | 反馈（直读库） |
| POST | `/api/open/dify/listDifyEndUser` | 终端用户（直读库） |
| POST | `/api/open/dify/runWorkflow` | 工作流执行（**嵌套 Envelope**，见下） |
| GET | `/api/open/dify/parameters` | 应用参数（开场白/建议问题） |

## 3. 原始 Dify 接口（`DifyConfig.baseUrl`）
- `POST /v1/chat-messages`（SSE）
- `POST /v1/messages/{message_id}/feedbacks`
- `GET /v1/messages/{message_id}/suggested`
- `POST /v1/conversations/{conversation_id}/name`（重命名，body `{auto_generate, user}`）
- `GET /v1/conversations`（`user`/`last_id`/`limit`，返回 `data` + `has_more`）
- `GET /v1/messages`（`user`/`conversation_id`/`first_id`/`limit`，返回 `data` + `has_more`）
- `GET /v1/parameters`
- `POST /v1/files/upload`（form：`user` + `file`）
- `POST /v1/workflows/run`（body `{inputs, response_mode, user}`）

## 4. 关键响应 Envelope（兼容必须一致）

- **会话/消息列表（原始 Dify）**：`{ data: [...], has_more: bool }`；消息字段过滤为
  `id / conversation_id / query / answer / created_at / metadata.retriever_resources[{position,dataset_id,document_name,content}]`。
- **云智直读库列表**：`data.records`（分页），`id` 映射为 `thirdId`。
- **runWorkflow（云智）**：`result.code==200` → `data.data.data.{status, outputs, error}`；
  `status ∈ {succeeded, partial-succeeded}` 才算成功；返回 `outputs`。
- **getCloudParameters（云智）**：`{ code: 200, data: { data: { opening_statement, suggested_questions[] } } }`。

## 5. SSE 事件契约（前端解析器依赖）

- `event` 取值：`message`、`message_end`、`agent_message`、`error`（Java 侧按 `event.contains("message")` 过滤转发）。
- 字段：`answer`、`conversation_id`、`message_id`、`metadata`。
- `message_end.metadata.retriever_resources[]`：裁剪为 `{content, document_name}`（`DifyUtil.trimMessageEndMetadata` 会移除 `usage`）。
- 标题标记：`LogTitleMarker` 会对 `answer` 做流式过滤（`applyLogTitleFilter`）；
  原始 Dify 列表查询时 `LogTitleMarker.strip` 去标记。
- `error` 事件：`{event:"error", message}`（Java 记录 isSuccess/errorType）。

## 6. 模型网关（云智「通用大模型调用器」）

- 通过 `runWorkflow`（appId = `generic_llm_app_id`）调用。
- inputs：`llm_name`、`system_prompt`、`user_prompt`；
- outputs：`status`、`answer`、`llm_name`、`resolved_model`、`error_code`、`error_message`。
- 成功 ⟺ `status == "success"` 且 `error_code` 为空。

## 7. 现有应用表（迁移来源）

- `ai_monitor_app` / `xb_ai_monitor_app`：字段含
  `id, uuid, app_id, app_name, app_info, dify_app_type, app_type, tag, api_key, is_deleted,
   create_user_id/name, update_user_id/name, create_time, update_time, is_jump, label_type,
   agent_item_id, agent_item_uuid, order_id, agent_picurl`。
- 中台注册表以 `app_id` + `api_key` 为对外标识，迁移脚本从上述表导入。
