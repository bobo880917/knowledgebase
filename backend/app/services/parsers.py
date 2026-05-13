from pathlib import Path

from app.services.text_utils import SectionDraft, build_sections_from_plain_text, normalize_text, split_paragraphs


SUPPORTED_EXTENSIONS = {".md", ".txt", ".docx", ".pdf", ".html", ".htm", ".xlsx", ".pptx"}


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
    if suffix in (".html", ".htm"):
        return parse_html_file(path)
    if suffix == ".xlsx":
        return parse_xlsx(path)
    if suffix == ".pptx":
        return parse_pptx(path)
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


def parse_html_file(path: Path) -> list[SectionDraft]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return parse_html_content(raw, path.stem)


def parse_html_content(html: str, fallback_title: str) -> list[SectionDraft]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("解析 HTML 需要安装 beautifulsoup4、lxml") from exc

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title_el = soup.find("title")
    page_title = title_el.get_text(strip=True) if title_el else ""
    text = soup.get_text(separator="\n")
    text = normalize_text(text)
    if not text.strip():
        raise ValueError("HTML 未提取到正文文本")
    heading = page_title or fallback_title
    return build_sections_from_plain_text(text, heading)


def parse_xlsx(path: Path) -> list[SectionDraft]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("解析 XLSX 需要安装 openpyxl") from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    sections: list[SectionDraft] = []
    try:
        for sheet in workbook.worksheets:
            lines: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append("\t".join(cells))
            block = normalize_text("\n".join(lines))
            paragraphs = split_paragraphs(block) if block else []
            if not paragraphs and block:
                paragraphs = [block]
            title = f"工作表: {sheet.title}"
            if paragraphs:
                sections.append(SectionDraft(title=title, level=2, paragraphs=paragraphs))
    finally:
        workbook.close()
    if not sections:
        raise ValueError("表格中未读取到文本内容")
    return sections


def parse_pptx(path: Path) -> list[SectionDraft]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise RuntimeError("解析 PPTX 需要安装 python-pptx") from exc

    prs = Presentation(str(path))
    sections: list[SectionDraft] = []
    for index, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                t = (shape.text or "").strip()
                if t:
                    texts.append(t)
        body = normalize_text("\n".join(texts))
        if not body:
            continue
        paras = split_paragraphs(body)
        title = f"幻灯片 {index}"
        sections.append(SectionDraft(title=title, level=2, paragraphs=paras))
    if not sections:
        raise ValueError("演示文稿中未提取到文本")
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
