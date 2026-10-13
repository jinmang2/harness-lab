"""One model factory, so every harness (and DeepSeek Harness) runs the same model.

Default: DeepSeek through `langchain-deepseek`, configured to match DeepSeek Harness's
own adapter (thinking mode on, streaming with usage). `LAB_MODEL_SPEC` swaps in any
`init_chat_model` spec for the lab engine only.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class ChatDeepSeekThinking(ChatDeepSeek):
    """ChatDeepSeek that sends `reasoning_content` back on assistant turns.

    DeepSeek thinking mode requires the previous assistant `reasoning_content` on
    tool-call turns. `ChatDeepSeek` stores it in `additional_kwargs` when reading a
    response but drops it when building the next request, so restore it here.
    DeepSeek Harness does the same in its own adapter.
    """

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        originals = [m for m in self._convert_input(input_).to_messages() if isinstance(m, AIMessage)]
        wires = [m for m in payload["messages"] if m.get("role") == "assistant"]
        for wire, original in zip(wires, originals, strict=False):
            reasoning = original.additional_kwargs.get("reasoning_content")
            if reasoning is not None:
                wire["reasoning_content"] = reasoning
        return payload


# DeepSeek Harness's built-in catalog (packages/llm/llm-deepseek): id, display name, context window.
MODELS = [
    {"id": "deepseek-flash", "name": "DeepSeek-V41-Flash", "context": 1_000_000},
    {"id": "deepseek-v4-flash", "name": "DeepSeek-V4-Flash", "context": 1_000_000},
    {"id": "deepseek-v4-pro", "name": "DeepSeek-V4-Pro", "context": 1_000_000},
]
CATALOG = [m["id"] for m in MODELS]
EFFORTS = ["off", "low", "high", "max"]  # "off" = thinking disabled, as in DeepSeek Harness


def model_name(model: str | None = None) -> str:
    return model or os.environ.get("LAB_MODEL_SPEC") or os.environ.get("LAB_MODEL") or DEFAULT_MODEL


def make_model(model: str | None = None, effort: str | None = None) -> BaseChatModel:
    """`model` / `effort` override LAB_MODEL / LAB_THINKING + LAB_REASONING_EFFORT for one session."""
    spec = None if model else os.environ.get("LAB_MODEL_SPEC")
    if spec:
        from langchain.chat_models import init_chat_model

        return init_chat_model(spec, streaming=True)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set (put it in .env, or use `lab gateway --mode mock`).")

    if effort:
        thinking = "disabled" if effort == "off" else "enabled"
    else:
        thinking = os.environ.get("LAB_THINKING", "enabled")
        effort = os.environ.get("LAB_REASONING_EFFORT", "high")
    extra_body: dict[str, Any] = {"thinking": {"type": thinking}}
    if thinking == "enabled":
        extra_body["reasoning_effort"] = effort

    return ChatDeepSeekThinking(
        model=model or os.environ.get("LAB_MODEL", DEFAULT_MODEL),
        api_key=api_key,
        api_base=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        streaming=True,
        stream_usage=True,
        extra_body=extra_body,
        max_retries=2,
    )
