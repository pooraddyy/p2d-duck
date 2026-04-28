from duck_ai import DuckChat, ImagePart

def main() -> None:
    with DuckChat() as duck:
        # Single image
        reply = duck.ask_with_image(
            "What is in this image?",
            "photo.jpg",
        )
        print(reply)

        # Multiple images via the parts list
        print(duck.ask([
            "Compare these two images:",
            ImagePart.from_path("a.png"),
            ImagePart.from_path("b.png"),
        ]))

if __name__ == "__main__":
    main()
