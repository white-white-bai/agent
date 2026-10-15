"""上传文件的统一读取：大小上限、扩展名白名单、文本解码（UTF-8 优先，兼容 GBK）。"""
from __future__ import annotations

from pathlib import PurePath

from fastapi import HTTPException, UploadFile

from agent_platform.core.config import get_settings

READ_CHUNK = 64 * 1024


async def read_upload(file: UploadFile, allowed_suffixes: set[str]) -> str:
    suffix = PurePath(file.filename or "").suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{suffix or '无扩展名'}")
    limit = get_settings().upload_max_bytes
    buffer = bytearray()
    while chunk := await file.read(READ_CHUNK):
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise HTTPException(status_code=413, detail=f"文件超过上限 {limit} 字节")
    return decode_text(bytes(buffer))


def decode_text(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="文件编码无法识别，请另存为 UTF-8") from exc


def chunk_text(text: str, size: int) -> list[str]:
    """按空行切段，段落超长时再按 size 硬切；空白块丢弃。"""
    size = max(size, 1)
    pieces: list[str] = []
    for paragraph in (part.strip() for part in text.split("\n\n")):
        if not paragraph:
            continue
        pieces.extend(paragraph[i : i + size] for i in range(0, len(paragraph), size))
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) + len(piece) + 2 <= size:
            merged[-1] = f"{merged[-1]}\n\n{piece}"
        else:
            merged.append(piece)
    return merged
