FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 依赖层：只靠 pyproject.toml + 空包/空 README 占位安装。
# README 也放这层之外，改文档不会让依赖层失效。
COPY pyproject.toml ./
RUN mkdir -p src/agent_platform && touch src/agent_platform/__init__.py README.md \
    && pip install --no-cache-dir --retries 5 --timeout 60 .

# 业务代码层：只重装本包（--no-deps 不再触碰网络依赖）
COPY src ./src
COPY README.md ./
RUN pip install --no-cache-dir --no-deps .

# 本地 SQLite 数据目录（compose 下由命名卷挂载于此）
RUN mkdir -p /app/data

EXPOSE 8900

CMD ["uvicorn", "agent_platform.api.main:app", "--host", "0.0.0.0", "--port", "8900"]
