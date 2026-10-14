"""云智「通用大模型调用器」网关适配为 LangChain ChatModel。

契约见 .trellis/tasks/10-14-agent-platform/research/dify-cloud-contract.md 第 6 节：
inputs: llm_name / system_prompt / user_prompt；outputs: status / answer / resolved_model ...
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def get_access_token(base_url: str, client_id: str, client_secret: str, timeout: float = 10.0) -> str:
    key = f"{base_url}|{client_id}"
    cached = _TOKEN_CACHE.get(key)
    if cached and cached[1] > time.time():
        return cached[0]

    response = httpx.post(
        f"{base_url.rstrip('/')}/api/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"云智取 token 失败: {payload}")
    data = payload["data"]
    expires_seconds = float(data.get("expire") or 3600)
    _TOKEN_CACHE[key] = (data["token"], time.time() + max(expires_seconds - 60, 30))
    return data["token"]


def run_generic_llm(
    base_url: str,
    access_token: str,
    llm_app_id: str,
    llm_name: str,
    system_prompt: str,
    user_prompt: str,
    user: str = "agent-platform",
    timeout: float = 120.0,
) -> dict[str, Any]:
    response = httpx.post(
        f"{base_url.rstrip('/')}/api/open/dify/runWorkflow",
        headers={"Authorization": f"JWT {access_token}"},
        json={
            "appId": llm_app_id,
            "inputs": {"llm_name": llm_name, "system_prompt": system_prompt or "", "user_prompt": user_prompt},
            "response_mode": "blocking",
            "user": user,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"云智模型网关调用失败: {payload.get('msg')}")
    return payload["data"]["data"]["data"].get("outputs", {})


def _split_messages(messages: list[BaseMessage]) -> tuple[str, str]:
    system_parts: list[str] = []
    user_parts: list[str] = []
    for message in messages:
        content = message.content if isinstance(message.content, str) else str(message.content)
        if message.type == "system":
            system_parts.append(content)
        else:
            user_parts.append(content)
    return "\n".join(system_parts), "\n".join(user_parts)


class CloudGatewayChatModel(BaseChatModel):
    model_name: str = ""
    base_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    llm_app_id: str = ""
    user: str = "agent-platform"

    @property
    def _llm_type(self) -> str:
        return "cloud-gateway"

    def _call_gateway(self, messages: list[BaseMessage]) -> str:
        system_prompt, user_prompt = _split_messages(messages)
        token = get_access_token(self.base_url, self.client_id, self.client_secret)
        outputs = run_generic_llm(
            self.base_url, token, self.llm_app_id, self.model_name, system_prompt, user_prompt, self.user
        )
        return outputs.get("answer", "") or ""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = self._call_gateway(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text = self._call_gateway(messages)
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
        if run_manager:
            run_manager.on_llm_new_token(text, chunk=chunk)
        yield chunk
