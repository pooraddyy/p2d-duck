import asyncio

from p2d_duck import AsyncDuckChat, gpt4


async def main() -> None:
    async with AsyncDuckChat(model=gpt4) as duck:
        async for chunk in duck.stream("Tell me one fun duck fact."):
            print(chunk, end="", flush=True)
        print()


if __name__ == "__main__":
    asyncio.run(main())
