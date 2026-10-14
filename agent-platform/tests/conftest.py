import os
import pathlib
import tempfile

_db_file = pathlib.Path(tempfile.gettempdir()) / "agent_platform_test.sqlite"
if _db_file.exists():
    _db_file.unlink()
os.environ["AP_ENV"] = "test"
os.environ["AP_DB_DSN"] = f"sqlite+pysqlite:///{_db_file}"

import pytest

from agent_platform.core import db as dbmod
from agent_platform.core.config import get_settings
from agent_platform.core.db import Base
from agent_platform.engine.context import EngineContext

get_settings.cache_clear()
dbmod.reset_state()


@pytest.fixture(autouse=True)
def _fresh_db():
    dbmod.reset_state()
    Base.metadata.drop_all(dbmod.get_engine())
    dbmod.init_db()
    yield
    dbmod.reset_state()


class FakeLLM:
    async def __call__(self, *, provider, model, system_prompt, user_prompt, temperature, max_tokens):
        return f"echo:{user_prompt}"


@pytest.fixture
def engine_ctx() -> EngineContext:
    return EngineContext(llm=FakeLLM())
