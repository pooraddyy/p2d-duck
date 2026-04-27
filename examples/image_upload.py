from p2d_duck import DuckChat, ImagePart, gpt4


def main() -> None:
    with DuckChat(model=gpt4) as duck:
        reply = duck.ask_with_image(
            "What is in this image? Describe in one sentence.",
            "photo.jpg",
        )
        print(reply)

        reply2 = duck.ask([
            "Compare these two images:",
            ImagePart.from_path("a.png"),
            ImagePart.from_path("b.png"),
        ])
        print(reply2)


if __name__ == "__main__":
    main()
