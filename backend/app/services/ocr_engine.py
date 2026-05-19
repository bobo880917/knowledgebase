"""本地 OCR：Tesseract + PyMuPDF（PDF 页渲染）+ Pillow（图片）。可选依赖，见 pyproject.toml [ocr]。"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any, Callable

from app.core.config import get_settings

ProgressNote = Callable[[str], None]


def ocr_health() -> dict[str, Any]:
    settings = get_settings()
    if not settings.ocr_enabled:
        return {
            "enabled": False,
            "ok": True,
            "engine": "",
            "message": "OCR 未启用。扫描 PDF / 图片需在 .env 设置 OCR_ENABLED=true 并安装依赖（uv sync --extra ocr）与本机 Tesseract。",
        }
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return {
            "enabled": True,
            "ok": False,
            "engine": "",
            "message": "已启用 OCR 但未安装 Python 依赖，请执行：uv sync --extra ocr",
        }
    import pytesseract as pt

    if settings.ocr_tesseract_cmd:
        pt.pytesseract.tesseract_cmd = settings.ocr_tesseract_cmd
    try:
        ver = pt.get_tesseract_version()
        return {
            "enabled": True,
            "ok": True,
            "engine": f"tesseract {ver}",
            "message": (
                f"Tesseract 可用；OCR_LANG={settings.ocr_lang}。"
                " 中文乱码请确认 `tesseract --list-langs` 含 chi_sim；"
                "macOS 可 `brew install tesseract-lang`。"
            ),
        }
    except Exception as exc:
        return {
            "enabled": True,
            "ok": False,
            "engine": "",
            "message": f"Tesseract 不可用或未安装语言包：{exc}",
        }


def _cache_file(raw_content_hash: str) -> Path:
    settings = get_settings()
    seed = (
        f"{raw_content_hash}|{settings.ocr_lang}|{settings.ocr_pdf_dpi}|"
        f"{settings.ocr_tesseract_config}|{int(settings.ocr_preprocess_autocontrast)}"
    ).encode("utf-8")
    name = hashlib.sha256(seed).hexdigest()[:40] + ".json"
    d = settings.upload_dir / "ocr_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def load_ocr_cache(raw_content_hash: str) -> dict[str, Any] | None:
    path = _cache_file(raw_content_hash)
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_ocr_cache(raw_content_hash: str, payload: dict[str, Any]) -> None:
    path = _cache_file(raw_content_hash)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=0)


def _configure_tesseract() -> None:
    import pytesseract

    cmd = get_settings().ocr_tesseract_cmd.strip()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


def _tesseract_config_arg() -> str | None:
    raw = get_settings().ocr_tesseract_config.strip()
    return raw if raw else None


def _prepare_for_tesseract(img: Any) -> Any:
    from PIL import ImageOps

    settings = get_settings()
    gray = img.convert("L") if img.mode != "L" else img
    if settings.ocr_preprocess_autocontrast:
        gray = ImageOps.autocontrast(gray, cutoff=2)
    return gray


def ocr_image_path(path: Path, *, raw_content_hash: str, progress: ProgressNote | None = None) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    if not settings.ocr_enabled:
        raise ValueError("未启用 OCR（OCR_ENABLED=false），无法导入图片为文本")

    cached = load_ocr_cache(raw_content_hash)
    if cached and isinstance(cached.get("text"), str):
        if progress:
            progress("OCR：使用磁盘缓存")
        meta = dict(cached.get("meta") or {})
        meta["cache_hit"] = True
        return str(cached["text"]), meta

    _configure_tesseract()
    import pytesseract
    from PIL import Image

    if progress:
        progress("OCR：识别图片中…")
    img = Image.open(path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    prepared = _prepare_for_tesseract(img)
    tess_cfg = _tesseract_config_arg()
    text = (
        pytesseract.image_to_string(prepared, lang=settings.ocr_lang, config=tess_cfg) or ""
    )
    meta: dict[str, Any] = {
        "engine": "tesseract",
        "lang": settings.ocr_lang,
        "source": "image",
        "cache_hit": False,
        "tesseract_config": tess_cfg or "",
        "preprocess_autocontrast": settings.ocr_preprocess_autocontrast,
    }
    save_ocr_cache(raw_content_hash, {"text": text, "meta": meta})
    return text, meta


def ocr_pdf_scanned(
    path: Path,
    *,
    raw_content_hash: str,
    progress: ProgressNote | None = None,
) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    if not settings.ocr_enabled:
        raise ValueError("PDF 无文字层且未启用 OCR")

    cached = load_ocr_cache(raw_content_hash)
    if cached and isinstance(cached.get("text"), str):
        if progress:
            progress("OCR：使用磁盘缓存")
        meta = dict(cached.get("meta") or {})
        meta["cache_hit"] = True
        return str(cached["text"]), meta

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF OCR 需要安装 pymupdf：uv sync --extra ocr") from exc

    _configure_tesseract()
    import pytesseract
    from PIL import Image

    doc = fitz.open(path)
    try:
        pages_total = len(doc)
        n = min(pages_total, max(1, settings.ocr_pdf_max_pages))
        tess_cfg = _tesseract_config_arg()
        parts: list[str] = []
        for i in range(n):
            if progress:
                progress(f"OCR：识别 PDF 第 {i + 1}/{n} 页…")
            page = doc[i]
            pix = page.get_pixmap(dpi=settings.ocr_pdf_dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            prepared = _prepare_for_tesseract(img)
            parts.append(
                pytesseract.image_to_string(prepared, lang=settings.ocr_lang, config=tess_cfg) or ""
            )
        text = "\n\n".join(parts)
    finally:
        doc.close()

    meta: dict[str, Any] = {
        "engine": "tesseract+pymupdf",
        "lang": settings.ocr_lang,
        "dpi": settings.ocr_pdf_dpi,
        "pages_ocr": n,
        "pages_total": pages_total,
        "cache_hit": False,
        "tesseract_config": tess_cfg or "",
        "preprocess_autocontrast": settings.ocr_preprocess_autocontrast,
    }

    save_ocr_cache(raw_content_hash, {"text": text, "meta": meta})
    return text, meta
