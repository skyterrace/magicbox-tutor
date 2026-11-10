from __future__ import annotations

from magicbox_tutor.speech import prepare_speech, sanitize_for_speech, split_sentences


def test_markdown_code_url_and_emoji_are_removed() -> None:
    text = (
        "```python\nprint('x')\n```\n"
        "**3+4=7**，对不对？😊\n"
        "参考 [这里](https://example.com/a) 或 https://example.com/b"
    )
    clean = sanitize_for_speech(text)
    assert "3加4等于7" in clean
    assert "```" not in clean
    assert "**" not in clean
    assert "https://" not in clean
    assert "😊" not in clean
    assert "这里" in clean


def test_english_only_gets_chinese_prefix() -> None:
    clean = sanitize_for_speech("Apple means 苹果.")  # contains Chinese, no prefix
    assert "Apple" in clean
    clean2 = sanitize_for_speech("Hello world.")
    assert clean2.startswith("我用中文说：")


def test_math_symbols_are_spoken() -> None:
    clean = sanitize_for_speech("12÷3=4，50%是0.5，2×3=6，2*3=6。")
    assert "12除以3等于4" in clean
    assert "百分之50" in clean
    assert "2乘3等于6" in clean


def test_sentences_are_split_and_bounded() -> None:
    sentences = prepare_speech(
        "第一句。第二句！第三句？" + "很长的一句话，" * 30,
        max_chars=600,
        max_sentence_chars=40,
    )
    assert sentences[0] == "第一句。"
    assert sentences[1] == "第二句！"
    assert all(len(s) <= 40 for s in sentences)
    assert len(sentences) > 3


def test_long_answer_is_truncated_at_boundary() -> None:
    text = "这是第一句。" * 100
    clean = sanitize_for_speech(text, max_chars=80)
    assert len(clean) <= 81
    assert clean.endswith("。")


def test_every_chunk_has_chinese_for_vendor_tts() -> None:
    chunks = prepare_speech("Apple. 苹果。Banana.", max_chars=200, max_sentence_chars=40)
    assert chunks
    assert all(any("\u4e00" <= ch <= "\u9fff" for ch in chunk) for chunk in chunks)


def test_empty_and_symbol_only() -> None:
    assert sanitize_for_speech("") == ""
    assert sanitize_for_speech("😊😊") == ""
    assert split_sentences("") == []
