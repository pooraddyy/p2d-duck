from duck_ai import DuckChat, image_generation

def main() -> None:
    with DuckChat(model=image_generation) as duck:
        duck.generate_image(
            "a cute rubber duck wearing a wizard hat, digital art",
            save_to="duck_wizard.jpg",
        )
        print("saved -> duck_wizard.jpg")

if __name__ == "__main__":
    main()
