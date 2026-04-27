from __future__ import annotations

import base64
import json
import uuid
from typing import Any, Dict, Iterator, List, Optional, Union

import requests

from ._challenge import make_fe_signals, solve_challenge
from ._exceptions import APIError, ConversationLimitError, DuckChatError, RateLimitError
from ._models import (
    Content,
    History,
    ImagePart,
    Message,
    ModelType,
    Role,
    image_generation,
    model_supports_reasoning,
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


class DuckChat:
    def __init__(
        self,
        model: Union[ModelType, str] = "gpt4",
        *,
        effort: Optional[str] = None,
        user_agent: Optional[str] = None,
        fe_version: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: float = 60.0,
    ):
        self.model = resolve_model(model)
        self.effort = effort
        self.user_agent = user_agent or _DEFAULT_UA
        self.fe_version = fe_version or _DEFAULT_FE_VERSION
        self.timeout = timeout
        self.history = History(model=self.model)
        self._jwk: Optional[Dict[str, Any]] = None
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{_BASE}/",
                "Origin": _BASE,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }
        )

    def __enter__(self) -> "DuckChat":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    def reset(self) -> None:
        self.history.clear()

    def _fetch_challenge_header(self) -> str:
        r = self._session.get(
            f"{_BASE}/duckchat/v1/status",
            headers={
                "Accept": "*/*",
                "x-vqd-accept": "1",
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "Referer": f"{_BASE}/",
                "Origin": _BASE,
            },
            timeout=self.timeout,
        )
        if r.status_code == 429:
            raise RateLimitError(r.text)
        if r.status_code >= 400:
            raise APIError(f"status endpoint failed: {r.status_code}", r.status_code, r.text)
        challenge = r.headers.get("x-vqd-hash-1")
        if not challenge:
            raise DuckChatError("server did not return x-vqd-hash-1 challenge")
        return solve_challenge(challenge, self.user_agent)

    def _get_jwk(self) -> Dict[str, Any]:
        if self._jwk is None:
            from ._durable import generate_jwk as _gen
            self._jwk = _gen()
        return self._jwk

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

    @staticmethod
    def _has_image(messages: List[Dict[str, Any]]) -> bool:
        for m in messages:
            c = m.get("content")
            if isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "image":
                        return True
        return False

    def _post_chat(self, payload: Dict[str, Any], *, stream: bool = True) -> requests.Response:
        hash_header = self._fetch_challenge_header()
        resp = self._session.post(
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
            stream=stream,
            timeout=self.timeout,
        )
        if resp.status_code == 200:
            return resp
        body = ""
        try:
            body = resp.text
        except Exception:
            pass
        if resp.status_code == 429:
            if "ERR_CONVERSATION_LIMIT" in body:
                raise ConversationLimitError(body)
            raise RateLimitError(body)
        raise APIError(f"chat failed: HTTP {resp.status_code}", resp.status_code, body)

    @staticmethod
    def _iter_sse(resp: requests.Response) -> Iterator[str]:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if not raw.startswith("data:"):
                continue
            data = raw[5:].lstrip()
            if not data:
                continue
            yield data

    def stream(
        self,
        prompt: Union[str, List[Union[str, ImagePart, dict]]],
        *,
        remember: bool = True,
        model: Optional[Union[ModelType, str]] = None,
        effort: Optional[str] = None,
    ) -> Iterator[str]:
        if remember:
            self.history.add_user(prompt)
            messages = self.history.to_messages()
        else:
            messages = [Message(role=Role.User.value, content=prompt).to_dict()]
        is_mm = self._has_image(messages)
        use_model = resolve_model(model) if model else (_VISION_MODEL if is_mm else self.model)
        payload = self._build_payload(messages, model=use_model, effort=effort)
        collected: List[str] = []
        with self._post_chat(payload, stream=True) as resp:
            for data in self._iter_sse(resp):
                if data == "[DONE]":
                    break
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
                chunk = obj.get("message") or ""
                if chunk:
                    collected.append(chunk)
                    yield chunk
        if remember and collected:
            self.history.add_assistant("".join(collected))

    def ask(
        self,
        prompt: Union[str, List[Union[str, ImagePart, dict]]],
        *,
        remember: bool = True,
        model: Optional[Union[ModelType, str]] = None,
        effort: Optional[str] = None,
    ) -> str:
        return "".join(self.stream(prompt, remember=remember, model=model, effort=effort))

    def ask_with_image(
        self,
        prompt: str,
        image: Union[str, bytes, ImagePart],
        *,
        mime_type: str = "image/png",
        remember: bool = True,
        model: Optional[Union[ModelType, str]] = None,
        effort: Optional[str] = None,
    ) -> str:
        part = self._coerce_image(image, mime_type)
        return self.ask([prompt, part], remember=remember, model=model or _VISION_MODEL, effort=effort)

    @staticmethod
    def _coerce_image(image: Union[str, bytes, ImagePart], mime_type: str) -> ImagePart:
        if isinstance(image, ImagePart):
            return image
        if isinstance(image, bytes):
            return ImagePart.from_bytes(image, mime_type=mime_type)
        if isinstance(image, str):
            if image.startswith("data:"):
                return ImagePart(image=image, mime_type=mime_type)
            return ImagePart.from_path(image)
        raise TypeError(f"unsupported image type: {type(image).__name__}")

    def generate_image(
        self,
        prompt: str,
        *,
        save_to: Optional[str] = None,
    ) -> bytes:
        messages = [Message(role=Role.User.value, content=prompt).to_dict()]
        payload = self._build_payload(messages, model=image_generation, can_use_tools=False)
        partials: List[str] = []
        final: Optional[str] = None
        with self._post_chat(payload, stream=True) as resp:
            for data in self._iter_sse(resp):
                if data == "[DONE]":
                    break
                if data.startswith("[CHAT_TITLE") or data.startswith("[LIMIT") or data.startswith("[PING"):
                    continue
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                if obj.get("action") == "error":
                    msg = obj.get("type") or obj.get("error") or json.dumps(obj)
                    if obj.get("status") == 429:
                        raise RateLimitError(msg)
                    raise APIError(str(msg), obj.get("status"), data)
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
