"""Unit tests for DOCX font normalization (synthetic DOCX fixtures only)."""

import io
from unittest.mock import patch

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.pdf_to_word import font_normalizer
from app.pdf_to_word.errors import ConversionFailedError
from app.pdf_to_word.font_normalizer import (
    DEFAULT_CJK_FONT,
    DEFAULT_LATIN_FONT,
    map_cjk_font,
    map_latin_font,
    normalize_docx,
    normalize_docx_with_status,
    resolve_run_fonts,
    strip_subset_prefix,
)


def test_strip_subset_prefix() -> None:
    assert strip_subset_prefix("ABCDEF+SimSun") == "SimSun"
    assert strip_subset_prefix("SimSun") == "SimSun"
    assert strip_subset_prefix("") == ""


def test_common_latin_fonts_are_canonicalized() -> None:
    assert map_latin_font("Helvetica") == "Arial"
    assert map_latin_font("Helvetica-Bold") == "Arial"
    assert map_latin_font("Times") == "Times New Roman"
    assert map_latin_font("TimesNewRomanPSMT") == "Times New Roman"
    assert map_latin_font("Arial") == "Arial"
    assert map_latin_font("Courier") == "Courier New"


def test_common_cjk_fonts_are_canonicalized() -> None:
    assert map_cjk_font("SimSun") == "宋体"
    assert map_cjk_font("ABCDEF+SimSun") == "宋体"
    assert map_cjk_font("Heiti") == "黑体"
    assert map_cjk_font("SimHei") == "黑体"
    assert map_cjk_font("Microsoft YaHei") == "微软雅黑"
    assert map_cjk_font("NotoSansCJKsc-Regular") == "微软雅黑"
    assert map_cjk_font("Droid Sans Fallback") == "微软雅黑"
    assert map_cjk_font("DengXian") == "等线"
    assert map_cjk_font("KaiTi") == "楷体"
    assert map_cjk_font("FangSong") == "仿宋"


def test_cjk_names_are_not_treated_as_latin() -> None:
    assert map_latin_font("Heiti") is None
    assert map_latin_font("SimSun") is None
    assert map_latin_font("宋体") is None


def test_unknown_fonts_fall_back_to_defaults() -> None:
    assert map_latin_font("SomeObscureFont") is None
    assert map_cjk_font("SomeObscureFont") is None
    latin, cjk = resolve_run_fonts(["SomeObscureFont"])
    assert latin == DEFAULT_LATIN_FONT
    assert cjk == DEFAULT_CJK_FONT


def test_resolve_run_fonts_uses_cjk_name_from_latin_slots() -> None:
    # pdf2docx writes the CJK font name into ascii/hAnsi as well.
    latin, cjk = resolve_run_fonts(["Heiti", "Heiti", "Heiti"])
    assert latin == DEFAULT_LATIN_FONT
    assert cjk == "黑体"


def test_resolve_run_fonts_keeps_recognized_latin_and_cjk() -> None:
    latin, cjk = resolve_run_fonts(["Times New Roman", "Times New Roman", "SimSun"])
    assert latin == "Times New Roman"
    assert cjk == "宋体"


def _make_styled_docx() -> bytes:
    document = Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("蓝色标题")
    run.bold = True
    run.italic = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0, 0, 0xCC)
    run.font.name = "ABCDEF+Heiti"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "ABCDEF+Heiti")

    mixed = document.add_paragraph()
    latin_run = mixed.add_run("Hello ")
    latin_run.font.name = "Helvetica"
    cjk_run = mixed.add_run("世界 123")
    cjk_run.font.name = "UnknownCJKFont"
    cjk_run._element.rPr.rFonts.set(qn("w:eastAsia"), "UnknownCJKFont")
    mixed.add_run("")  # empty run must not break normalization

    table = document.add_table(rows=1, cols=2)
    cell_run = table.cell(0, 0).paragraphs[0].add_run("单元格")
    cell_run.font.name = "Heiti"
    cell_run._element.rPr.rFonts.set(qn("w:eastAsia"), "Heiti")
    table.cell(0, 1).paragraphs[0].add_run("Cell")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _all_r_fonts(document: Document):
    return list(document.element.body.iter(qn("w:rFonts")))


def test_normalize_docx_rewrites_fonts_and_preserves_styles() -> None:
    normalized = Document(io.BytesIO(normalize_docx(_make_styled_docx())))

    heading = normalized.paragraphs[0]
    assert heading.text == "蓝色标题"
    run = heading.runs[0]
    assert run.bold is True
    assert run.italic is True
    assert run.font.size == Pt(20)
    assert run.font.color.rgb == RGBColor(0, 0, 0xCC)
    fonts = run._element.rPr.rFonts
    assert fonts.get(qn("w:ascii")) == DEFAULT_LATIN_FONT
    assert fonts.get(qn("w:hAnsi")) == DEFAULT_LATIN_FONT
    assert fonts.get(qn("w:eastAsia")) == "黑体"
    assert fonts.get(qn("w:cs")) == DEFAULT_LATIN_FONT


def test_normalize_docx_handles_mixed_runs_and_tables() -> None:
    normalized = Document(io.BytesIO(normalize_docx(_make_styled_docx())))

    mixed = normalized.paragraphs[1]
    assert mixed.text == "Hello 世界 123"
    latin_fonts = mixed.runs[0]._element.rPr.rFonts
    assert latin_fonts.get(qn("w:ascii")) == "Arial"
    cjk_fonts = mixed.runs[1]._element.rPr.rFonts
    assert cjk_fonts.get(qn("w:eastAsia")) == DEFAULT_CJK_FONT

    cell_run = normalized.tables[0].cell(0, 0).paragraphs[0].runs[0]
    assert cell_run.text == "单元格"
    assert cell_run._element.rPr.rFonts.get(qn("w:eastAsia")) == "黑体"
    assert normalized.tables[0].cell(0, 1).text == "Cell"

    for r_fonts in _all_r_fonts(normalized):
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            value = r_fonts.get(qn(attr))
            assert value is not None
            assert "+" not in value
            assert "Heiti" not in value
            assert "UnknownCJKFont" not in value


def _docx_with_line_spacing(line_twips: int, font_half_points: int) -> bytes:
    document = Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("行距测试")
    run.font.size = Pt(font_half_points / 2)
    spacing = paragraph._p.get_or_add_pPr().get_or_add_spacing()
    spacing.set(qn("w:line"), str(line_twips))
    spacing.set(qn("w:lineRule"), "exact")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _line_rule(docx_bytes: bytes) -> str | None:
    document = Document(io.BytesIO(docx_bytes))
    spacing = document.paragraphs[0]._p.pPr.spacing
    return spacing.get(qn("w:lineRule"))


def test_cramped_exact_line_spacing_becomes_at_least() -> None:
    # 12 pt font = 240 twips; 200 twips exact line height clips the glyphs.
    normalized = normalize_docx(_docx_with_line_spacing(200, 24))
    assert _line_rule(normalized) == "atLeast"


def test_comfortable_exact_line_spacing_is_kept() -> None:
    normalized = normalize_docx(_docx_with_line_spacing(400, 24))
    assert _line_rule(normalized) == "exact"


def test_normalize_docx_with_status_reports_success() -> None:
    data, normalized = normalize_docx_with_status(_make_styled_docx())

    assert normalized is True
    document = Document(io.BytesIO(data))
    fonts = document.paragraphs[0].runs[0]._element.rPr.rFonts
    assert fonts.get(qn("w:eastAsia")) == "黑体"
    assert "Heiti" not in document.element.xml


def test_normalize_docx_with_status_falls_back_to_valid_original() -> None:
    original = _make_styled_docx()
    with patch.object(font_normalizer, "normalize_docx", side_effect=RuntimeError("boom")):
        data, normalized = normalize_docx_with_status(original)

    assert normalized is False
    assert data == original
    # The returned fallback must still be a readable, editable DOCX.
    assert Document(io.BytesIO(data)).paragraphs[0].text == "蓝色标题"


def test_normalize_docx_with_status_raises_when_no_valid_file_exists() -> None:
    with pytest.raises(ConversionFailedError):
        normalize_docx_with_status(b"not a real docx package")


def test_font_repair_that_changes_content_falls_back_to_original(monkeypatch):
    original = _make_styled_docx()

    def changed(data):
        document = Document(io.BytesIO(data))
        document.paragraphs[0].text = "unexpected change"
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    monkeypatch.setattr(font_normalizer, "normalize_docx", changed)
    returned, normalized = normalize_docx_with_status(original)
    assert returned == original
    assert normalized is False
