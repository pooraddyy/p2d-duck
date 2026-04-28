from duck_ai import DuckChat


def main() -> None:
    with DuckChat() as duck:
        for chunk in duck.stream("Write a 4-line haiku about ducks."):
            print(chunk, end="", flush=True)
        print()


if __name__ == "__main__":
    main()
