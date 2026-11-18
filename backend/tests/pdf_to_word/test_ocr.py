"""Deterministic recognition, classification, merge and status regressions."""
import io
from types import SimpleNamespace

import pymupdf
import pytest
from docx import Document

from app.pdf_to_word import ocr
from app.pdf_to_word.errors import OcrFailedError, OcrPageLimitError, OcrUnavailableError, ScannedPdfError
from app.pdf_to_word.ocr import OcrLine, ocr_image, recognize_pdf
from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts
from app.pdf_to_word.service import PdfToWordService
from tests.pdf_to_word import synthetic_pdfs as samples


class FakeEngine:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def __call__(self, image_bytes):
        result = self._results[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _result(lines, scores=None):
    return SimpleNamespace(
        txts=[text for text, _ in lines],
        boxes=[_box(*box) for _, box in lines],
        scores=[0.95] * len(lines) if scores is None else scores,
    )


def _tiny_image() -> bytes:
    with pymupdf.open() as document:
        page = document.new_page(width=200, height=200)
        page.insert_text((20, 110), "Synthetic image", fontsize=20)
        return page.get_pixmap().tobytes("png")


def _image_pdf(page_count: int) -> bytes:
    image_bytes = _tiny_image()
    with pymupdf.open() as document:
        for _ in range(page_count):
            page = document.new_page(width=200, height=200)
            page.insert_image(page.rect, stream=image_bytes)
        return document.tobytes()


def test_ocr_preserves_characters_and_whitespace():
    text = "  编号 Ａ - １0 2 4，5 - 3 = 2；1 2 3\t结束。  "
    lines = ocr_image(b"image", engine=FakeEngine([_result([(text, (0, 0, 100, 20))])]))
    assert lines[0].text == text
    result = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),)))
    assert paragraph_texts(Document(io.BytesIO(result.docx))) == [text]


def test_ocr_image_sorts_lines_into_reading_order():
    engine = FakeEngine([_result([("第二行", (10, 120, 200, 150)), ("右下", (260, 40, 420, 70)), ("左下", (10, 40, 200, 70))])])
    assert [line.text for line in ocr_image(b"image", engine=engine)] == ["左下", "右下", "第二行"]


@pytest.mark.parametrize("uncertain_index", range(10))
def test_ten_lines_retain_any_low_confidence_line_and_report_partial(uncertain_index):
    expected = [f"第{index}行，完整保留。" for index in range(10)]
    scores = [0.95] * 10
    scores[uncertain_index] = 0.1
    engine = FakeEngine([_result([(text, (10, 10 + index * 40, 180, 30 + index * 40)) for index, text in enumerate(expected)], scores)])
    prepared = recognize_pdf(_image_pdf(1), engine=engine)
    outcome = build_ocr_docx(prepared)
    assert outcome.ocr_status == "partial"
    assert paragraph_texts(Document(io.BytesIO(outcome.docx))) == expected


def test_missing_box_preserves_text_and_reports_uncertainty():
    engine = FakeEngine([SimpleNamespace(txts=["整行必须保留"], boxes=[], scores=[])])
    lines = ocr_image(b"image", engine=engine)
    assert lines[0].text == "整行必须保留"
    assert lines[0].uncertain


def test_ocr_image_wraps_engine_errors():
    with pytest.raises(OcrFailedError):
        ocr_image(b"image", engine=FakeEngine([RuntimeError("synthetic failure")]))


def test_scanned_page_limit_is_enforced():
    engine = FakeEngine([])
    with pytest.raises(OcrPageLimitError):
        recognize_pdf(_image_pdf(11), engine=engine)
    assert engine.calls == 0


def test_partial_failure_keeps_remaining_pages():
    prepared = recognize_pdf(_image_pdf(2), engine=FakeEngine([
        _result([("第一页文字", (10, 10, 150, 40))]), RuntimeError("page two failed")
    ]))
    assert prepared.pages[1].failed_regions == 1
    assert prepared.pages[1].fallback_image
    outcome = build_ocr_docx(prepared)
    assert outcome.ocr_status == "partial"
    document = Document(io.BytesIO(outcome.docx))
    assert "第一页文字" in paragraph_texts(document)
    assert len(document.inline_shapes) == 1
    assert len(document.sections) == 2


def test_empty_scan_keeps_original_information():
    prepared = recognize_pdf(_image_pdf(1), engine=FakeEngine([_result([])]))
    assert prepared.pages[0].empty_regions == 1
    assert prepared.pages[0].fallback_image
    outcome = build_ocr_docx(prepared)
    assert outcome.ocr_status == "partial"
    assert len(Document(io.BytesIO(outcome.docx)).inline_shapes) == 1


def test_mixed_nonzero_origin_deduplicates_only_equal_overlapping_text(monkeypatch):
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=600)
        page.insert_text((50, 150), "Native title")
        page.insert_image(pymupdf.Rect(40, 100, 300, 300), stream=_tiny_image(), keep_proportion=False)
        source = document.tobytes()
    native = OcrLine("Native title", (50, 140, 150, 160))
    monkeypatch.setattr(ocr, "_native_lines", lambda page: [native])
    monkeypatch.setattr(ocr.RenderBudget, "render", lambda *args, **kwargs: (b"image", 1.0, 1.0))
    engine = FakeEngine([_result([
        ("Native title", (10, 40, 110, 60)),
        ("Different content", (10, 40, 110, 60)),
    ])])
    prepared = recognize_pdf(source, engine=engine)
    assert prepared.pages[0].duplicate_lines == 1
    assert [line.text for line in prepared.pages[0].lines] == ["Native title", "Different content"]
    assert prepared.pages[0].lines[1].bbox == (50, 140, 150, 160)
    texts = paragraph_texts(Document(io.BytesIO(build_ocr_docx(prepared).docx)))
    assert texts == ["Native title", "Different content"]


def test_small_multiple_image_regions_and_partial_failure():
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 60), "Native title")
        for y in [100, 200]:
            page.insert_image(pymupdf.Rect(50, y, 100, y + 30), stream=_tiny_image())
        source = document.tobytes()
    engine = FakeEngine([_result([("Small image text", (0, 0, 80, 20))]), RuntimeError("second region")])
    prepared = recognize_pdf(source, engine=engine)
    assert engine.calls == 2
    assert prepared.pages[0].failed_regions == 1
    assert prepared.pages[0].fallback_image
    assert "Small image text" in [line.text for line in prepared.pages[0].lines]


def test_engine_is_created_once_and_disables_internal_filter(monkeypatch):
    import threading
    import rapidocr

    created = []
    class Engine:
        def __init__(self, **kwargs):
            created.append(kwargs)

    monkeypatch.setattr(rapidocr, "RapidOCR", Engine)
    ocr.reset_engine()
    try:
        results = []
        threads = [threading.Thread(target=lambda: results.append(ocr._get_engine())) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(created) == 1
        assert created[0]["params"]["Global.text_score"] == 0.0
        assert all(engine is results[0] for engine in results)
    finally:
        ocr.reset_engine()


def test_engine_initialization_failure_is_reported(monkeypatch):
    import rapidocr

    def broken(**kwargs):
        raise ImportError("synthetic initialization failure")
    monkeypatch.setattr(rapidocr, "RapidOCR", broken)
    ocr.reset_engine()
    try:
        with pytest.raises(OcrUnavailableError):
            ocr._get_engine()
    finally:
        ocr.reset_engine()


def test_service_rejects_scanned_pdf_when_ocr_disabled():
    with pytest.raises(ScannedPdfError):
        PdfToWordService().convert(samples.scanned_chinese_pdf(), "scan.pdf")


def test_service_reports_not_needed_without_loading_engine():
    ocr.reset_engine()
    outcome = PdfToWordService().convert(samples.chinese_paragraphs_pdf(), "text.pdf", ocr_enabled=True)
    assert outcome.ocr_status == "not-needed"
    assert ocr._engine is None



def test_xml_unsupported_line_is_recorded_and_original_page_is_retained():
    raw = "不能静默删除\x01原文"
    prepared = recognize_pdf(_image_pdf(1), engine=FakeEngine([_result([(raw, (0, 0, 100, 20))])]))
    page = prepared.pages[0]
    assert [line.text for line in page.rejected_lines] == [raw]
    assert page.fallback_image
    outcome = build_ocr_docx(prepared)
    assert outcome.ocr_status == "partial"
    assert len(Document(io.BytesIO(outcome.docx)).inline_shapes) == 1


def test_whitespace_distinguishes_numeric_fields_during_deduplication():
    native = OcrLine("123", (0, 0, 100, 20))
    recognized = OcrLine("1 2 3", (0, 0, 100, 20))
    assert not ocr._is_duplicate(recognized, [native])
