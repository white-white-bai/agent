"""文本向量化：默认离线确定性哈希嵌入，可切换 OpenAI 兼容 embedding 接口。"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import httpx

from agent_platform.core.config import Settings

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    lowered = (text or "").lower()
    tokens = _TOKEN_RE.findall(lowered)
    for chunk in _TOKEN_RE.findall(lowered.replace(" ", "")):
        if len(chunk) > 1:
            tokens.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
    return tokens


def hash_embed(text: str, dim: int = 256) -> list[float]:
    vector = [0.0] * dim
    for token in _tokenize(text):
        digest = hashlib.md5(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class Embedder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    async def encode(self, text: str) -> list[float]:
        settings = self.settings
        if settings is not None and settings.embedding_base_url:
            return await self._remote(text, settings)
        dim = settings.embedding_dim if settings is not None else 256
        return hash_embed(text, dim)

    async def _remote(self, text: str, settings: Settings) -> list[float]:
        headers = {"Authorization": f"Bearer {settings.embedding_api_key}"} if settings.embedding_api_key else {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{settings.embedding_base_url.rstrip('/')}/embeddings",
                json={"model": settings.embedding_model or "text-embedding-ada-002", "input": text},
                headers=headers,
            )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        return payload["data"][0]["embedding"]
