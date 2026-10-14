"""字段级 SM4 加解密（复用现有库的密钥/IV，与 Java 侧兼容）。

纯 Python 实现（ECB / CBC + PKCS7），避免引入额外依赖；密钥/IV 支持 hex 字符串。
"""
from __future__ import annotations

from functools import lru_cache

SBOX = [
    0xd6, 0x90, 0xe9, 0xfe, 0xcc, 0xe1, 0x3d, 0xb7, 0x16, 0xb6, 0x14, 0xc2, 0x28, 0xfb, 0x2c, 0x05,
    0x2b, 0x67, 0x9a, 0x76, 0x2a, 0xbe, 0x04, 0xc3, 0xaa, 0x44, 0x13, 0x26, 0x49, 0x86, 0x06, 0x99,
    0x9c, 0x42, 0x50, 0xf4, 0x91, 0xef, 0x98, 0x7a, 0x33, 0x54, 0x0b, 0x43, 0xed, 0xcf, 0xac, 0x62,
    0xe4, 0xb3, 0x1c, 0xa9, 0xc9, 0x08, 0xe8, 0x95, 0x80, 0xdf, 0x94, 0xfa, 0x75, 0x8f, 0x3f, 0xa6,
    0x47, 0x07, 0xa7, 0xfc, 0xf3, 0x73, 0x17, 0xba, 0x83, 0x59, 0x3c, 0x19, 0xe6, 0x85, 0x4f, 0xa8,
    0x68, 0x6b, 0x81, 0xb2, 0x71, 0x64, 0xda, 0x8b, 0xf8, 0xeb, 0x0f, 0x4b, 0x70, 0x56, 0x9d, 0x35,
    0x1e, 0x24, 0x0e, 0x5e, 0x63, 0x58, 0xd1, 0xa2, 0x25, 0x22, 0x7c, 0x3b, 0x01, 0x21, 0x78, 0x87,
    0xd4, 0x00, 0x46, 0x57, 0x9f, 0xd3, 0x27, 0x52, 0x4c, 0x36, 0x02, 0xe7, 0xa0, 0xc4, 0xc8, 0x9e,
    0xea, 0xbf, 0x8a, 0xd2, 0x40, 0xc7, 0x38, 0xb5, 0xa3, 0xf7, 0xf2, 0xce, 0xf9, 0x61, 0x15, 0xa1,
    0xe0, 0xae, 0x5d, 0xa4, 0x9b, 0x34, 0x1a, 0x55, 0xad, 0x93, 0x32, 0x30, 0xf5, 0x8c, 0xb1, 0xe3,
    0x1d, 0xf6, 0xe2, 0x2e, 0x82, 0x66, 0xca, 0x60, 0xc0, 0x29, 0x23, 0xab, 0x0d, 0x53, 0x4e, 0x6f,
    0xd5, 0xdb, 0x37, 0x45, 0xde, 0xfd, 0x8e, 0x2f, 0x03, 0xff, 0x6a, 0x72, 0x6d, 0x6c, 0x5b, 0x51,
    0x8d, 0x1b, 0xaf, 0x92, 0xbb, 0xdd, 0xbc, 0x7f, 0x11, 0xd9, 0x5c, 0x41, 0x1f, 0x10, 0x5a, 0xd8,
    0x0a, 0xc1, 0x31, 0x88, 0xa5, 0xcd, 0x7b, 0xbd, 0x2d, 0x74, 0xd0, 0x12, 0xb8, 0xe5, 0xb4, 0xb0,
    0x89, 0x69, 0x97, 0x4a, 0x0c, 0x96, 0x77, 0x7e, 0x65, 0xb9, 0xf1, 0x09, 0xc5, 0x6e, 0xc6, 0x84,
    0x18, 0xf0, 0x7d, 0xec, 0x3a, 0xdc, 0x4d, 0x20, 0x79, 0xee, 0x5f, 0x3e, 0xd7, 0xcb, 0x39, 0x48,
]

FK = [0xA3B1BAC6, 0x56AA3350, 0x677D9197, 0xB27022DC]
CK = [
    0x00070E15, 0x1C232A31, 0x383F464D, 0x545B6269, 0x70777E85, 0x8C939AA1, 0xA8AFB6BD, 0xC4CBD2D9,
    0xE0E7EEF5, 0xFC030A11, 0x181F262D, 0x343B4249, 0x50575E65, 0x6C737A81, 0x888F969D, 0xA4ABB2B9,
    0xC0C7CED5, 0xDCE3EAF1, 0xF8FF060D, 0x141B2229, 0x30373E45, 0x4C535A61, 0x686F767D, 0x848B9299,
    0xA0A7AEB5, 0xBCC3CAD1, 0xD8DFE6ED, 0xF4FB0209, 0x10171E25, 0x2C333A41, 0x484F565D, 0x646B7279,
]

_MASK32 = 0xFFFFFFFF


def _rotl(value: int, bits: int) -> int:
    return ((value << bits) | (value >> (32 - bits))) & _MASK32


def _tau(value: int) -> int:
    return (
        (SBOX[(value >> 24) & 0xFF] << 24)
        | (SBOX[(value >> 16) & 0xFF] << 16)
        | (SBOX[(value >> 8) & 0xFF] << 8)
        | SBOX[value & 0xFF]
    )


def _t(value: int) -> int:
    b = _tau(value)
    return b ^ _rotl(b, 2) ^ _rotl(b, 10) ^ _rotl(b, 18) ^ _rotl(b, 24)


def _t_prime(value: int) -> int:
    b = _tau(value)
    return b ^ _rotl(b, 13) ^ _rotl(b, 23)


@lru_cache(maxsize=64)
def _round_keys(key: bytes) -> tuple[int, ...]:
    if len(key) != 16:
        raise ValueError("SM4 密钥必须为 16 字节")
    mk = [int.from_bytes(key[i * 4 : i * 4 + 4], "big") for i in range(4)]
    k = [mk[i] ^ FK[i] for i in range(4)]
    rk: list[int] = []
    for i in range(32):
        k.append(k[i] ^ _t_prime(k[i + 1] ^ k[i + 2] ^ k[i + 3] ^ CK[i]))
        rk.append(k[i + 4])
    return tuple(rk)


def _crypt_block(block: bytes, round_keys: tuple[int, ...]) -> bytes:
    x = [int.from_bytes(block[i * 4 : i * 4 + 4], "big") for i in range(4)]
    for i in range(32):
        x.append(x[i] ^ _t(x[i + 1] ^ x[i + 2] ^ x[i + 3] ^ round_keys[i]))
    return b"".join(int(x[35 - i]).to_bytes(4, "big") for i in range(4))


def _normalize(data: bytes | str) -> bytes:
    if isinstance(data, bytes):
        return data
    text = data.strip()
    try:
        return bytes.fromhex(text)
    except ValueError:
        return data.encode()


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    padding = block - len(data) % block
    return data + bytes([padding]) * padding


def _pkcs7_unpad(data: bytes, block: int = 16) -> bytes:
    if not data or len(data) % block:
        raise ValueError("密文长度非法")
    padding = data[-1]
    if padding < 1 or padding > block or data[-padding:] != bytes([padding]) * padding:
        raise ValueError("PKCS7 填充非法")
    return data[:-padding]


def _process(data: bytes, round_keys: tuple[int, ...], *, decrypt: bool, iv: bytes | None) -> bytes:
    keys = round_keys[::-1] if decrypt else round_keys
    out = bytearray()
    prev = iv
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        if decrypt:
            plain = _crypt_block(chunk, keys)
            if iv is not None:
                plain = bytes(a ^ b for a, b in zip(plain, prev))
            prev = chunk
        else:
            if iv is not None:
                chunk = bytes(a ^ b for a, b in zip(chunk, prev))
            plain = _crypt_block(chunk, keys)
            prev = plain
        out.extend(plain)
    return bytes(out)


def encrypt(
    text: str,
    key: str | bytes,
    iv: str | bytes | None = None,
    *,
    mode: str = "cbc",
    output: str = "hex",
) -> str:
    raw_key = _normalize(key)
    raw_iv = _normalize(iv) if iv else None
    if mode == "cbc" and raw_iv is None:
        raw_iv = b"\x00" * 16
    payload = _process(_pkcs7_pad(text.encode()), _round_keys(raw_key), decrypt=False, iv=raw_iv)
    return payload.hex() if output == "hex" else _b64(payload)


def decrypt(
    ciphertext: str,
    key: str | bytes,
    iv: str | bytes | None = None,
    *,
    mode: str = "cbc",
    input: str = "hex",
) -> str:
    raw_key = _normalize(key)
    raw_iv = _normalize(iv) if iv else None
    if mode == "cbc" and raw_iv is None:
        raw_iv = b"\x00" * 16
    payload = bytes.fromhex(ciphertext) if input == "hex" else _unb64(ciphertext)
    if not payload or len(payload) % 16:
        raise ValueError("密文长度非法")
    plain = _process(payload, _round_keys(raw_key), decrypt=True, iv=raw_iv)
    return _pkcs7_unpad(plain).decode()


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode()


def _unb64(text: str) -> bytes:
    import base64

    return base64.b64decode(text)
