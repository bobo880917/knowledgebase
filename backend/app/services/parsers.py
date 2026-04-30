from pathlib import Path

from app.services.text_utils import SectionDraft, build_sections_from_plain_text, normalize_text, split_paragraphs


SUPPORTED_EXTENSIONS = {".md", ".txt", ".docx", ".pdf"}


def parse_document(path: Path) -> list[SectionDraft]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"暂不支持的文件格式：{suffix}")
    if suffix == ".md":
        return parse_markdown(path)
    if suffix == ".txt":
        return build_sections_from_plain_text(path.read_text(encoding="utf-8"), path.stem)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    raise ValueError(f"暂不支持的文件格式：{suffix}")


def parse_markdown(path: Path) -> list[SectionDraft]:
    lines = path.read_text(encoding="utf-8").splitlines()
    sections: list[SectionDraft] = []
    current = SectionDraft(title=path.stem, level=1, paragraphs=[])
    buffer: list[str] = []

    def flush_paragraphs() -> None:
        nonlocal buffer
        if buffer:
            current.paragraphs.extend(split_paragraphs("\n".join(buffer)))
            buffer = []

    for line in lines:
        if line.startswith("#"):
            marker, _, title = line.partition(" ")
            if marker and set(marker) == {"#"} and title.strip():
                flush_paragraphs()
                if current.paragraphs or not sections:
                    sections.append(current)
                current = SectionDraft(title=title.strip(), level=len(marker), paragraphs=[])
                continue
        buffer.append(line)

    flush_paragraphs()
    if current.paragraphs or not sections:
        sections.append(current)
    return sections


def parse_docx(path: Path) -> list[SectionDraft]:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("解析 DOCX 需要安装 python-docx") from exc

    doc = Document(path)
    sections: list[SectionDraft] = []
    current = SectionDraft(title=path.stem, level=1, paragraphs=[])

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name.lower() if paragraph.style else ""
        if style_name.startswith("heading") or style_name.startswith("标题"):
            if current.paragraphs or not sections:
                sections.append(current)
            level = 2
            for token in style_name.split():
                if token.isdigit():
                    level = int(token)
                    break
            current = SectionDraft(title=text, level=level, paragraphs=[])
        else:
            current.paragraphs.append(text)

    if current.paragraphs or not sections:
        sections.append(current)
    return sections


def parse_pdf(path: Path) -> list[SectionDraft]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("解析 PDF 需要安装 pypdf") from exc

    reader = PdfReader(str(path))
    page_texts = []
    for page in reader.pages:
        page_texts.append(page.extract_text() or "")
    text = normalize_text("\n\n".join(page_texts))
    if not text:
        raise ValueError("PDF 未提取到文本，可能是扫描件；OCR 将在后续阶段支持")
    return build_sections_from_plain_text(text, path.stem)
