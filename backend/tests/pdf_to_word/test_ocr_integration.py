"""Integration tests for OCR using the real RapidOCR engine.

All PDFs are synthetic scans generated in ``synthetic_pdfs``; no real documents
or personal data are used. Recognition is not exact, so assertions check that
the key content is recovered rather than a character-perfect transcript.
"""

import io
import re
import zipfile

from docx import Document
from fastapi.testclient import TestClient

from app.main import create_app
from app.pdf_to_word import ocr
from app.pdf_to_word.converter import convert_pdf_to_docx
from app.pdf_to_word.errors import OcrUnavailableError
from app.pdf_to_word.ocr import recognize_pdf
from app.pdf_to_word.service import PdfToWordService
from tests.pdf_to_word import synthetic_pdfs as samples
from tests.pdf_to_word.test_conversion_quality import (
    _assert_editable_structure,
    _assert_fonts_are_safe,
)


def _compact(text: str) -> str:
    """Drop whitespace so OCR spacing does not affect content assertions."""
    return re.sub(r"\s+", "", text)


def _full_text(document: Document) -> str:
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def _document_from_docx(docx_bytes: bytes) -> Document:
    return Document(io.BytesIO(docx_bytes))


def _media_names(docx_bytes: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
        return [name for name in archive.namelist() if name.startswith("word/media/")]


def _assert_contains(text: str, expected: str) -> None:
    assert _compact(expected) in _compact(text), f"missing {expected!r} in OCR output"


def _ocr_convert(pdf_bytes: bytes):
    return PdfToWordService().convert(pdf_bytes, "scan.pdf", ocr_enabled=True)


def test_scanned_chinese_pdf_produces_editable_text() -> None:
    outcome = _ocr_convert(samples.scanned_chinese_pdf())
    assert outcome.ocr_status == "applied"
    assert outcome.fonts_normalized is True

    document = _document_from_docx(outcome.docx)
    text = _full_text(document)
    for expected in (
        "示例季度运营报告",
        "本季度示例业务保持稳定。",
        "各项指标均为虚构数据。",
        "用于验证中文扫描识别。",
    ):
        _assert_contains(text, expected)

    # The scan must become text, not an embedded page image.
    assert _media_names(outcome.docx) == []
    _assert_fonts_are_safe(document)
    _assert_editable_structure(document)


def test_scanned_english_pdf_keeps_full_lines() -> None:
    outcome = _ocr_convert(samples.scanned_english_pdf())
    assert outcome.ocr_status == "applied"

    text = _full_text(_document_from_docx(outcome.docx))
    for expected in (
        "Quarterly Report 2026",
        "Revenue reached 128 units, up 12 percent.",
        "user@example.com",
        "A-1024",
    ):
        _assert_contains(text, expected)


def test_scanned_mixed_language_pdf_keeps_digits_and_symbols() -> None:
    outcome = _ocr_convert(samples.scanned_mixed_language_pdf())
    assert outcome.ocr_status == "applied"

    text = _full_text(_document_from_docx(outcome.docx))
    for expected in ("中英混排扫描示例", "2026-11-17", "v1.2", "95%", "100%", "括号"):
        _assert_contains(text, expected)


def test_mixed_pages_keep_both_pages_in_reading_order() -> None:
    outcome = _ocr_convert(samples.mixed_pages_pdf())
    assert outcome.ocr_status == "applied"

    document = _document_from_docx(outcome.docx)
    text = _full_text(document)
    for expected in (
        "第一页为普通文字页。",
        "该段落应保持原生文字不被栅格化。",
        "第二页为扫描图片页。",
        "Scan only content.",
    ):
        _assert_contains(text, expected)

    compact = _compact(text)
    assert compact.index(_compact("第一页为普通文字页。")) < compact.index(
        _compact("第二页为扫描图片页。")
    )
    # The digital page must not be duplicated by the OCR step.
    assert compact.count(_compact("第一页为普通文字页。")) == 1


def test_same_page_mixed_content_adds_image_text_without_duplicates() -> None:
    outcome = _ocr_convert(samples.same_page_image_text_pdf())
    assert outcome.ocr_status == "applied"

    document = _document_from_docx(outcome.docx)
    compact = _compact(_full_text(document))
    for expected in (
        "原生文字段落，应当保留。",
        "Native line 2026.",
        "图片中的文字。",
        "Image-only note.",
    ):
        assert _compact(expected) in compact
    # Native text must appear once only, even though the image sits on the page.
    assert compact.count(_compact("原生文字段落，应当保留。")) == 1
    assert compact.count(_compact("Native line 2026.")) == 1
    _assert_fonts_are_safe(document)


def test_structured_scan_keeps_title_list_and_table_text() -> None:
    outcome = _ocr_convert(samples.structured_scanned_pdf())
    assert outcome.ocr_status == "applied"

    text = _full_text(_document_from_docx(outcome.docx))
    for expected in (
        "示例结构文档",
        "一、要点列表",
        "第一项示例内容。",
        "第二项示例内容。",
        "1024",
    ):
        _assert_contains(text, expected)


def test_illustration_only_scan_does_not_invent_text() -> None:
    outcome = _ocr_convert(samples.illustration_only_pdf())
    assert outcome.ocr_status == "partial"
    assert _media_names(outcome.docx)


def test_prepare_searchable_pdf_leaves_text_pages_untouched() -> None:
    prepared = recognize_pdf(samples.chinese_paragraphs_pdf())
    assert not prepared.needed
    assert len(prepared.pages) == 1


def test_api_ocr_enabled_returns_recognized_docx() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("扫描件.pdf", samples.scanned_chinese_pdf(), "application/pdf")},
        data={"ocr_enabled": "true"},
    )

    assert response.status_code == 200
    assert response.headers["X-Ocr-Status"] == "applied"
    assert response.headers["X-Font-Normalization"] == "applied"

    document = Document(io.BytesIO(response.content))
    _assert_contains(_full_text(document), "示例季度运营报告")


def test_api_without_ocr_flag_still_rejects_scanned_pdf() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("扫描件.pdf", samples.scanned_chinese_pdf(), "application/pdf")},
    )

    assert response.status_code == 400
    assert "扫描件" in response.json()["detail"]


def test_api_reports_ocr_status_disabled_for_plain_conversion() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("示例.pdf", samples.chinese_paragraphs_pdf(), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.headers["X-Ocr-Status"] == "disabled"


def test_api_reports_ocr_status_not_needed_for_text_pdf() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("示例.pdf", samples.chinese_paragraphs_pdf(), "application/pdf")},
        data={"ocr_enabled": "true"},
    )
    assert response.status_code == 200
    assert response.headers["X-Ocr-Status"] == "not-needed"


def test_api_enforces_ocr_page_limit() -> None:
    client = TestClient(create_app())
    pages = []
    for _ in range(ocr.MAX_OCR_PAGES + 1):
        pages.append(samples.scanned_chinese_pdf())
    # Combine pages by merging the single-page scans.
    import pymupdf

    merged = pymupdf.open()
    for page_pdf in pages:
        source = pymupdf.open(stream=page_pdf, filetype="pdf")
        merged.insert_pdf(source)
        source.close()
    buffer = io.BytesIO()
    merged.save(buffer)
    merged.close()

    response = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("多页.pdf", buffer.getvalue(), "application/pdf")},
        data={"ocr_enabled": "true"},
    )
    assert response.status_code == 400
    assert "页数" in response.json()["detail"]


def test_api_maps_ocr_engine_failure_to_5xx(monkeypatch) -> None:
    def _broken_ocr(image_bytes, *, engine=None):
        raise OcrUnavailableError

    monkeypatch.setattr(ocr, "ocr_image", _broken_ocr)

    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("扫描件.pdf", samples.scanned_chinese_pdf(), "application/pdf")},
        data={"ocr_enabled": "true"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "文字识别服务暂时不可用，请稍后重试。"
    assert "Traceback" not in response.text


def test_ocr_output_of_plain_conversion_is_unchanged() -> None:
    """The plain path must keep producing the same content as V1.1."""
    direct = convert_pdf_to_docx(samples.chinese_paragraphs_pdf())
    outcome = _ocr_convert(samples.chinese_paragraphs_pdf())
    assert outcome.ocr_status == "not-needed"
    assert _full_text(_document_from_docx(outcome.docx)) == _full_text(
        _document_from_docx(direct.docx)
    )
