from __future__ import annotations

from unittest.mock import patch

import pytest

from duck_ai import APIError, ChallengeError, ConversationLimitError, DuckChat


def _stub_init(self):
    self.model = "gpt-4o-mini"
    self.effort = None
    self.user_agent = "test-agent"
    self.fe_version = "test-fe"
    self.timeout = 5.0
    self.max_retries = 3
    self.backoff_base = 0.0
    from duck_ai.models import History

    self.history = History()
    self._jwk = {"kty": "RSA", "e": "AQAB", "n": "x"}
    import threading

    self._jwk_lock = threading.Lock()
    self._owns_client = False
    self._client = None
    self._warmed = True


def _make_chat() -> DuckChat:
    chat = DuckChat.__new__(DuckChat)
    _stub_init(chat)
    return chat


def test_retry_succeeds_after_transient_challenge_error():
    chat = _make_chat()
    calls = {"n": 0}

    def fake_attempt(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ChallengeError("boom")
        yield {"message": "hello"}

    with patch.object(chat, "_attempt_stream", side_effect=fake_attempt):
        out = list(chat._stream_with_retry({}))

    assert calls["n"] == 2
    assert out == [{"message": "hello"}]


def test_retry_gives_up_after_max_attempts():
    chat = _make_chat()
    chat.max_retries = 2
    attempts = {"n": 0}

    def always_fail(payload):
        attempts["n"] += 1
        raise ChallengeError("nope")
        yield  # unreachable

    with patch.object(chat, "_attempt_stream", side_effect=always_fail):
        with pytest.raises(ChallengeError):
            list(chat._stream_with_retry({}))

    assert attempts["n"] == 2


def test_conversation_limit_is_terminal():
    chat = _make_chat()
    attempts = {"n": 0}

    def always_limit(payload):
        attempts["n"] += 1
        raise ConversationLimitError("ERR_CONVERSATION_LIMIT")
        yield  # unreachable

    with patch.object(chat, "_attempt_stream", side_effect=always_limit):
        with pytest.raises(ConversationLimitError):
            list(chat._stream_with_retry({}))

    # No retries — terminal error should bail out immediately.
    assert attempts["n"] == 1


def test_4xx_api_error_is_not_retried():
    chat = _make_chat()
    attempts = {"n": 0}

    def always_400(payload):
        attempts["n"] += 1
        raise APIError("bad request", status_code=400, body="nope")
        yield  # unreachable

    with patch.object(chat, "_attempt_stream", side_effect=always_400):
        with pytest.raises(APIError):
            list(chat._stream_with_retry({}))

    assert attempts["n"] == 1


def test_5xx_api_error_is_retried():
    chat = _make_chat()
    chat.max_retries = 3
    attempts = {"n": 0}

    def flaky(payload):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise APIError("upstream", status_code=502, body="")
        yield {"message": "ok"}

    with patch.object(chat, "_attempt_stream", side_effect=flaky):
        out = list(chat._stream_with_retry({}))

    assert attempts["n"] == 3
    assert out == [{"message": "ok"}]
