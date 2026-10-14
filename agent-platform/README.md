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
│   └── api/                 # FastAPI + 兼容接口
└── tests/
```

## 本地运行

```bash
cd agent-platform
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env
pytest
uvicorn agent_platform.api.main:app --reload --port 8900
```
