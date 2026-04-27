from p2d_duck import DuckChat, image_generation


def main() -> None:
    with DuckChat(model=image_generation) as duck:
        data = duck.generate_image(
            "a cute rubber duck wearing a wizard hat, digital art",
            save_to="duck_wizard.jpg",
        )
        print(f"Saved {len(data)} bytes to duck_wizard.jpg")


if __name__ == "__main__":
    main()
