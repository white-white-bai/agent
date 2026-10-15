# agent-platform-ui

agent 中台的独立管理端。Vue 3 + Vite + Element Plus + Pinia + vue-router，图编排使用 AntV X6。

后端为 `../agent-platform`（FastAPI），管理端沿用 Java 侧既有的 `/admin` 协议，前端只做协议消费，不引入新契约。

## 页面

| 路由 | 视图 | 说明 |
| --- | --- | --- |
| `/login` | `LoginView` | 登录，支持 `?redirect=` 回跳 |
| `/apps` | `AppsView` | agent 应用注册（列表 / 新增 / 编辑 / 删除） |
| `/apps/:appUuid/graph` | `GraphEditorView` | 图编辑器（AntV X6）、草稿保存、发布、版本回滚、Dify DSL 导入、运行（整图流式 SSE + 单节点运行） |
| `/providers` | `ProvidersView` | 大模型 / 检索 / 向量 / 观测 provider 配置 |
| `/mcp` | `McpServersView` | 工具（MCP server）配置 |
| `/knowledge` | `KnowledgeView` | 知识库文档 |
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
