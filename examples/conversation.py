from duck_ai import DuckChat, gpt5_mini

def main() -> None:
    with DuckChat(model=gpt5_mini) as duck:
        print(duck.ask("My name is Alice. Remember it."))
        print(duck.ask("What is my name?"))
        duck.reset()
        print(duck.ask("What is my name? (after reset)"))

if __name__ == "__main__":
    main()
