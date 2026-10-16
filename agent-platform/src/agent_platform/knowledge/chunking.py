"""知识库文本分段与清洗：预处理规则 + 可配分隔符分段 + 规则式 Q&A 分段。

分段单位是**字符**（沿用原 `chunk_text` 行为），不是 token。
`split_qa` 为**规则式**（按问句标记成对），不是 LLM 生成；未识别到问句标记时回退通用分段。
"""
from __future__ import annotations

import itertools
import re
from typing import Any

DEFAULT_SEPARATOR = "\n\n"
DEFAULT_MAX_CHARS = 500
DEFAULT_OVERLAP_CHARS = 50

DEFAULT_CHUNK_CONFIG: dict[str, Any] = {
    "separator": DEFAULT_SEPARATOR,
    "max_chars": DEFAULT_MAX_CHARS,
    "overlap_chars": DEFAULT_OVERLAP_CHARS,
    "preprocess": {"replace_whitespace": True, "remove_urls_emails": False},
    "qa_mode": False,
}

_URL_RE = re.compile(r"(?:https?://|www\.)[A-Za-z0-9\-._~:/?#\[\]@!$&*+,;=%]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_INLINE_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_QA_HEAD_RE = re.compile(r"^\s*(?:q[:：]|问[:：]|问题[:：])", re.IGNORECASE)


def _as_int(value: Any, default: int) -> int:
    """缺省（None）用默认值；显式给了非法值也回退默认；显式数字照用（含 0）。"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """与默认值合并并收敛字段：分隔符空回退、max_chars>=1、0<=overlap<max_chars。"""
    raw = dict(raw or {})
    preprocess_raw = raw.get("preprocess") or {}
    separator = raw.get("separator")
    if not isinstance(separator, str) or separator == "":
        separator = DEFAULT_SEPARATOR
    max_chars = _as_int(raw.get("max_chars"), DEFAULT_MAX_CHARS)
    max_chars = max(max_chars, 1)
    overlap = _as_int(raw.get("overlap_chars"), DEFAULT_OVERLAP_CHARS)
    overlap = min(max(overlap, 0), max_chars - 1) if max_chars > 1 else 0
    return {
        "separator": separator,
        "max_chars": max_chars,
        "overlap_chars": overlap,
        "preprocess": {
            "replace_whitespace": bool(preprocess_raw.get("replace_whitespace", True)),
            "remove_urls_emails": bool(preprocess_raw.get("remove_urls_emails", False)),
        },
        "qa_mode": bool(raw.get("qa_mode", False)),
    }


def preprocess_text(text: str, *, replace_whitespace: bool = True, remove_urls_emails: bool = False) -> str:
    """清洗正文：统一换行；可折叠连续空白/空行；可删除 URL 与邮箱。"""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if remove_urls_emails:
        normalized = _URL_RE.sub(" ", normalized)
        normalized = _EMAIL_RE.sub(" ", normalized)
    if replace_whitespace:
        normalized = _INLINE_WS_RE.sub(" ", normalized)
        normalized = _BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def _hard_split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def split_text(
    text: str,
    *,
    separator: str = DEFAULT_SEPARATOR,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = 0,
) -> list[str]:
    """按分隔符切段，段落超长时再按 max_chars 硬切；相邻小块合并；overlap>0 时保留重叠。"""
    size = max(max_chars, 1)
    sep = separator or DEFAULT_SEPARATOR
    pieces: list[str] = []
    for paragraph in (part.strip() for part in text.split(sep)):
        if not paragraph:
            continue
        pieces.extend(paragraph[i : i + size] for i in range(0, len(paragraph), size))
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) + len(piece) + len(sep) <= size:
            merged[-1] = f"{merged[-1]}{sep}{piece}"
        else:
            merged.append(piece)
    overlap = min(max(overlap_chars, 0), size - 1) if size > 1 else 0
    if overlap <= 0 or len(merged) < 2:
        return merged
    overlapped = [merged[0]]
    for previous, current in itertools.pairwise(merged):
        overlapped.append(f"{previous[-overlap:]}{sep}{current}")
    return overlapped


def _is_question(block: str) -> bool:
    first = block.splitlines()[0].strip() if block.strip() else ""
    if not first:
        return False
    if _QA_HEAD_RE.match(first):
        return True
    # 问句可能在首行中间（如「问题一？答案一。」），只要首行出现问号即视为问句
    return "？" in first or "?" in first


def split_qa(text: str, *, max_chars: int = DEFAULT_MAX_CHARS, separator: str = DEFAULT_SEPARATOR) -> list[str]:
    """规则式 Q&A 分段：问句行为界，问 + 其后答合为一段；无问句标记则回退通用分段。"""
    blocks = [block.strip() for block in text.split(separator) if block.strip()]
    pairs: list[tuple[str, list[str]]] = []
    preamble: list[str] = []
    current: tuple[str, list[str]] | None = None
    for block in blocks:
        if _is_question(block):
            if current is not None:
                pairs.append(current)
            current = (block, [])
        elif current is not None:
            current[1].append(block)
        else:
            preamble.append(block)
    if current is not None:
        pairs.append(current)
    if not pairs:
        return split_text(text, separator=separator, max_chars=max_chars)
    size = max(max_chars, 1)
    chunks: list[str] = []
    if preamble:
        chunks.extend(_hard_split("\n".join(preamble), size))
    for question, body in pairs:
        joined = question if not body else f"{question}\n" + "\n".join(body)
        chunks.extend(_hard_split(joined, size))
    return chunks


def chunk_document(text: str, config: dict[str, Any] | None = None) -> list[str]:
    """预处理 + 分段（Q&A 或通用），返回分段文本列表。"""
    cfg = normalize_config(config)
    cleaned = preprocess_text(text, **cfg["preprocess"])
    if not cleaned:
        return []
    if cfg["qa_mode"]:
        return split_qa(cleaned, max_chars=cfg["max_chars"], separator=cfg["separator"])
    return split_text(
        cleaned,
        separator=cfg["separator"],
        max_chars=cfg["max_chars"],
        overlap_chars=cfg["overlap_chars"],
    )
