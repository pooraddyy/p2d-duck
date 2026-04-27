# p2d-duck

Free, no-API-key Python client for **DuckDuckGo AI Chat** ([duck.ai](https://duck.ai)).

- Sync + Async + Streaming
- 6 models: GPT-4o mini, GPT-5 mini, Claude Haiku 4.5, Llama 4 Scout, Mistral Small, GPT-OSS 120B
- **Reasoning effort switching** (`fast` vs `reasoning` mode)
- **Image generation** (`image-generation` model)
- **Image upload / multimodal** (vision-capable chats)
- Built-in solver for the `x-vqd-hash-1` JS challenge
- CLI: `p2d-duck`
- No account, no API key, no server, no fee

## Install

```bash
pip install p2d-duck
```

For the async client:

```bash
pip install "p2d-duck[async]"
```

## Quickstart

Just import the model alias you want and pass it to `DuckChat`:

```python
from p2d_duck import DuckChat, gpt4

with DuckChat(model=gpt4) as duck:
    reply = duck.ask("Explain quantum tunneling in one sentence.")
    print(reply)
```

Want Claude instead? Just swap the alias:

```python
from p2d_duck import DuckChat, claude

with DuckChat(model=claude) as duck:
    print(duck.ask("Hi Claude!"))
```

You can also pass the alias as a plain string — `DuckChat(model="gpt4")`,
`DuckChat(model="claude")`, etc.

## Streaming

```python
from p2d_duck import DuckChat

with DuckChat() as duck:
    for chunk in duck.stream("Write a 4-line haiku about ducks."):
        print(chunk, end="", flush=True)
```

## Multi-turn conversation

`DuckChat` keeps history automatically. Use `duck.reset()` to start fresh.

```python
from p2d_duck import DuckChat, claude

with DuckChat(model=claude) as duck:
    duck.ask("My name is Alice. Remember it.")
    print(duck.ask("What is my name?"))
    duck.reset()
```

## Reasoning vs Fast mode

Some models support a per-call **reasoning effort**. Pass `effort="fast"` for
quick replies or `effort="reasoning"` to let the model think.

```python
from p2d_duck import DuckChat, gpt5_mini, claude

# Fast mode (low/no reasoning effort)
with DuckChat(model=gpt5_mini, effort="fast") as duck:
    print(duck.ask("Quick: 2+2?"))

# Reasoning mode (model takes its time)
with DuckChat(model=claude, effort="reasoning") as duck:
    print(duck.ask("Solve this riddle: I speak without a mouth..."))

# Switch per-call
with DuckChat(model=gpt5_mini) as duck:
    duck.ask("Easy question", effort="fast")
    duck.ask("Hard question", effort="reasoning")
```

| Model | Supports `fast` / `reasoning`? | Default effort |
|---|---|---|
| `gpt4` (gpt-4o-mini) | no | — |
| `gpt5_mini` | yes | `minimal` |
| `claude` (Haiku 4.5) | yes | `low` |
| `gpt_oss` (gpt-oss 120B) | yes | `low` |
| `llama` (Llama 4 Scout) | no | — |
| `mistral` (Small 2603) | no | — |

For non-reasoning models, the `effort` parameter is silently ignored.

## Image generation

```python
from p2d_duck import DuckChat, image_generation

with DuckChat(model=image_generation) as duck:
    duck.generate_image(
        "a cute rubber duck wearing a wizard hat, digital art",
        save_to="duck_wizard.jpg",
    )
```

## Image upload (multimodal)

Multimodal requests use the vision-capable `gpt-5-mini` model by default.

```python
from p2d_duck import DuckChat, ImagePart

with DuckChat() as duck:
    reply = duck.ask_with_image(
        "What is in this image?",
        "photo.jpg",
    )
    print(reply)

    reply2 = duck.ask([
        "Compare these two images:",
        ImagePart.from_path("a.png"),
        ImagePart.from_path("b.png"),
    ])
```

## Async

```python
import asyncio
from p2d_duck import AsyncDuckChat, gpt4

async def main():
    async with AsyncDuckChat(model=gpt4) as duck:
        async for chunk in duck.stream("Tell me a fun duck fact."):
            print(chunk, end="", flush=True)

asyncio.run(main())
```

## CLI

```bash
p2d-duck                                        # interactive REPL
p2d-duck chat "Hello, who are you?"
p2d-duck -m claude chat "Hi Claude!"
p2d-duck -m gpt5_mini -e reasoning chat "Solve x^2 - 5x + 6 = 0"
p2d-duck chat "Describe this" --image cat.jpg
p2d-duck image "a watercolor moon over a lake" -o moon.jpg
```

## Models

```python
from p2d_duck import DuckChat, gpt4, gpt5_mini, claude, llama, mistral, gpt_oss, image_generation
```

| Alias | Resolved model id |
|---|---|
| `gpt4` / `gpt4o_mini` | `gpt-4o-mini` |
| `gpt5` / `gpt5_mini` | `gpt-5-mini` |
| `claude` / `claude_haiku` | `claude-haiku-4-5` |
| `llama` / `llama4_scout` | `meta-llama/Llama-4-Scout-17B-16E-Instruct` |
| `mistral` / `mistral_small` | `mistral-small-2603` |
| `gpt_oss` / `gpt_oss_120b` | `tinfoil/gpt-oss-120b` |
| `image_generation` | `image-generation` |

You can also pass any model string directly: `DuckChat(model="gpt-4o-mini")`.

The classic `ModelType` enum is still available for backwards compatibility:

```python
from p2d_duck import DuckChat, ModelType

with DuckChat(model=ModelType.Claude) as duck:
    ...
```

## How it works

DuckDuckGo's AI Chat backend (`duck.ai/duckchat/v1/*`) requires a per-request
proof-of-work challenge encoded in the `x-vqd-hash-1` header. The server returns an
obfuscated JavaScript snippet that must be evaluated against a browser-like
environment to compute valid client hashes.

`p2d-duck` ships with:

1. A minimal browser-DOM JavaScript shim (`_stubs.js`).
2. An embedded V8 isolate via [`mini-racer`](https://pypi.org/project/mini-racer/)
   to execute the challenge.
3. SHA-256 hashing of the resulting fingerprint values.
4. A durable-stream RSA-OAEP public key for resumable streams.

No external Node.js install is required.

## Exceptions

| Exception | When |
|---|---|
| `DuckChatError` | Generic error; base class. |
| `ChallengeError` | Couldn't solve the JS challenge. |
| `RateLimitError` | HTTP 429 from the server. |
| `ConversationLimitError` | Too many turns in one session. |
| `APIError` | Any other non-200 response (`.status_code`, `.body`). |

If you hit `HTTP 418 ERR_CHALLENGE` repeatedly, your IP is being throttled by
duck.ai's anti-abuse system. Wait 30-60 seconds between consecutive requests.

## License

MIT. See [LICENSE](LICENSE).

## Disclaimer

This is an **unofficial** reverse-engineered client. It is not affiliated
with or endorsed by DuckDuckGo. Use at your own risk and respect
[duck.ai](https://duck.ai)'s terms of service. The DuckDuckGo backend may
change at any time and break this library.
