from __future__ import annotations

import base64
import json
import logging
import random
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx

from ._challenge import make_fe_signals, solve_challenge
from ._durable import generate_jwk
from .exceptions import (
    APIError,
    ChallengeError,
    ConversationLimitError,
    DuckChatError,
    RateLimitError,
)
from .models import (
    History,
    ImagePart,
    Message,
    ModelType,
    Role,
    image_generation,
    resolve_effort,
    resolve_model,
    vision_capable_default,
)

log = logging.getLogger("duck_ai")

_BASE = "https://duck.ai"
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15"
)
# duck.ai rotates this string. Library users can override via `fe_version=`.
_DEFAULT_FE_VERSION = "serp_20260424_180649_ET-0bdc33b2a02ebf8f235def65d887787f694720a1"
_TOOL_CHOICE_OFF = {
    "NewsSearch": False,
    "VideosSearch": False,
    "LocalSearch": False,
    "WeatherForecast": False,
}

class DuckChat:
    def __init__(
        self,
        model: Union[ModelType, str] = "gpt4",
        *,
        effort: Optional[str] = None,
        user_agent: Optional[str] = None,
        fe_version: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        timeout: float = 60.0,
        max_retries: int = 4,
        backoff_base: float = 0.6,
        warm_session: bool = True,
    ):
        self.model = resolve_model(model)
        self.effort = effort
        self.user_agent = user_agent or _DEFAULT_UA
        self.fe_version = fe_version or _DEFAULT_FE_VERSION
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.backoff_base = max(0.0, float(backoff_base))
        self.history = History(model=self.model)
        self._jwk: Optional[Dict[str, Any]] = None
        self._jwk_lock = threading.Lock()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            http2=False,
            timeout=httpx.Timeout(timeout, connect=15.0, read=timeout),
            headers={
                "User-Agent": self.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{_BASE}/",
                "Origin": _BASE,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
            follow_redirects=True,
        )
        self._warmed = not warm_session
        self._pending_hash: Optional[str] = None
        if warm_session:
            try:
                self._warm()
            except Exception as e:
                # Don't hard-fail if warming fails — the retry layer will
                # cover the cold-start anyway. Just log.
                log.debug("warm-up failed: %s", e)

    # ------------------------------------------------------------------ ctx
    def __enter__(self) -> "DuckChat":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            try:
                self._client.close()
            except Exception:
                pass

    def reset(self) -> None:
        self.history.clear()

    # ----------------------------------------------------------------- warm
    def _warm(self) -> None:
        if self._warmed:
            return
        try:
            self._client.get(
                f"{_BASE}/",
                headers={"Accept": "text/html"},
                timeout=10.0,
            )
        finally:
            self._warmed = True

    # ------------------------------------------------------------ challenge
    def _fetch_challenge_header(self) -> str:
        # Reuse the rotating header captured from the previous chat response;
        # this is exactly how the duck.ai web client behaves and avoids the
        # "first call works, second 418s" trap (and vice versa).
        pending = getattr(self, "_pending_hash", None)
        if pending:
            self._pending_hash = None
            return solve_challenge(pending, self.user_agent)
        r = self._client.get(
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
            raise APIError(
                f"status endpoint failed: {r.status_code}",
                r.status_code,
                r.text,
            )
        challenge = r.headers.get("x-vqd-hash-1")
        if not challenge:
            raise DuckChatError("server did not return x-vqd-hash-1 challenge")
        return solve_challenge(challenge, self.user_agent)

    def _get_jwk(self) -> Dict[str, Any]:
        if self._jwk is None:
            with self._jwk_lock:
                if self._jwk is None:
                    self._jwk = generate_jwk()
        return self._jwk

    # ------------------------------------------------------------- payload
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

    # ----------------------------------------------------- HTTP + SSE iter
    def _chat_stream(self, payload: Dict[str, Any]):
        hash_header = self._fetch_challenge_header()
        return self._client.stream(
            "POST",
            f"{_BASE}/duckchat/v1/chat",
            content=json.dumps(payload),
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

    @staticmethod
    def _raise_for_status(resp: "httpx.Response") -> None:
        try:
            resp.read()
            body = resp.text
        except Exception:
            body = ""
        if resp.status_code == 418:
            raise ChallengeError(f"server rejected challenge: {body[:200]}")
        if resp.status_code == 429:
            if "ERR_CONVERSATION_LIMIT" in body:
                raise ConversationLimitError(body)
            raise RateLimitError(body)
        raise APIError(
            f"chat failed: HTTP {resp.status_code}", resp.status_code, body
        )

    @staticmethod
    def _iter_sse(resp: "httpx.Response") -> Iterator[str]:
        for raw in resp.iter_lines():
            if not raw:
                continue
            if not raw.startswith("data:"):
                continue
            data = raw[5:].lstrip()
            if data:
                yield data

    # ---------------------------------------------------------- retry core
    def _attempt_stream(
        self, payload: Dict[str, Any]
    ) -> Iterator[dict]:
        with self._chat_stream(payload) as resp:
            if resp.status_code != 200:
                self._raise_for_status(resp)
            # Capture the next challenge header for the following request.
            new_hash = resp.headers.get("x-vqd-hash-1")
            if new_hash:
                self._pending_hash = new_hash
            saw_any = False
            for data in self._iter_sse(resp):
                if data == "[DONE]":
                    return
                if (
                    data.startswith("[CHAT_TITLE")
                    or data.startswith("[LIMIT")
                    or data.startswith("[PING")
                ):
                    continue
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                if obj.get("action") == "error":
                    msg = (
                        obj.get("type")
                        or obj.get("error")
                        or json.dumps(obj)
                    )
                    if obj.get("status") == 429:
                        if msg == "ERR_CONVERSATION_LIMIT":
                            raise ConversationLimitError(msg)
                        raise RateLimitError(msg)
                    if msg in ("ERR_CHALLENGE", "ERR_INVALID_CHALLENGE"):
                        raise ChallengeError(str(msg))
                    raise APIError(str(msg), obj.get("status"), data)
                saw_any = True
                yield obj
            if not saw_any:
                # Empty stream — duck.ai sometimes does this when the
                # challenge was accepted but the model rejected the request.
                # Treat as transient.
                raise APIError("empty stream from duck.ai", 200, "")

    def _stream_with_retry(
        self, payload: Dict[str, Any]
    ) -> Iterator[dict]:
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            try:
                yield from self._attempt_stream(payload)
                return
            except (ChallengeError, httpx.RemoteProtocolError, httpx.ReadError) as e:
                last_exc = e  # transient: refresh challenge and retry
            except APIError as e:
                # Retry on 5xx and on the synthetic empty-stream APIError.
                if e.status_code is None or e.status_code >= 500:
                    last_exc = e
                else:
                    raise
            except RateLimitError as e:
                # 429s without conversation-limit semantics may clear if we
                # back off; ConversationLimitError is a subclass of
                # RateLimitError but we already raised it specifically.
                if isinstance(e, ConversationLimitError):
                    raise
                last_exc = e
            except httpx.TimeoutException as e:
                last_exc = e
            # Backoff with jitter before the next attempt.
            if attempt < self.max_retries - 1:
                delay = self.backoff_base * (2**attempt) + random.uniform(0, 0.25)
                log.debug(
                    "duck.ai retry %d/%d after %.2fs",
                    attempt + 2,
                    self.max_retries,
                    delay,
                )
                time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise DuckChatError("exhausted retries with no specific error")

    # ----------------------------------------------------------- public API
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
        if model is not None:
            use_model = resolve_model(model)
        elif is_mm:
            # Only re-route to a vision model if the user's choice can't see.
            from .models import model_supports_vision

            use_model = (
                self.model
                if model_supports_vision(self.model)
                else vision_capable_default()
            )
        else:
            use_model = self.model
        payload = self._build_payload(messages, model=use_model, effort=effort)
        collected: List[str] = []
        for obj in self._stream_with_retry(payload):
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
        return "".join(
            self.stream(prompt, remember=remember, model=model, effort=effort)
        )

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
        return self.ask(
            [prompt, part], remember=remember, model=model, effort=effort
        )

    @staticmethod
    def _coerce_image(
        image: Union[str, bytes, ImagePart], mime_type: str
    ) -> ImagePart:
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
        payload = self._build_payload(
            messages, model=image_generation, can_use_tools=False
        )
        partials: List[str] = []
        final: Optional[str] = None
        for obj in self._stream_with_retry(payload):
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
