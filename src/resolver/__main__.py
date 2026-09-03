from .resolve import EntityResolver


if __name__ == "__main__":
    print(EntityResolver(["OpenAI"]).resolve("OpenAI, Inc."))
