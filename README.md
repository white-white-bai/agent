# agent 中台

用 LangChain / LangGraph 自建编排引擎，替换现有 `gov-service-ai-assistant` 的 Dify 编排能力。

本仓库只含中台自身，两个平级工程：

| 目录 | 内容 | 端口 |
|---|---|---|
| `agent-platform/` | Python 服务（FastAPI + LangGraph），引擎、兼容接口、管理端 API | 8900 |
| `agent-platform-ui/` | 独立管理前端（Vue 3 + Element Plus + AntV X6） | 5199 |

PRD 里提到的 `backend/`、`frontend/` 属于外部仓库 `gov-service-ai-assistant`，**不在本仓库内**。
设计前提是「不改动 Java 后端与前端源码、只改 base-url」，因此对外协议（SSE 事件序列、Envelope 形状）是硬约束。

- 需求与逐条决策（唯一权威来源）：`.trellis/tasks/10-14-agent-platform/prd.md`
- 兼容契约：`.trellis/tasks/10-14-agent-platform/research/dify-cloud-contract.md`
- 各工程细节见 `agent-platform/README.md`、`agent-platform-ui/README.md`

## 启动

需要 Python ≥ 3.10、Node ≥ 18。**先起后端，再起前端**（前端 dev server 会把接口代理到后端，顺序反了接口报 502）。

### 1. 后端（8900）

```bash
cd agent-platform
python -m venv .venv && . .venv/Scripts/activate   # Windows；Linux/macOS 用 .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m uvicorn agent_platform.api.main:app --reload --host 127.0.0.1 --port 8900
```

`.env.example` 的 `AP_DB_DSN` / `AP_REDIS_URL` 默认指向内网 MySQL/Redis。不想接外部依赖、只跑本地演示时，把 DSN 改成文件库即可，建表由启动时的 `init_db()` 完成，`sql/ddl.sql` 无需手工执行：

```bash
# .env
AP_ENV=dev
AP_HTTP_PORT=8900
AP_DB_DSN=sqlite+pysqlite:///./.run/agent_platform.db
AP_DEFAULT_TENANT=changzhou
```

```bash
curl -s http://127.0.0.1:8900/healthz                        # {"status":"ok"}
```

### 2. 前端（5199）

```bash
cd agent-platform-ui
npm install --registry=https://registry.npmmirror.com
npm run dev
```

浏览器打开 **`http://localhost:5199`** —— Vite 默认只监听 `localhost`（IPv6 `::1`），`127.0.0.1:5199` 连不上。

代理目标由 `AP_UI_PROXY_TARGET` 控制（默认 `http://127.0.0.1:8900`），走 Vite 代理转发 `/admin`、`/v1`、`/api`、`/healthz`。

## 登录

`AP_ADMIN_AUTH_ENABLED=false`（默认）时 `/admin` 免鉴权，直接进即可。置 `true` 后需要登录，
种子账号由 `AP_ADMIN_SEED_USERNAME` / `AP_ADMIN_SEED_PASSWORD` 配置，默认 `admin` / `admin123`，**上线前必须改掉**。

## 测试

```bash
cd agent-platform && pytest && python -m ruff check .        # 后端：临时 SQLite + mock，不依赖 MySQL/Redis
cd agent-platform-ui && npm test && npm run lint             # 前端：vitest + eslint
```

## 其它入口

```bash
cd agent-platform
python -m agent_platform.worker.main                  # 异步任务 worker（Redis 队列，不可用时降级进程内）
python scripts/smoke_e2e.py                           # 内网冒烟：连真 MySQL / 云智网关 / 真实模型
python -m agent_platform.importer app.yml -o graph.json   # Dify DSL → 中台图定义
```

`docker-compose.yml`（API + worker + Langfuse）在 `agent-platform/` 下。
