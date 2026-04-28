from duck_ai import DuckChat, gpt4


def main() -> None:
    with DuckChat(model=gpt4) as duck:
        reply = duck.ask("Explain quantum tunneling in one sentence.")
        print(reply)


if __name__ == "__main__":
    main()
