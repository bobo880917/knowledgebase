import re
from dataclasses import dataclass


@dataclass(slots=True)
class SectionDraft:
    title: str
    level: int
    paragraphs: list[str]


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\x0b\x0c]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_paragraphs(text: str) -> list[str]:
    normalized = normalize_text(text)
    parts = re.split(r"\n\s*\n", normalized)
    return [re.sub(r"\s+", " ", part).strip() for part in parts if part.strip()]


def summarize_text(text: str, max_chars: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    sentence = re.split(r"(?<=[。！？.!?])\s*", cleaned, maxsplit=1)[0]
    if 20 <= len(sentence) <= max_chars:
        return sentence
    return cleaned[:max_chars].rstrip() + "..."


def chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        chunks.append(cleaned[start:end].strip())
        if end == len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def build_sections_from_plain_text(text: str, fallback_title: str) -> list[SectionDraft]:
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return [SectionDraft(title=fallback_title, level=1, paragraphs=[])]

    sections: list[SectionDraft] = []
    current = SectionDraft(title=fallback_title, level=1, paragraphs=[])
    title_pattern = re.compile(r"^((第[一二三四五六七八九十百千0-9]+[章节篇])|([0-9]+(\.[0-9]+)*[、.\s]))\s*(.+)$")

    for paragraph in paragraphs:
        is_short_title = len(paragraph) <= 80 and not re.search(r"[。！？.!?]$", paragraph)
        if title_pattern.match(paragraph) or is_short_title and len(current.paragraphs) >= 2:
            if current.paragraphs or not sections:
                sections.append(current)
            current = SectionDraft(title=paragraph, level=2, paragraphs=[])
        else:
            current.paragraphs.append(paragraph)

    if current.paragraphs or not sections:
        sections.append(current)
    return sections
