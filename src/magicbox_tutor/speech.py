"""Turn model text into short, speakable Chinese sentences.

The vendor TTS queue speaks one message at a time and only accepts text that
contains Chinese.  This module removes Markdown/code/URL noise, turns common
math symbols into spoken Chinese, limits the total answer length, and splits the
result into sentence-sized chunks.
"""

from __future__ import annotations

import re
import unicodedata


_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_HTML_RE = re.compile(r"<[^>]+>")
_MARKDOWN_CHARS_RE = re.compile(r"[*_~#>|]+")
_MULTI_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_PUNCT_RE = re.compile(r"([，。！？；：、])\1+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\uFE0F\u200D"
    "]"
)
_CJK_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)、])\s*", re.MULTILINE)
_LATEX_RE = re.compile(r"\$([^$]+)\$")


def sanitize_for_speech(text: str, max_chars: int = 600) -> str:
    """Return a clean, Chinese-friendly string suitable for TTS."""

    if not text:
        return ""

    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    value = _CODE_FENCE_RE.sub("", value)
    value = _IMAGE_RE.sub(r"\1", value)
    value = _LINK_RE.sub(r"\1", value)
    value = _URL_RE.sub("", value)
    value = _EMAIL_RE.sub("", value)
    value = _HTML_RE.sub("", value)
    value = _INLINE_CODE_RE.sub(r"\1", value)
    value = _LATEX_RE.sub(r"\1", value)
    value = value.replace("\\", "")
    # Normalize a digit-star-digit multiplication before Markdown stripping.
    value = re.sub(r"(?<=\d)\s*\*\s*(?=\d)", "乘", value)
    value = _MARKDOWN_CHARS_RE.sub("", value)
    value = _LIST_MARKER_RE.sub("", value)
    value = _EMOJI_RE.sub("", value)

    # Normalise the symbols a primary-school answer is most likely to use.
    value = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"百分之\1", value)
    value = value.replace("℃", "摄氏度").replace("°C", "摄氏度")
    value = re.sub(r"(?<=\d)\s*\+\s*(?=\d)", "加", value)
    value = re.sub(r"(?<=\d)\s*=\s*(?=\d)", "等于", value)
    value = re.sub(r"(?<=\d)\s*[×xX*]\s*(?=\d)", "乘", value)
    value = re.sub(r"(?<=\d)\s*[÷/]\s*(?=\d)", "除以", value)
    value = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "减", value)
    value = value.replace("×", "乘").replace("÷", "除以")
    value = value.replace("+", "加").replace("=", "等于")

    value = value.replace("\n", "。")
    value = _MULTI_SPACE_RE.sub(" ", value)
    value = re.sub(r" +([，。！？；：、])", r"\1", value)
    value = _MULTI_PUNCT_RE.sub(r"\1", value)
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("!", "！").replace("?", "？").replace(";", "；")
    value = value.replace(":", "：")
    value = value.strip(" \t，,。；;：:")

    if not value:
        return ""

    # TTS in the vendor audio node skips messages without Chinese.  Prefixing a
    # short Chinese phrase keeps an English-only answer audible instead of silent.
    if not _CJK_RE.search(value):
        value = "我用中文说：" + value

    if len(value) > max_chars:
        value = _truncate_at_boundary(value, max_chars)

    if value and value[-1] not in "。！？!?；;":
        value += "。"
    return value


def _truncate_at_boundary(text: str, max_chars: int) -> str:
    clipped = text[:max_chars]
    boundary = max(
        clipped.rfind("。"),
        clipped.rfind("！"),
        clipped.rfind("？"),
        clipped.rfind("；"),
    )
    if boundary >= max(20, max_chars // 3):
        return clipped[: boundary + 1]
    comma = max(clipped.rfind("，"), clipped.rfind("、"), clipped.rfind(","))
    if comma >= max(20, max_chars // 3):
        return clipped[:comma] + "。"
    return clipped.rstrip("，,、 ") + "。"


def split_sentences(text: str, max_sentence_chars: int = 80) -> list[str]:
    """Split text into TTS-sized sentences without dropping content."""

    if not text:
        return []
    sentences: list[str] = []
    for match in _SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        if len(sentence) <= max_sentence_chars:
            sentences.append(_ensure_ending(sentence))
            continue
        sentences.extend(_split_long_sentence(sentence, max_sentence_chars))
    return [s for s in sentences if _has_speakable_content(s)]


def _split_long_sentence(sentence: str, limit: int) -> list[str]:
    pieces: list[str] = []
    remaining = sentence
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = max(
            window.rfind("，"),
            window.rfind("、"),
            window.rfind(","),
            window.rfind("："),
            window.rfind(":"),
        )
        if cut < max(12, limit // 3):
            cut = limit - 1
        piece = remaining[: cut + 1].strip("，,、：: ")
        if piece:
            pieces.append(_ensure_ending(piece))
        remaining = remaining[cut + 1 :].lstrip("，,、：: ")
    if remaining.strip():
        pieces.append(_ensure_ending(remaining.strip()))
    return pieces


def _ensure_ending(text: str) -> str:
    text = text.strip()
    if text and text[-1] not in "。！？!?；;":
        text += "。"
    return text


def _has_speakable_content(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4DBF\u4E00-\u9FFF0-9A-Za-z]", text))


def prepare_speech(
    text: str,
    max_chars: int = 600,
    max_sentence_chars: int = 80,
) -> list[str]:
    """Return the ordered list of chunks to publish to the TTS topic."""

    clean = sanitize_for_speech(text, max_chars=max_chars)
    if not clean:
        return []
    chunks = split_sentences(clean, max_sentence_chars=max_sentence_chars)
    # audio_io skips a TTS message that contains no Chinese.  Keep every chunk
    # audible even when the model answers an English word in isolation.
    return [
        chunk if _CJK_RE.search(chunk) else "英文：" + chunk
        for chunk in chunks
    ]
