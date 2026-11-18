"""Real PDF -> DOCX conversion quality tests using synthetic fixtures.

These tests run the actual pdf2docx engine (no mocks) and verify text
completeness, OOXML font configuration, preserved styles and editability.
"""

import io
import zipfile

import pymupdf
import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from fastapi.testclient import TestClient

from app.main import create_app
from app.pdf_to_word.converter import convert_pdf_to_docx
from app.pdf_to_word.errors import ConversionFailedError
from tests.pdf_to_word import synthetic_pdfs as samples

ALLOWED_CJK_FONTS = {"宋体", "黑体", "微软雅黑", "等线", "楷体", "仿宋"}
ALLOWED_LATIN_FONTS = {
    "Arial",
    "Times New Roman",
    "Calibri",
    "Courier New",
    "Cambria",
    "Consolas",
    "Georgia",
    "Verdana",
    "Tahoma",
}


def _convert(pdf_bytes: bytes) -> Document:
    return Document(io.BytesIO(convert_pdf_to_docx(pdf_bytes).docx))


def _full_text(document: Document) -> str:
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def _document_xml(document: Document) -> str:
    buffer = io.BytesIO()
    document.save(buffer)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _assert_fonts_are_safe(document: Document) -> None:
    """Every run must declare resolvable Latin and East Asian fonts."""
    r_fonts_list = list(document.element.body.iter(qn("w:rFonts")))
    assert r_fonts_list, "expected at least one run with font declarations"
    for r_fonts in r_fonts_list:
        ascii_font = r_fonts.get(qn("w:ascii"))
        east_asia = r_fonts.get(qn("w:eastAsia"))
        assert ascii_font in ALLOWED_LATIN_FONTS
        assert r_fonts.get(qn("w:hAnsi")) in ALLOWED_LATIN_FONTS
        assert r_fonts.get(qn("w:cs")) in ALLOWED_LATIN_FONTS
        assert east_asia in ALLOWED_CJK_FONTS


def _assert_editable_structure(document: Document) -> None:
    xml = _document_xml(document)
    # No text-box fragmentation and no raw PDF font names in the output.
    assert "txbxContent" not in xml
    assert "Heiti" not in xml
    assert document.paragraphs


def test_sample_a_chinese_paragraphs() -> None:
    document = _convert(samples.chinese_paragraphs_pdf())
    text = _full_text(document)
    for expected in ("示例季度运营报告", "第一段", "第二段", "第三段", "2026"):
        assert expected in text
    _assert_fonts_are_safe(document)
    _assert_editable_structure(document)


def test_sample_b_mixed_chinese_and_english() -> None:
    document = _convert(samples.mixed_language_pdf())
    text = _full_text(document)
    for expected in ("中英混排", "FastAPI", "DOCX", "2026-11-17", "100%"):
        assert expected in text
    _assert_fonts_are_safe(document)


def test_sample_c_styles_are_preserved() -> None:
    document = _convert(samples.styled_pdf())
    runs = {
        run.text: run
        for paragraph in document.paragraphs
        for run in paragraph.runs
        if run.text.strip()
    }

    heading = runs["蓝色标题示例"]
    assert heading.font.size == Pt(20)
    assert heading.font.color.rgb == RGBColor(0, 0, 0xCC)

    bold = runs["Bold Heading"]
    assert bold.bold is True
    assert bold.font.size == Pt(14)
    assert bold.font.color.rgb == RGBColor(0, 0, 0xCC)

    body = runs["普通黑色正文，字号较小，用于对比样式保留情况。"]
    assert body.font.size == Pt(10.5)
    assert body.font.color.rgb == RGBColor(0, 0, 0)
    _assert_fonts_are_safe(document)


def test_sample_d_table_content_and_fonts() -> None:
    document = _convert(samples.table_pdf())
    assert len(document.tables) == 1
    table = document.tables[0]
    cells = [[cell.text for cell in row.cells] for row in table.rows]
    assert cells[0] == ["指标名称", "示例数值"]
    assert cells[1] == ["季度收入", "128 万元"]
    assert cells[2] == ["更新日期", "2026-11-17"]
    assert cells[3] == ["Owner", "Example Team"]
    _assert_fonts_are_safe(document)
    _assert_editable_structure(document)


def test_sample_e_report_structure() -> None:
    document = _convert(samples.report_pdf())
    text = _full_text(document)
    for expected in (
        "示例项目周报",
        "报告日期：2026-11-17",
        "一、本周进展",
        "二、下周计划",
        "三、风险说明",
        "Conversion Quality",
    ):
        assert expected in text

    title = next(
        run
        for paragraph in document.paragraphs
        for run in paragraph.runs
        if run.text == "示例项目周报"
    )
    assert title.font.size == Pt(20)
    _assert_fonts_are_safe(document)
    _assert_editable_structure(document)


def test_trailing_chinese_period_after_email_is_preserved() -> None:
    """The full stop after an English email address must survive conversion.

    V1.1 reported that ``user@example.com。`` could lose its trailing ``。``.
    The three layouts below all keep the period as separate spans or on the
    following line, which is how real PDF producers emit it.
    """
    document = _convert(samples.email_period_pdf())
    # Iterate ``w:t`` so text inside hyperlink elements is included too.
    text = "".join(node.text or "" for node in document.element.body.iter(qn("w:t")))
    normalized = text.replace("\t", "")

    assert "如需帮助请发送邮件至 user@example.com。" in normalized
    assert "联系邮箱：user@example.com。" in normalized
    assert normalized.count("user@example.com。") == 3


@pytest.mark.parametrize(
    "sample_factory",
    [
        samples.chinese_paragraphs_pdf,
        samples.mixed_language_pdf,
        samples.styled_pdf,
        samples.table_pdf,
        samples.report_pdf,
    ],
)
def test_all_samples_produce_valid_docx_package(sample_factory) -> None:
    outcome = convert_pdf_to_docx(sample_factory())
    assert outcome.fonts_normalized is True
    with zipfile.ZipFile(io.BytesIO(outcome.docx)) as archive:
        assert archive.testzip() is None
        assert "word/document.xml" in archive.namelist()
    assert len(Document(io.BytesIO(outcome.docx)).paragraphs) >= 0


def test_api_response_has_normalized_fonts_and_chinese_text() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={
            "file": (
                "示例报告.pdf",
                samples.chinese_paragraphs_pdf(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200
    assert response.headers["X-Font-Normalization"] == "applied"
    document = Document(io.BytesIO(response.content))
    assert "示例季度运营报告" in _full_text(document)
    _assert_fonts_are_safe(document)
    assert "Heiti" not in response.content.decode("utf-8", errors="ignore")


def test_error_paths_still_reject_invalid_inputs() -> None:
    client = TestClient(create_app())
    empty = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert empty.status_code == 400

    not_pdf = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("note.txt", b"plain text", "text/plain")},
    )
    assert not_pdf.status_code == 400

    document = pymupdf.open()
    page = document.new_page()
    page.draw_rect(pymupdf.Rect(0, 0, 595, 842), color=(1, 1, 1), fill=(1, 1, 1))
    buffer = io.BytesIO()
    document.save(buffer, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    document.close()
    encrypted = client.post(
        "/api/pdf-to-word/convert",
        files={"file": ("locked.pdf", buffer.getvalue(), "application/pdf")},
    )
    assert encrypted.status_code == 400
    assert "加密" in encrypted.json()["detail"]


def test_api_returns_original_docx_with_warning_when_font_repair_fails(monkeypatch) -> None:
    """A failed font repair must still deliver the valid DOCX, flagged."""

    def _broken_normalize(docx_bytes: bytes) -> bytes:
        raise RuntimeError("internal-normalizer-detail")

    monkeypatch.setattr(
        "app.pdf_to_word.font_normalizer.normalize_docx", _broken_normalize
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={
            "file": (
                "示例报告.pdf",
                samples.chinese_paragraphs_pdf(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Font-Normalization"] == "fallback"

    # The fallback file must remain a valid, editable DOCX with intact text.
    document = Document(io.BytesIO(response.content))
    assert "示例季度运营报告" in _full_text(document)
    assert document.paragraphs

    body = response.content.decode("utf-8", errors="ignore")
    assert "internal-normalizer-detail" not in body
    assert "Traceback" not in body


def test_api_reports_5xx_when_no_valid_docx_can_be_returned(monkeypatch) -> None:
    """Engine failure is an internal error, not a 400 client error."""

    def _broken_convert(pdf_bytes: bytes):
        raise ConversionFailedError

    monkeypatch.setattr(
        "app.pdf_to_word.service.convert_pdf_to_docx", _broken_convert
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/pdf-to-word/convert",
        files={
            "file": (
                "示例报告.pdf",
                samples.chinese_paragraphs_pdf(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "转换失败，请稍后重试。"
    assert "Traceback" not in response.text
