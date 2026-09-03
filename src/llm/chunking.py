"""Text preparation for provider payload limits."""


def chunk_text(text: str, max_chars: int = 12000) -> list[str]:
    """Split text on paragraph boundaries while preserving all content."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [paragraph[index : index + max_chars] for index in range(0, len(paragraph), max_chars)] or [""]
        for piece in pieces:
            if current and len(current) + 2 + len(piece) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks
