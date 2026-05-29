from __future__ import annotations


def chunk_text(text: str, *, max_chars: int = 700, overlap: int = 80) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        candidate = normalized[start:end]

        if end < len(normalized):
            split_at = max(candidate.rfind("\n"), candidate.rfind("。"), candidate.rfind("."))
            if split_at > max_chars // 2:
                end = start + split_at + 1
                candidate = normalized[start:end]

        chunks.append(candidate.strip())
        if end >= len(normalized):
            break
        start = max(0, end - overlap)

    return chunks
