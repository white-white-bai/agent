FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# 本地 SQLite 数据目录（compose 下由命名卷挂载于此）
RUN mkdir -p /app/data

EXPOSE 8900

CMD ["uvicorn", "agent_platform.api.main:app", "--host", "0.0.0.0", "--port", "8900"]
