from duck_ai import (
    MODEL_ALIASES,
    ModelType,
    list_models,
    model_supports_reasoning,
    model_supports_vision,
    resolve_effort,
    resolve_model,
)

def test_alias_resolution():
    assert resolve_model("gpt4") == "gpt-4o-mini"
    assert resolve_model("GPT4") == "gpt-4o-mini"
    assert resolve_model("claude") == "claude-haiku-4-5"
    assert resolve_model("haiku") == "claude-haiku-4-5"
    assert resolve_model("image") == "image-generation"

def test_passthrough_unknown():
    # Unknown model strings pass through unchanged so users can try new ids.
    assert resolve_model("custom/model-7b") == "custom/model-7b"

def test_enum_member():
    assert resolve_model(ModelType.Claude) == "claude-haiku-4-5"

def test_none_default():
    assert resolve_model(None) == "gpt-4o-mini"

def test_capabilities():
    assert model_supports_reasoning("gpt5_mini") is True
    assert model_supports_reasoning("gpt4") is False
    assert model_supports_vision("claude") is True
    assert model_supports_vision("llama") is False

def test_effort():
    assert resolve_effort("gpt5_mini", None) == "minimal"
    assert resolve_effort("gpt5_mini", "fast") == "minimal"
    assert resolve_effort("gpt5_mini", "reasoning") == "low"
    assert resolve_effort("gpt4", "reasoning") is None  # not a reasoning model
    assert resolve_effort("claude", "thinking") == "low"

def test_list_models():
    models = list_models()
    assert "gpt-4o-mini" in models
    assert "claude-haiku-4-5" in models
    assert "image-generation" in models

def test_alias_table_complete():
    # Every alias should resolve to a known model id (or itself).
    for k, v in MODEL_ALIASES.items():
        assert resolve_model(k) == v, f"alias {k} did not resolve to {v}"
