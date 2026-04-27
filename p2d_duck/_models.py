from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Union


class ModelType(str, Enum):
    GPT4oMini = "gpt-4o-mini"
    GPT5Mini = "gpt-5-mini"
    Claude = "claude-haiku-4-5"
    ClaudeHaiku = "claude-haiku-4-5"
    Llama = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
    Llama4Scout = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
    Mistral = "mistral-small-2603"
    MistralSmall = "mistral-small-2603"
    GptOss = "tinfoil/gpt-oss-120b"
    ImageGeneration = "image-generation"

    def __str__(self) -> str:
        return self.value


gpt4 = "gpt-4o-mini"
gpt4o_mini = "gpt-4o-mini"
gpt5 = "gpt-5-mini"
gpt5_mini = "gpt-5-mini"
claude = "claude-haiku-4-5"
claude_haiku = "claude-haiku-4-5"
llama = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
llama4_scout = "meta-llama/Llama-4-Scout-17B-16E-Instruct"
mistral = "mistral-small-2603"
mistral_small = "mistral-small-2603"
gpt_oss = "tinfoil/gpt-oss-120b"
gpt_oss_120b = "tinfoil/gpt-oss-120b"
image_generation = "image-generation"

MODEL_ALIASES = {
    "gpt4": gpt4,
    "gpt-4": gpt4,
    "gpt4o-mini": gpt4o_mini,
    "gpt-4o-mini": gpt4o_mini,
    "gpt5": gpt5,
    "gpt-5": gpt5,
    "gpt5-mini": gpt5_mini,
    "gpt-5-mini": gpt5_mini,
    "claude": claude,
    "claude-haiku": claude_haiku,
    "claude-haiku-4-5": claude_haiku,
    "llama": llama,
    "llama4": llama4_scout,
    "llama4-scout": llama4_scout,
    "mistral": mistral,
    "mistral-small": mistral_small,
    "mistral-small-2603": mistral_small,
    "gpt-oss": gpt_oss,
    "gpt-oss-120b": gpt_oss_120b,
    "tinfoil/gpt-oss-120b": gpt_oss_120b,
    "image-generation": image_generation,
    "image": image_generation,
}


_MODEL_CAPABILITIES = {
    "gpt-4o-mini": {"reasoning": False, "vision": False},
    "gpt-5-mini": {"reasoning": True, "vision": True, "fast": "minimal", "default": "minimal", "thinking": "low"},
    "claude-haiku-4-5": {"reasoning": True, "vision": True, "fast": "none", "default": "low", "thinking": "low"},
    "meta-llama/Llama-4-Scout-17B-16E-Instruct": {"reasoning": False, "vision": False},
    "mistral-small-2603": {"reasoning": False, "vision": False},
    "tinfoil/gpt-oss-120b": {"reasoning": True, "vision": False, "fast": "low", "default": "low", "thinking": "low"},
    "image-generation": {"reasoning": False, "vision": False},
}


def resolve_model(name: Union["ModelType", str]) -> str:
    if isinstance(name, ModelType):
        return name.value
    if not isinstance(name, str):
        return str(name)
    return MODEL_ALIASES.get(name, name)


def model_supports_reasoning(model: str) -> bool:
    return _MODEL_CAPABILITIES.get(resolve_model(model), {}).get("reasoning", False)


def model_supports_vision(model: str) -> bool:
    return _MODEL_CAPABILITIES.get(resolve_model(model), {}).get("vision", False)


def resolve_effort(model: str, effort: Optional[str]) -> Optional[str]:
    cap = _MODEL_CAPABILITIES.get(resolve_model(model), {})
    if not cap.get("reasoning"):
        return None
    if effort is None:
        return cap.get("default")
    e = effort.strip().lower()
    if e == "fast":
        return cap.get("fast")
    if e in ("reasoning", "thinking", "slow"):
        return cap.get("thinking")
    return effort


class Role(str, Enum):
    User = "user"
    Assistant = "assistant"
    System = "system"

    def __str__(self) -> str:
        return self.value


@dataclass
class ImagePart:
    image: str
    mime_type: str = "image/png"

    @classmethod
    def from_bytes(cls, data: bytes, mime_type: str = "image/png") -> "ImagePart":
        import base64

        b64 = base64.b64encode(data).decode("ascii")
        return cls(image=f"data:{mime_type};base64,{b64}", mime_type=mime_type)

    @classmethod
    def from_path(cls, path: str, mime_type: str | None = None) -> "ImagePart":
        import mimetypes

        mt = mime_type or mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            return cls.from_bytes(f.read(), mime_type=mt)

    def to_part(self) -> dict:
        return {"type": "image", "mimeType": self.mime_type, "image": self.image}


Content = Union[str, List[Union[str, ImagePart, dict]]]


@dataclass
class Message:
    role: str
    content: Content

    def to_dict(self) -> dict:
        if isinstance(self.content, str):
            return {"role": str(self.role), "content": self.content}
        parts: List[dict] = []
        for p in self.content:
            if isinstance(p, str):
                parts.append({"type": "text", "text": p})
            elif isinstance(p, ImagePart):
                parts.append(p.to_part())
            elif isinstance(p, dict):
                parts.append(p)
            else:
                raise TypeError(f"Unsupported content part: {type(p).__name__}")
        return {"role": str(self.role), "content": parts}


@dataclass
class History:
    model: str = gpt4
    messages: List[Message] = field(default_factory=list)

    def add_user(self, content: Content) -> None:
        self.messages.append(Message(role=Role.User.value, content=content))

    def add_assistant(self, content: str) -> None:
        self.messages.append(Message(role=Role.Assistant.value, content=content))

    def to_messages(self) -> list[dict]:
        return [m.to_dict() for m in self.messages]

    def clear(self) -> None:
        self.messages.clear()
