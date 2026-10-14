"""SM4 字段级加密：标准向量、模式、填充与错误路径。"""
from __future__ import annotations

import pytest

from agent_platform.core.crypto import (
    _b64,
    _crypt_block,
    _normalize,
    _pkcs7_pad,
    _pkcs7_unpad,
    _round_keys,
    _unb64,
    decrypt,
    encrypt,
)

# GB/T 32907-2016 附录 A.1 标准向量
KEY_HEX = "0123456789abcdeffedcba9876543210"
CIPHER_HEX = "681edf34d206965e86b3e94f536e4246"

KEY_BYTES = bytes.fromhex(KEY_HEX)
KEY_PLAIN = "zbcdefghijklmnop"  # 16 字节非 hex 字符串 → 按 UTF-8 直传
IV_A = "iv-vector-000001"
IV_B = "iv-vector-000002"
SAMPLE = "常州市政务服务中心"


def test_sm4_known_answer_vector():
    round_keys = _round_keys(KEY_BYTES)
    assert _crypt_block(KEY_BYTES, round_keys).hex() == CIPHER_HEX


def test_round_keys_rejects_wrong_length():
    with pytest.raises(ValueError, match="SM4 密钥必须为 16 字节"):
        _round_keys(b"short")


def test_normalize_accepts_hex_and_plain_text():
    assert _normalize(KEY_HEX) == KEY_BYTES
    assert _normalize(KEY_PLAIN) == KEY_PLAIN.encode()
    assert _normalize(KEY_BYTES) == KEY_BYTES
    assert _normalize(f"  {KEY_HEX}  ") == KEY_BYTES


def test_pkcs7_pad_and_unpad_roundtrip():
    assert _pkcs7_pad(b"abc") == b"abc" + b"\x0d" * 13
    assert len(_pkcs7_pad(b"0123456789abcdef")) == 32
    assert _pkcs7_unpad(_pkcs7_pad(b"abc")) == b"abc"


def test_pkcs7_unpad_rejects_bad_length():
    with pytest.raises(ValueError, match="密文长度非法"):
        _pkcs7_unpad(b"abc")
    with pytest.raises(ValueError, match="密文长度非法"):
        _pkcs7_unpad(b"")


def test_pkcs7_unpad_rejects_bad_padding():
    with pytest.raises(ValueError, match="PKCS7 填充非法"):
        _pkcs7_unpad(b"0123456789abcde" + b"\x00")
    with pytest.raises(ValueError, match="PKCS7 填充非法"):
        _pkcs7_unpad(b"0123456789abcde" + b"\x11")


def test_encrypt_decrypt_hex_roundtrip_with_key_hex():
    ciphertext = encrypt(SAMPLE, KEY_HEX)
    assert ciphertext != SAMPLE
    assert all(char in "0123456789abcdef" for char in ciphertext)
    assert decrypt(ciphertext, KEY_HEX) == SAMPLE


def test_encrypt_decrypt_with_plain_text_key_and_iv():
    ciphertext = encrypt("hello 中台", KEY_PLAIN, IV_A)
    assert decrypt(ciphertext, KEY_PLAIN, IV_A) == "hello 中台"


def test_cbc_defaults_to_zero_iv():
    assert encrypt("abc", KEY_HEX) == encrypt("abc", KEY_HEX, "\x00" * 16)


def test_cbc_changes_with_iv():
    first = encrypt("abc", KEY_HEX, IV_A)
    second = encrypt("abc", KEY_HEX, IV_B)
    assert first != second
    assert decrypt(first, KEY_HEX, IV_A) == "abc"
    assert decrypt(second, KEY_HEX, IV_B) == "abc"


def test_ecb_mode_ignores_iv_and_is_deterministic():
    first = encrypt("常州市", KEY_HEX, mode="ecb")
    second = encrypt("常州市", KEY_HEX, mode="ecb")
    assert first == second
    assert decrypt(first, KEY_HEX, mode="ecb") == "常州市"


def test_cbc_and_ecb_differ():
    assert encrypt(SAMPLE, KEY_HEX, mode="ecb") != encrypt(SAMPLE, KEY_HEX)


def test_cbc_multi_block_roundtrip():
    ciphertext = encrypt(SAMPLE, KEY_HEX)
    assert len(ciphertext) == 64
    assert decrypt(ciphertext, KEY_HEX) == SAMPLE


def test_multi_block_ciphertext_is_not_ecb_concat():
    plain = SAMPLE + SAMPLE
    cbc = bytes.fromhex(encrypt(plain, KEY_HEX))
    ecb = bytes.fromhex(encrypt(plain, KEY_HEX, mode="ecb"))
    assert cbc[:16] == ecb[:16]
    assert cbc[16:32] != ecb[16:32]


def test_base64_output_and_input():
    ciphertext = encrypt("常州市", KEY_HEX, output="base64")
    assert decrypt(ciphertext, KEY_HEX, input="base64") == "常州市"


def test_encrypt_always_pads_to_block_boundary():
    for length in (0, 1, 15, 16, 17, 31, 32):
        payload = "a" * length
        ciphertext = encrypt(payload, KEY_HEX)
        assert len(ciphertext) % 32 == 0
        assert decrypt(ciphertext, KEY_HEX) == payload


def test_b64_helpers_roundtrip():
    assert _unb64(_b64(b"\x00\xff\x10")) == b"\x00\xff\x10"


def test_decrypt_rejects_truncated_ciphertext():
    with pytest.raises(ValueError, match="密文长度非法"):
        decrypt("681edf34", KEY_HEX)


def test_decrypt_rejects_tampered_ciphertext():
    ciphertext = encrypt("常州市政务服务中心", KEY_HEX)
    tampered = "00" + ciphertext[2:]
    with pytest.raises((ValueError, UnicodeDecodeError)):
        decrypt(tampered, KEY_HEX)
