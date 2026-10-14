from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AP_", env_file=".env", extra="ignore")

    env: str = "dev"
    http_port: int = 8900

    db_dsn: str = "sqlite+pysqlite:///:memory:"
    redis_url: str = "redis://localhost:6379/0"

    default_tenant: str = "changzhou"

    cloud_gateway_base_url: str = ""
    cloud_gateway_client_id: str = ""
    cloud_gateway_client_secret: str = ""
    cloud_gateway_llm_app_id: str = ""

    openai_base_url: str = ""
    openai_api_key: str = ""

    light_rag_base_url: str = ""
    light_rag_api_key: str = ""
    knowflow_base_url: str = ""
    knowledge_graph_base_url: str = ""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    sm4_key: str = ""
    sm4_iv: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
