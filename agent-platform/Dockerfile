FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 依赖层：只靠 pyproject.toml + 一个空包占位安装，改源码不会让这一层失效
COPY pyproject.toml README.md ./
RUN mkdir -p src/agent_platform && touch src/agent_platform/__init__.py \
    && pip install --no-cache-dir --retries 5 --timeout 60 .

# 业务代码层：只重装本包（--no-deps 不再触碰网络依赖）
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

# 本地 SQLite 数据目录（compose 下由命名卷挂载于此）
RUN mkdir -p /app/data

EXPOSE 8900

CMD ["uvicorn", "agent_platform.api.main:app", "--host", "0.0.0.0", "--port", "8900"]
