from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from ._challenge import make_fe_signals, solve_challenge
from ._exceptions import APIError, ConversationLimitError, DuckChatError, RateLimitError
from ._models import (
    History,
    ImagePart,
    Message,
    ModelType,
    Role,
    image_generation,
    resolve_effort,
    resolve_model,
)

_BASE = "https://duck.ai"
_DEFAULT_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mozilla/5 Mobile/15E148 Version/15.0"
)
_DEFAULT_FE_VERSION = "serp_20260424_180649_ET-0bdc33b2a02ebf8f235def65d887787f694720a1"
_TOOL_CHOICE_OFF = {
    "NewsSearch": False,
    "VideosSearch": False,
    "LocalSearch": False,
    "WeatherForecast": False,
}
_VISION_MODEL = "gpt-5-mini"


class AsyncDuckChat:
    def __init__(
        self,
        model: Union[ModelType, str] = "gpt4",
        *,
        effort: Optional[str] = None,
        user_agent: Optional[str] = None,
        fe_version: Optional[str] = None,
        session: Optional["aiohttp.ClientSession"] = None,
        timeout: float = 60.0,
    ):
        try:
            import aiohttp  # noqa: F401
        except Exception as e:
            raise ImportError(
                "AsyncDuckChat requires aiohttp. Install with: pip install p2d-duck[async]"
            ) from e
        self.model = resolve_model(model)
        self.effort = effort
        self.user_agent = user_agent or _DEFAULT_UA
        self.fe_version = fe_version or _DEFAULT_FE_VERSION
        self.timeout = timeout
        self.history = History(model=self.model)
        self._session = session
        self._owns_session = session is None
        self._jwk: Optional[Dict[str, Any]] = None

    async def __aenter__(self) -> "AsyncDuckChat":
        await self._ensure_session()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    def reset(self) -> None:
        self.history.clear()

    async def _ensure_session(self):
        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                },
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )

    def _get_jwk(self) -> Dict[str, Any]:
        if self._jwk is None:
            from ._durable import generate_jwk as _gen
            self._jwk = _gen()
        return self._jwk

    async def _fetch_challenge_header(self) -> str:
        await self._ensure_session()
        async with self._session.get(
            f"{_BASE}/duckchat/v1/status",
            headers={
                "Accept": "*/*",
                "x-vqd-accept": "1",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referer": f"{_BASE}/",
                "Origin": _BASE,
            },
        ) as r:
            if r.status == 429:
                raise RateLimitError(await r.text())
            if r.status >= 400:
                raise APIError(
                    f"status endpoint failed: {r.status}", r.status, await r.text()
                )
            challenge = r.headers.get("x-vqd-hash-1")
            if not challenge:
                raise DuckChatError("server did not return x-vqd-hash-1 challenge")
            return await asyncio.to_thread(solve_challenge, challenge, self.user_agent)

    @staticmethod
    def _has_image(messages: List[Dict[str, Any]]) -> bool:
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "image":
                        return True
        return False

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        can_use_tools: bool = True,
        effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        m = resolve_model(model or self.model)
        payload: Dict[str, Any] = {
            "model": m,
            "metadata": {"toolChoice": dict(_TOOL_CHOICE_OFF)},
            "messages": messages,
            "canUseTools": can_use_tools,
        }
        eff = resolve_effort(m, effort if effort is not None else self.effort)
        if eff is not None:
            payload["reasoningEffort"] = eff
        payload["canUseApproxLocation"] = None
        payload["durableStream"] = {
            "messageId": str(uuid.uuid4()),
            "conversationId": str(uuid.uuid4()),
            "publicKey": self._get_jwk(),
        }
        return payload

    async def _stream_events(self, payload: Dict[str, Any]) -> AsyncIterator[dict]:
        await self._ensure_session()
        hash_header = await self._fetch_challenge_header()
        resp = await self._session.post(
            f"{_BASE}/duckchat/v1/chat",
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "x-vqd-hash-1": hash_header,
                "x-fe-signals": make_fe_signals(),
                "x-fe-version": self.fe_version,
                "Referer": f"{_BASE}/",
                "Origin": _BASE,
            },
        )
        async with resp:
            if resp.status == 200:
                async for raw_bytes in resp.content:
                    line = raw_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].lstrip()
                    if not data or data == "[DONE]":
                        return
                    if data.startswith("[CHAT_TITLE") or data.startswith("[LIMIT") or data.startswith("[PING"):
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    if obj.get("action") == "error":
                        msg = obj.get("type") or obj.get("error") or json.dumps(obj)
                        if obj.get("status") == 429:
                            if msg == "ERR_CONVERSATION_LIMIT":
                                raise ConversationLimitError(msg)
                            raise RateLimitError(msg)
                        raise APIError(str(msg), obj.get("status"), data)
                    yield obj
                return
            body = await resp.text()
            if resp.status == 429:
                if "ERR_CONVERSATION_LIMIT" in body:
                    raise ConversationLimitError(body)
                raise RateLimitError(body)
            raise APIError(f"chat failed: HTTP {resp.status}", resp.status, body)

    async def stream(
        self,
        prompt: Union[str, List[Union[str, ImagePart, dict]]],
        *,
        remember: bool = True,
        model: Optional[Union[ModelType, str]] = None,
        effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        if remember:
            self.history.add_user(prompt)
            messages = self.history.to_messages()
        else:
            messages = [Message(role=Role.User.value, content=prompt).to_dict()]
        is_mm = self._has_image(messages)
        use_model = resolve_model(model) if model else (_VISION_MODEL if is_mm else self.model)
        payload = self._build_payload(messages, model=use_model, effort=effort)
        collected: List[str] = []
        async for obj in self._stream_events(payload):
            chunk = obj.get("message") or ""
            if chunk:
                collected.append(chunk)
                yield chunk
        if remember and collected:
            self.history.add_assistant("".join(collected))

    async def ask(
        self,
        prompt: Union[str, List[Union[str, ImagePart, dict]]],
        *,
        remember: bool = True,
        model: Optional[Union[ModelType, str]] = None,
        effort: Optional[str] = None,
    ) -> str:
        out: List[str] = []
        async for chunk in self.stream(prompt, remember=remember, model=model, effort=effort):
            out.append(chunk)
        return "".join(out)

    async def ask_with_image(
        self,
        prompt: str,
        image: Union[str, bytes, ImagePart],
        *,
        mime_type: str = "image/png",
        remember: bool = True,
        model: Optional[Union[ModelType, str]] = None,
        effort: Optional[str] = None,
    ) -> str:
        from ._client import DuckChat as _Sync

        part = _Sync._coerce_image(image, mime_type)
        return await self.ask(
            [prompt, part], remember=remember, model=model or _VISION_MODEL, effort=effort
        )

    async def generate_image(
        self,
        prompt: str,
        *,
        save_to: Optional[str] = None,
    ) -> bytes:
        messages = [Message(role=Role.User.value, content=prompt).to_dict()]
        payload = self._build_payload(messages, model=image_generation, can_use_tools=False)
        partials: List[str] = []
        final: Optional[str] = None
        async for obj in self._stream_events(payload):
            role = obj.get("role") or ""
            result = obj.get("result") or ""
            if role == "partial-image" and result:
                partials.append(result)
            elif role in ("generated-image", "image") and result:
                final = result
        b64 = final if final else "".join(partials)
        if not b64:
            raise DuckChatError("image generation returned no data")
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        data = base64.b64decode(b64)
        if save_to:
            with open(save_to, "wb") as f:
                f.write(data)
        return data
