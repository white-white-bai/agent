import copy
import os
import pathlib
import tempfile
import uuid

_db_file = pathlib.Path(tempfile.gettempdir()) / "agent_platform_test.sqlite"
if _db_file.exists():
    _db_file.unlink()
os.environ["AP_ENV"] = "test"
os.environ["AP_DB_DSN"] = f"sqlite+pysqlite:///{_db_file}"

import pytest
from fastapi.testclient import TestClient

from agent_platform.api.main import app, get_engine_context
from agent_platform.core import db as dbmod
from agent_platform.core import redis as redismod
from agent_platform.core.config import get_settings
from agent_platform.core.db import Base, session_scope
from agent_platform.domain.models import App, Graph, GraphVersion
from agent_platform.engine.context import EngineContext
from agent_platform.graph.schema import GraphDef

get_settings.cache_clear()
dbmod.reset_state()

GRAPH_DEF = GraphDef.model_validate(
    {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "llm", "type": "llm", "config": {"user_prompt": "{{ query }}", "output_var": "text"}},
            {"id": "answer", "type": "answer", "config": {"template": "{{ text }}"}},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"source": "start", "target": "llm"},
            {"source": "llm", "target": "answer"},
            {"source": "answer", "target": "end"},
        ],
    }
).model_dump(mode="json")


@pytest.fixture(autouse=True)
def _fresh_db():
    dbmod.reset_state()
    redismod.reset_state()
    Base.metadata.drop_all(dbmod.get_engine())
    dbmod.init_db()
    yield
    dbmod.reset_state()
    redismod.reset_state()


class FakeLLM:
    async def __call__(self, *, provider, model, system_prompt, user_prompt, temperature, max_tokens):
        return f"echo:{user_prompt}"


@pytest.fixture()
def engine_ctx() -> EngineContext:
    return EngineContext(llm=FakeLLM())


@pytest.fixture()
def graph_def() -> dict:
    return copy.deepcopy(GRAPH_DEF)


@pytest.fixture()
def seed_app():
    """建应用（默认附一份已发布图定义），返回 (app_uuid, api_key)。"""

    def _seed(
        *,
        tenant_code: str = "t",
        app_id: str = "app-1",
        api_key: str = "key-1",
        app_name: str = "demo",
        published: bool = True,
        definition: dict | None = None,
    ) -> tuple[str, str]:
        with session_scope() as session:
            row = App(
                uuid=uuid.uuid4().hex,
                tenant_code=tenant_code,
                app_id=app_id,
                api_key=api_key,
                app_name=app_name,
            )
            session.add(row)
            session.flush()
            graph = Graph(uuid=uuid.uuid4().hex, tenant_code=tenant_code, app_uuid=row.uuid, status="draft")
            session.add(graph)
            session.flush()
            if published:
                version = GraphVersion(
                    uuid=uuid.uuid4().hex,
                    graph_uuid=graph.uuid,
                    version=1,
                    definition=definition or GRAPH_DEF,
                )
                session.add(version)
                session.flush()
                graph.status = "published"
                graph.published_version_id = version.id
            return row.uuid, row.api_key

    return _seed


@pytest.fixture()
def api_client(engine_ctx):
    app.dependency_overrides[get_engine_context] = lambda: engine_ctx
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
