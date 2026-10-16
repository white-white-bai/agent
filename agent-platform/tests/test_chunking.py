"""知识库分段与清洗：预处理规则、分隔符分段、规则式 Q&A 分段。"""
from __future__ import annotations

from agent_platform.knowledge.chunking import (
    DEFAULT_CHUNK_CONFIG,
    chunk_document,
    normalize_config,
    preprocess_text,
    split_qa,
    split_text,
)

# --------------------------------------------------------------------------- normalize


def test_normalize_config_fills_defaults():
    assert normalize_config(None) == DEFAULT_CHUNK_CONFIG
    assert normalize_config({}) == DEFAULT_CHUNK_CONFIG


def test_normalize_config_clamps_and_falls_back():
    assert normalize_config({"separator": ""})["separator"] == "\n\n"
    assert normalize_config({"max_chars": 0})["max_chars"] == 1
    assert normalize_config({"max_chars": "bad"})["max_chars"] == DEFAULT_CHUNK_CONFIG["max_chars"]
    # overlap 被夹到 [0, max_chars-1]
    assert normalize_config({"max_chars": 10, "overlap_chars": 50})["overlap_chars"] == 9
    assert normalize_config({"overlap_chars": -3})["overlap_chars"] == 0


def test_normalize_config_reads_preprocess_and_qa_flags():
    cfg = normalize_config({"preprocess": {"remove_urls_emails": True}, "qa_mode": True})
    assert cfg["preprocess"] == {"replace_whitespace": True, "remove_urls_emails": True}
    assert cfg["qa_mode"] is True


# --------------------------------------------------------------------------- preprocess


def test_preprocess_collapses_whitespace_and_blank_lines():
    assert preprocess_text("a  \t b", replace_whitespace=True) == "a b"
    assert preprocess_text("a\r\n\r\n\r\nb", replace_whitespace=True) == "a\n\nb"
    assert preprocess_text("  前后空白  ", replace_whitespace=True) == "前后空白"


def test_preprocess_keeps_whitespace_when_disabled():
    assert preprocess_text("a  \t b", replace_whitespace=False) == "a  \t b"


def test_preprocess_removes_urls_and_emails():
    cleaned = preprocess_text(
        "见 https://example.com/a 与 www.test.cn 邮箱 admin@example.com", remove_urls_emails=True
    )
    assert "http" not in cleaned and "www." not in cleaned and "@" not in cleaned
    assert cleaned == "见 与 邮箱"


# --------------------------------------------------------------------------- split_text


def test_split_text_uses_custom_separator():
    assert split_text("A|B|C", separator="|", max_chars=100) == ["A|B|C"]


def test_split_text_hard_splits_long_paragraphs():
    text = "A" * 10 + "|" + "B" * 10
    assert split_text(text, separator="|", max_chars=5) == ["AAAAA", "AAAAA", "BBBBB", "BBBBB"]


def test_split_text_overlap_prepends_previous_tail():
    text = "AAAAAAAAAA|BBBBBBBBBB"
    assert split_text(text, separator="|", max_chars=10, overlap_chars=4) == ["AAAAAAAAAA", "AAAA|BBBBBBBBBB"]


def test_split_text_merges_adjacent_short_pieces():
    assert split_text("甲|乙|丙", separator="|", max_chars=100) == ["甲|乙|丙"]


# --------------------------------------------------------------------------- split_qa


def test_split_qa_pairs_question_with_following_answer():
    text = "什么是常州？\n常州是江苏省的地级市。\n\n如何预约？\n通过政务大厅或线上预约。"
    assert split_qa(text, max_chars=500) == [
        "什么是常州？\n常州是江苏省的地级市。",
        "如何预约？\n通过政务大厅或线上预约。",
    ]


def test_split_qa_groups_trailing_answer_into_last_pair():
    text = "问题一？\n\n补充说明。"
    assert split_qa(text, max_chars=500) == ["问题一？\n补充说明。"]


def test_split_qa_recognises_head_markers():
    text = "Q: 如何办理\n带身份证。\n\n问题：需要多久\n三个工作日。"
    assert split_qa(text, max_chars=500) == ["Q: 如何办理\n带身份证。", "问题：需要多久\n三个工作日。"]


def test_split_qa_handles_inline_question_and_answer():
    text = "问题一？答案一。\n\n问题二？答案二。"
    assert split_qa(text, max_chars=500) == ["问题一？答案一。", "问题二？答案二。"]


def test_split_qa_falls_back_without_question_markers():
    assert split_qa("普通段落。\n\n第二段。", max_chars=100) == ["普通段落。\n\n第二段。"]


def test_split_qa_keeps_preamble_before_first_question():
    chunks = split_qa("前言内容。\n\n问题？", max_chars=500)
    assert chunks == ["前言内容。", "问题？"]


# --------------------------------------------------------------------------- chunk_document


def test_chunk_document_preprocesses_then_splits():
    assert chunk_document("a  b\n\n\nc", {}) == ["a b\n\nc"]


def test_chunk_document_returns_empty_for_blank_text():
    assert chunk_document("   \n\n  ", {}) == []
    assert chunk_document("", None) == []


def test_chunk_document_honours_qa_mode():
    text = "问题一？\n答案一。\n\n问题二？\n答案二。"
    assert chunk_document(text, {"qa_mode": True, "preprocess": {"replace_whitespace": False}}) == [
        "问题一？\n答案一。",
        "问题二？\n答案二。",
    ]
