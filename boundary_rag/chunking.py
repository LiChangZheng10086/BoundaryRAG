"""RAG 索引用的文档切分工具。

索引器采用 parent-child 切分策略：
- 先解析结构块，保留标题、段落和代码块作为语义边界；
- 再把结构块组合成较大的 parent chunk，用于 metadata 和可追溯性；
- 最后把每个 parent 切成带重叠的小 child chunk，用于向量检索。

这样既能保证检索粒度足够精确，也能让生成答案知道命中内容来自哪个章节。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


DEFAULT_PARENT_CHARS = 2_400
DEFAULT_CHILD_CHARS = 700
DEFAULT_CHILD_OVERLAP = 80


@dataclass(frozen=True)
class ChunkPiece:
    """一个 child chunk，以及描述其切分方式的 metadata。"""
    text: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class StructuralBlock:
    """解析后的文档结构块，包含它所在的标题层级。"""
    text: str
    block_type: str
    heading_path: tuple[str, ...]


def chunk_text(text: str, *, max_chars: int = DEFAULT_CHILD_CHARS, overlap: int = DEFAULT_CHILD_OVERLAP) -> list[str]:
    """兼容旧接口：只返回 child chunk 的文本。"""
    return [piece.text for piece in chunk_document(text, max_child_chars=max_chars, child_overlap=overlap)]


def chunk_document(
    text: str,
    *,
    max_parent_chars: int = DEFAULT_PARENT_CHARS,
    max_child_chars: int = DEFAULT_CHILD_CHARS,
    child_overlap: int = DEFAULT_CHILD_OVERLAP,
) -> list[ChunkPiece]:
    """把原始文本切成可检索的 child chunk，并附带 parent metadata。"""
    blocks = _parse_structural_blocks(text)
    if not blocks:
        return []

    parents = _build_parent_chunks(blocks, max_parent_chars=max_parent_chars)
    pieces: list[ChunkPiece] = []
    for parent_index, parent in enumerate(parents):
        parent_id = _stable_parent_id(parent_index=parent_index, text=parent["text"])
        child_texts = _split_child_text(parent["text"], max_chars=max_child_chars, overlap=child_overlap)
        for child_index, child_text in enumerate(child_texts):
            metadata = {
                "chunk_index": len(pieces),
                "parent_id": parent_id,
                "parent_index": parent_index,
                "child_index": child_index,
                "heading_path": parent["heading_path"],
                "heading": parent["heading_path"][-1] if parent["heading_path"] else "",
                "block_types": parent["block_types"],
                "split_strategy": "heading_semantic_paragraph_code_parent_child",
                "semantic_boundary": True,
                "max_parent_chars": max_parent_chars,
                "max_child_chars": max_child_chars,
                "child_overlap": child_overlap,
            }
            pieces.append(ChunkPiece(text=child_text, metadata=metadata))
    return pieces


def _parse_structural_blocks(text: str) -> list[StructuralBlock]:
    """在不依赖 Markdown 库的情况下解析标题、段落和 fenced code block。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    heading_stack: list[tuple[int, str]] = []
    blocks: list[StructuralBlock] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False
    fence_marker = ""

    def current_heading_path() -> tuple[str, ...]:
        return tuple(title for _, title in heading_stack)

    def flush_paragraph() -> None:
        """在语义边界处提交已累积的段落行。"""
        if not paragraph:
            return
        content = "\n".join(line.strip() for line in paragraph if line.strip()).strip()
        paragraph.clear()
        if content:
            blocks.append(StructuralBlock(text=content, block_type="paragraph", heading_path=current_heading_path()))

    def flush_code() -> None:
        """把 fenced code 作为不可拆分的结构块提交。"""
        if not code_lines:
            return
        content = "\n".join(code_lines).strip()
        code_lines.clear()
        if content:
            blocks.append(StructuralBlock(text=content, block_type="code", heading_path=current_heading_path()))

    for raw_line in normalized.splitlines():
        line = raw_line.rstrip()
        fence_match = re.match(r"^\s*(```+|~~~+)", line)
        if fence_match:
            marker = fence_match.group(1)[:3]
            if in_code and marker == fence_marker:
                code_lines.append(line)
                flush_code()
                in_code = False
                fence_marker = ""
            elif not in_code:
                flush_paragraph()
                in_code = True
                fence_marker = marker
                code_lines.append(line)
            else:
                code_lines.append(line)
            continue

        if in_code:
            code_lines.append(line)
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_stack = [(item_level, item_title) for item_level, item_title in heading_stack if item_level < level]
            heading_stack.append((level, title))
            blocks.append(StructuralBlock(text=line.strip(), block_type="heading", heading_path=current_heading_path()))
            continue

        if not line.strip():
            flush_paragraph()
            continue

        paragraph.append(line)

    if in_code:
        flush_code()
    flush_paragraph()
    return blocks


def _build_parent_chunks(blocks: list[StructuralBlock], *, max_parent_chars: int) -> list[dict[str, object]]:
    """把结构块组合成 parent chunk，并尽量尊重章节变化。"""
    parents: list[dict[str, object]] = []
    current_blocks: list[StructuralBlock] = []

    def current_text() -> str:
        return "\n\n".join(block.text for block in current_blocks).strip()

    def flush_current() -> None:
        """保存当前 parent chunk，并重置累加器。"""
        if not current_blocks:
            return
        text = current_text()
        if not text:
            current_blocks.clear()
            return
        heading_path = _dominant_heading_path(current_blocks)
        block_types = sorted({block.block_type for block in current_blocks})
        parents.append(
            {
                "text": text,
                "heading_path": list(heading_path),
                "block_types": block_types,
            }
        )
        current_blocks.clear()

    for block in blocks:
        candidate = "\n\n".join([*(item.text for item in current_blocks), block.text]).strip()
        starts_new_section = block.block_type == "heading" and current_blocks
        if current_blocks and (starts_new_section or len(candidate) > max_parent_chars):
            flush_current()
        current_blocks.append(block)
        if block.block_type == "code" and len(block.text) >= max_parent_chars:
            flush_current()

    flush_current()
    return parents


def _dominant_heading_path(blocks: list[StructuralBlock]) -> tuple[str, ...]:
    for block in reversed(blocks):
        if block.heading_path:
            return block.heading_path
    return ()


def _split_child_text(text: str, *, max_chars: int, overlap: int) -> list[str]:
    """把 parent chunk 切成带重叠的检索 chunk。"""
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        candidate = normalized[start:end]
        if end < len(normalized):
            split_at = _best_split(candidate, min_split=max_chars // 2)
            if split_at > 0:
                end = start + split_at
                candidate = normalized[start:end]
        chunk = candidate.strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(0, end - overlap)
    return chunks


def _best_split(candidate: str, *, min_split: int) -> int:
    """优先在自然语言边界切分，而不是硬按字符截断。"""
    splitters = ["\n\n", "\n", "。", "！", "？", ". ", "; ", "；", "，", ", "]
    best = -1
    for splitter in splitters:
        index = candidate.rfind(splitter)
        if index >= min_split:
            best = max(best, index + len(splitter))
    return best


def _stable_parent_id(*, parent_index: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"parent_{parent_index}_{digest}"
