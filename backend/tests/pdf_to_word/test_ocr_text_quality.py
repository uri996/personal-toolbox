"""Exact recognized-text fidelity and reference-based real OCR quality."""
import io
from types import SimpleNamespace

import pytest
from docx import Document

from app.pdf_to_word import ocr
from app.pdf_to_word.errors import ConversionFailedError, ScannedPdfError
from app.pdf_to_word.ocr import OcrDocument, OcrLine, OcrPage
from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts
from app.pdf_to_word.service import PdfToWordService
from .synthetic_pdfs import (
    DENSE_PARAGRAPHS, LONG_REPORT_PAGES, PUNCTUATION_LINES, REPORT_HEADER, REPORT_FOOTER,
    dense_chinese_scan_pdf, hidden_text_layer_scan_pdf, long_report_scan_pdf, punctuation_scan_pdf,
)
from .quality_metrics import character_errors, compact, contiguous_line_error, missing_lines
from .test_ocr import _image_pdf

FIDELITY_LINES = [
    "“中文双引号”与‘单引号’都应保留。",
    "省略号……与破折号——都不能丢失。",
    "书名《示例手册》与括号（圆括号）【方括号】。",
    "句读：问号？叹号！分号；冒号：顿号、逗号，句号。",
    "混排：Version v1.2，日期 2026 - 11 - 17，希腊字母 ν，比例 95%。",
    "序号：第一章、第二节、（三）、四、五、六、编号 ①。",
    "生僻字㐀𠀀🙂；1 2 3；5 - 3 = 2；Ａ　１２３。",
    "  首尾空格\t制表符\n换行  ",
]


class ScriptedEngine:
    def __init__(self, lines, *, x=40.0):
        self.lines = lines
        self.x = x

    def __call__(self, _image):
        boxes = [
            [[self.x, 40 + index * 40], [self.x + 200, 40 + index * 40],
             [self.x + 200, 60 + index * 40], [self.x, 60 + index * 40]]
            for index in range(len(self.lines))
        ]
        return SimpleNamespace(txts=self.lines, boxes=boxes, scores=[0.99] * len(self.lines))


def _output(prepared):
    return paragraph_texts(Document(io.BytesIO(build_ocr_docx(prepared).docx)))


def test_raw_ocr_to_docx_exact_unicode_whitespace_and_order():
    prepared = ocr.recognize_pdf(_image_pdf(1), engine=ScriptedEngine(FIDELITY_LINES))
    assert [line.text for line in prepared.pages[0].lines] == FIDELITY_LINES
    assert _output(prepared) == FIDELITY_LINES


def test_long_line_at_right_edge_is_preserved():
    text = "这是一条非常长的扫描文本行" * 100
    prepared = ocr.recognize_pdf(_image_pdf(1), engine=ScriptedEngine([text], x=5550))
    assert _output(prepared) == [text]


def test_many_pages_preserve_every_paragraph_exactly():
    pages = tuple(OcrPage(tuple(OcrLine(f"第{page}页第{line}段。" * 20, (0, line * 30, 500, line * 30 + 20))
                               for line in range(20)), attempted=True) for page in range(6))
    expected = []
    for index, page in enumerate(pages):
        if index:
            expected.append("")
        expected.extend(line.text for line in page.lines)
    assert _output(OcrDocument(pages)) == expected


def test_invalid_xml_character_fails_visibly():
    page = OcrPage((OcrLine("无法静默删除\x01字符", (0, 0, 100, 20)),), attempted=True)
    with pytest.raises(ConversionFailedError):
        build_ocr_docx(OcrDocument((page,)))


def test_font_normalization_fallback_retains_exact_ocr_text(monkeypatch):
    def broken(data):
        raise RuntimeError("synthetic normalizer failure")
    monkeypatch.setattr("app.pdf_to_word.font_normalizer.normalize_docx", broken)
    prepared = OcrDocument((OcrPage((OcrLine("㐀𠀀，完整保留。", (0, 0, 100, 20)),), attempted=True),))
    outcome = build_ocr_docx(prepared)
    assert outcome.fonts_normalized is False
    assert paragraph_texts(Document(io.BytesIO(outcome.docx))) == ["㐀𠀀，完整保留。"]


def test_font_enhancement_text_change_falls_back_to_exact_original(monkeypatch):
    def corrupt(data):
        document = Document(io.BytesIO(data))
        document.paragraphs[0].text = "被错误修改"
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue(), True
    monkeypatch.setattr("app.pdf_to_word.ocr_docx.normalize_docx_with_status", corrupt)
    prepared = OcrDocument((OcrPage((OcrLine("原始正确内容", (0, 0, 100, 20)),), attempted=True),))
    outcome = build_ocr_docx(prepared)
    assert outcome.fonts_normalized is False
    assert paragraph_texts(Document(io.BytesIO(outcome.docx))) == ["原始正确内容"]


def test_metrics_penalize_insertions_deletions_and_substitutions():
    assert character_errors("abc", "abX").substitutions == 1
    assert character_errors("abc", "ac").deletions == 1
    assert character_errors("abc", "abcjunk").insertions == 4
    assert character_errors("abc", "abcabc").cer == 1
    assert contiguous_line_error("abc", "aXXbYYc") > 0
    assert missing_lines(["第一段", "第二段"], "第一段") == ["第二段"]


@pytest.mark.parametrize("index", range(10))
def test_metrics_detect_any_missing_paragraph(index):
    actual = "".join(DENSE_PARAGRAPHS[:index] + DENSE_PARAGRAPHS[index + 1:])
    assert character_errors(compact("".join(DENSE_PARAGRAPHS)), compact(actual)).deletions > 0
    assert DENSE_PARAGRAPHS[index] in missing_lines(DENSE_PARAGRAPHS, actual)


def _assert_model_quality(expected_lines, actual_lines, *, max_cer, max_line_error):
    expected = compact("".join(expected_lines))
    actual = compact("".join(actual_lines))
    errors = character_errors(expected, actual)
    print(f"OCR CER={errors.cer:.6f} S={errors.substitutions} D={errors.deletions} I={errors.insertions}")
    punctuation = "“”‘’…—《》？！。，、；：（）【】"
    expected_marks = "".join(char for char in expected if char in punctuation)
    actual_marks = "".join(char for char in actual if char in punctuation)
    marks = character_errors(expected_marks, actual_marks)
    print(f"punctuation CER={marks.cer:.6f} S={marks.substitutions} D={marks.deletions} I={marks.insertions}")
    line_errors = [(line, contiguous_line_error(compact(line), actual)) for line in expected_lines]
    worst_line, worst_error = max(line_errors, key=lambda item: item[1])
    print(f"worst line CER={worst_error:.6f}; recognized codepoints={sum(map(len, actual_lines))}")
    assert errors.cer <= max_cer, errors
    assert worst_error <= max_line_error, f"line CER={worst_error:.4f}: {worst_line}"


def test_real_ocr_dense_chinese_page_keeps_every_paragraph():
    prepared = ocr.recognize_pdf(dense_chinese_scan_pdf())
    lines = _output(prepared)
    assert lines == [line.text for line in prepared.pages[0].lines]
    _assert_model_quality(DENSE_PARAGRAPHS, lines, max_cer=0.05, max_line_error=0.05)


def test_real_ocr_preserves_chinese_punctuation():
    prepared = ocr.recognize_pdf(punctuation_scan_pdf())
    lines = _output(prepared)
    assert lines == [line.text for line in prepared.pages[0].lines]
    _assert_model_quality(PUNCTUATION_LINES, lines, max_cer=0.12, max_line_error=0.20)
    text = "".join(lines)
    for char in "《》？！；：、，（）【】":
        assert char in text


def test_real_ocr_long_report_keeps_pages_complete_and_ordered():
    prepared = ocr.recognize_pdf(long_report_scan_pdf())
    lines = _output(prepared)
    expected = []
    recognized = []
    for index, (source, page) in enumerate(zip(LONG_REPORT_PAGES, prepared.pages)):
        assert not page.failed_regions and not page.empty_regions
        expected.extend([REPORT_HEADER.format(page=index + 1), *[text for text, _ in source], REPORT_FOOTER])
        if index:
            recognized.append("")
        recognized.extend(line.text for line in page.lines)
    assert lines == recognized
    _assert_model_quality(expected, lines, max_cer=0.05, max_line_error=0.10)
    text = compact("".join(lines))
    positions = [text.index(compact(page[0][0])) for page in LONG_REPORT_PAGES]
    assert positions == sorted(positions)
    assert all(text.count(compact(page[0][0])) == 1 for page in LONG_REPORT_PAGES)


def test_scan_with_hidden_text_layer_requires_ocr_when_off():
    with pytest.raises(ScannedPdfError):
        PdfToWordService().convert(hidden_text_layer_scan_pdf(), "hidden.pdf")


def test_scan_with_hidden_text_layer_is_recognized():
    prepared = ocr.recognize_pdf(hidden_text_layer_scan_pdf())
    lines = _output(prepared)
    assert "旧的错误文字层占位内容" not in "".join(lines)
    _assert_model_quality(DENSE_PARAGRAPHS[:4], lines, max_cer=0.05, max_line_error=0.05)
