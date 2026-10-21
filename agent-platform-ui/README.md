# agent-platform-ui

agent 中台的独立管理端。Vue 3 + Vite + Element Plus + Pinia + vue-router，图编排使用 AntV X6。

后端为 `../agent-platform`（FastAPI），管理端沿用 Java 侧既有的 `/admin` 协议，前端只做协议消费，不引入新契约。

## 页面

| 路由 | 视图 | 说明 |
| --- | --- | --- |
| `/login` | `LoginView` | 登录，支持 `?redirect=` 回跳 |
| `/apps` | `AppsView` | agent 应用注册（列表 / 新增 / 编辑 / 删除）；行操作按应用类型进入图编排或 Agent 配置 |
| `/apps/:appUuid/graph` | `GraphEditorView` | 图编辑器（AntV X6）、草稿保存、发布、版本回滚、Dify DSL 导入、运行（整图流式 SSE + 单节点运行 + HITL 审批/恢复） |
| `/apps/:appUuid/agent` | `AgentConfigView` | 真自主 Agent 配置（指令/模型/工具/知识/记忆/规划/反思/子 agent/HITL）+ 调试对话台（流式 token、工具与规划事件、HITL 批准/拒绝） |
| `/providers` | `ProvidersView` | 大模型 / 检索 / 向量 / 观测 provider 配置（含检索流水线只读回显） |
| `/agents` | `AgentsView` | 智能体定义（角色 / 8 种工作模式 / 工具 / 提示词 / CoT） |
| `/tools` | `ToolsView` | 生产级工具声明（参数 schema / 重试 / 兜底）与试调 |
| `/tool-audits` | `ToolAuditsView` | 工具调用审计：租户/工具/状态筛选，参数、错误与耗时 |
| `/prompts` | `PromptsView` | 少样本提示词模板（system 骨架 + 示例 + CoT 提示） |
| `/mcp` | `McpServersView` | 工具（MCP server）配置 |
| `/knowledge` | `KnowledgeView` | 知识库：创建向导（选数据源→分段与清洗含预览→处理完成）、知识库列表（建/改/删）、文档管理（上传/进度/批量/重传/状态轮询/每文档覆盖分段）、分段查看编辑、召回测试 |
| `/memory` | `MemoryView` | 用户级长期记忆：筛选 / 增删改 / 召回测试 / 按用户清除 / 按当前模型重建向量 / 开关只读回显 |
| `/runs` | `RunsView` | 管理端运行记录：等待审批的 HITL 运行、审批/恢复、取消、审批人/时间、状态筛选 |
| `/hitl-audits` | `HitlAuditsView` | HITL 外部审批审计：类型/租户/thread 筛选，展示 interrupt、决策与时间 |
| `/guards` | `GuardsView` | 护栏总开关、敏感词、配额 / 限流 / 轮次、兜底回复 |
| `/accounts` | `AccountsView` | 账号与角色 |
| `/metrics` | `MetricsView` | 监控看板（会话 / 消息 / 满意度 / Token / 异常趋势） |
| `/403` | `ForbiddenView` | 无权限 |

菜单按 `profile.permissions` 过滤，权限通配符为 `*`（见 `src/stores/auth.js`）。

## 命令

```bash
npm install --registry=https://registry.npmmirror.com   # 公司 nexus 不可达时需显式指定源
npm run dev      # 开发服务器，http://localhost:5199
npm run lint     # eslint（flat config）
npm test         # vitest run
npm run build    # 产物输出到 dist/
```

`npm run dev` 会把 `/admin`、`/v1`、`/api`、`/healthz` 代理到后端，目标地址由 `AP_UI_PROXY_TARGET` 控制，默认 `http://127.0.0.1:8900`。启动前端前需先起后端（见 `../agent-platform/README.md` 的「本地运行」），否则代理接口 502。

也可以走 Docker 一键起（见 `../agent-platform/docker-compose.yml`）：`docker compose up -d --build` 会用本目录的 `Dockerfile` 多阶段构建静态产物，再用 nginx 托管并把 `/admin`、`/v1`、`/api`、`/healthz` 反代到后端容器，浏览器访问 `http://localhost:5199`。

Vite 默认只监听 `localhost`（IPv6 `::1`），浏览器请用 `http://localhost:5199`；`127.0.0.1:5199` 会连不上。

## 目录

```
src/api/          fetch 封装与全部管理接口（client.js 负责 token / 错误归一化与 SSE 流式请求）
src/graph/        nodeMeta.js 节点元数据；mapper.js 图定义 ⇄ X6 cell 的纯函数映射
src/components/   BarChart、GraphCanvas（X6 胶水层）、NodePalette、NodeInspector 及字段编辑器
src/composables/  useTable.js 列表加载 / 错误 / 分页的通用逻辑
src/router/       index.js 路由表；guard.js 鉴权守卫（纯函数，便于单测）
src/utils/        chart.js 图表数据归一；sse.js SSE 分帧解析；run.js 运行对话框纯逻辑
tests/            vitest 用例，纯逻辑与组件挂载各占一半
```

## 测试

纯逻辑模块（mapper、nodeMeta、chart、guard、client、useTable、auth store、utils/sse、utils/run）直接单测；组件用 `@vue/test-utils` 挂载，靠 `vm.$emit` 驱动 Element Plus 的 v-model 与 `@change`，不模拟真实键盘输入。`GraphCanvas.vue` 与 `GraphEditorView.vue` 依赖真实 X6 画布与路由参数，不做挂载测试，其可测逻辑已下沉到 `src/graph/mapper.js`。

拖拽与画布交互仍以手工验证为准。
