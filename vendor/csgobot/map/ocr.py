"""Optional Tesseract OCR fallback for map crops."""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageOps


def preprocess_map_crop(crop: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(crop)
    gray = ImageEnhance.Contrast(gray).enhance(2.5)
    w, h = gray.size
    gray = gray.resize((max(1, w * 3), max(1, h * 3)), Image.Resampling.LANCZOS)
    return gray.point(lambda p: 255 if p > 140 else 0)


def ocr_map_crop(crop: Image.Image) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""

    try:
        processed = preprocess_map_crop(crop)
        raw = pytesseract.image_to_string(processed, config="--psm 7 -l eng")
        return " ".join(raw.split()).strip()
    except Exception:
        return ""
