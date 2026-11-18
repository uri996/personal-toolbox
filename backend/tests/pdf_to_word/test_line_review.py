"""Severe line review, false positives, source retention and real recovery."""
import io
import zipfile
from types import SimpleNamespace

import cv2
import numpy as np
import pymupdf
import pytest
from docx import Document

from app.pdf_to_word import ocr
from app.pdf_to_word.line_review import ReviewedEngine, line_evidence, MAX_LOCAL_RETRIES
from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts
from .catastrophic_samples import LONG_TEXT, severe_sample
from .quality_metrics import compact, character_errors


def crop_image(text=LONG_TEXT, inverted=False):
    font = pymupdf.Font(fontname="china-s")
    with pymupdf.open() as source:
        page = source.new_page(width=font.text_length(text, fontsize=11) + 24, height=40)
        writer = pymupdf.TextWriter(page.rect)
        writer.append((12, 24), text, font=font, fontsize=11)
        writer.write_text(page)
        pixmap = page.get_pixmap(dpi=150, alpha=False)
        pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3).copy()
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
    rows, columns = np.where(gray < 150)
    crop = pixels[rows.min():rows.max() + 1, columns.min():columns.max() + 1, ::-1].copy()
    crop = cv2.copyMakeBorder(crop, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return 255 - crop if inverted else crop


class ScriptedBase:
    """A deterministic pipeline with real image geometry and scripted OCR."""
    def __init__(self, crops, texts, candidate=LONG_TEXT, fail=False):
        self.crops = crops
        self.texts = texts
        self.candidate = candidate
        self.fail = fail
        self.local_calls = 0
        self.cfg = SimpleNamespace(Cls=SimpleNamespace(cls_thresh=0.9))

    def load_img(self, data):
        return self.crops[0]

    def preprocess_img(self, image):
        return image, {"preprocess": {"ratio_h": 1, "ratio_w": 1}}

    def run_ocr_steps(self, image, operations):
        width = image.shape[1]
        boxes = np.array([[[0, i * 50], [width, i * 50], [width, i * 50 + 30], [0, i * 50 + 30]]
                          for i in range(len(self.crops))], dtype=float)
        detected = SimpleNamespace(boxes=boxes)
        recognized = SimpleNamespace(txts=tuple(self.texts), scores=(0.99,) * len(self.texts))
        classified = SimpleNamespace(cls_res=[("0", 0.99)] * len(self.crops))
        return detected, classified, recognized, self.crops

    def cls_and_rotate(self, crops):
        return crops, None

    def recognize_txt(self, crops):
        self.local_calls += 1
        if self.fail:
            raise RuntimeError("synthetic local recognition failure")
        return SimpleNamespace(txts=(self.candidate,), scores=(0.99,))

    def build_final_output(self, original, detected, classified, recognized, crops, operations):
        valid = [index for index, text in enumerate(recognized.txts) if text.strip()]
        return SimpleNamespace(
            txts=tuple(recognized.txts[index] for index in valid),
            scores=tuple(recognized.scores[index] for index in valid),
            boxes=detected.boxes[valid],
        )


@pytest.mark.parametrize("text", ["OK", "Good day", "2026", "1          2          3",
                                  "A          B          C", "甲          乙          丙"])
@pytest.mark.parametrize("inverted", [False, True])
def test_optical_evidence_does_not_flag_short_or_spaced_text(text, inverted):
    assert line_evidence(crop_image(text, inverted), text) is None


def test_long_underline_does_not_turn_short_text_into_dense_text():
    image = crop_image("OK")
    canvas = np.full((image.shape[0] + 6, 900, 3), 255, dtype=np.uint8)
    canvas[:image.shape[0], :image.shape[1]] = image
    cv2.line(canvas, (0, image.shape[0]), (899, image.shape[0]), (0, 0, 0), 1)
    assert line_evidence(canvas, "OK") is None


def test_high_confidence_short_result_keeps_text_and_local_source_in_order():
    image = crop_image()
    base = ScriptedBase([image, crop_image("Following line")], ["短乱码", "Following line"], candidate="未恢复")
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(base))
    assert base.local_calls == 1
    assert lines[0].review and lines[0].review.retried
    assert not lines[0].review.recovered
    assert lines[0].text == "短乱码"
    prepared = ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),))
    outcome = build_ocr_docx(prepared)
    assert outcome.ocr_status == "partial"
    document = Document(io.BytesIO(outcome.docx))
    assert paragraph_texts(document) == ["短乱码", "", "Following line"]
    assert len(document.inline_shapes) == 1
    with zipfile.ZipFile(io.BytesIO(outcome.docx)) as archive:
        assert "短乱码" in archive.read("word/comments.xml").decode("utf-8")
        stored = archive.read(next(name for name in archive.namelist() if name.startswith("word/media/")))
    np.testing.assert_array_equal(cv2.imdecode(np.frombuffer(stored, np.uint8), 1), image)


def test_recovered_line_keeps_internal_evidence_but_no_word_image_or_comment():
    base = ScriptedBase([crop_image(inverted=True)], ["短乱码"])
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(base))
    assert base.local_calls == 2
    assert lines[0].text == LONG_TEXT
    assert lines[0].review.original_text == "短乱码"
    assert lines[0].review.recovered
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),)))
    assert outcome.ocr_status == "applied"
    document = Document(io.BytesIO(outcome.docx))
    assert paragraph_texts(document) == [LONG_TEXT]
    assert len(document.inline_shapes) == 0
    assert lines[0].review.image  # Evidence remains available for diagnostics.
    with zipfile.ZipFile(io.BytesIO(outcome.docx)) as archive:
        assert "word/comments.xml" not in archive.namelist()
        assert not any(name.startswith("word/media/") for name in archive.namelist())


def test_empty_detected_line_is_retained_for_source_fallback():
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(ScriptedBase([crop_image()], [""], candidate="")))
    assert len(lines) == 1
    assert lines[0].text == "" and lines[0].review
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),)))
    assert outcome.ocr_status == "partial"
    assert len(Document(io.BytesIO(outcome.docx)).inline_shapes) == 1


@pytest.mark.parametrize("fail,candidate", [(True, LONG_TEXT), (False, "无关内容" * 100)])
def test_unusable_retry_keeps_original_and_source(fail, candidate):
    base = ScriptedBase([crop_image(inverted=True)], ["短乱码"], fail=fail, candidate=candidate)
    line = ocr.ocr_image(b"image", engine=ReviewedEngine(base))[0]
    assert line.text == "短乱码"
    assert line.review.image and not line.review.recovered


def test_local_recognition_attempts_are_bounded():
    base = ScriptedBase([crop_image(inverted=True)] * 6, ["短乱码"] * 6)
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(base))
    assert base.local_calls == MAX_LOCAL_RETRIES
    assert len(lines) == 6
    assert all(line.review.image for line in lines)


def test_font_failure_still_downloads_reviewed_document(monkeypatch):
    def fail(data):
        raise RuntimeError("synthetic font enhancement failure")
    monkeypatch.setattr("app.pdf_to_word.font_normalizer.normalize_docx", fail)
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(ScriptedBase([crop_image()], ["短乱码"], candidate="未恢复")))
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),)))
    assert not outcome.fonts_normalized
    assert outcome.ocr_status == "partial"
    assert len(Document(io.BytesIO(outcome.docx)).inline_shapes) == 1


@pytest.mark.parametrize("variant", ["clear", "low-dpi", "compressed", "dark-gray"])
def test_real_fixed_long_lines_avoid_catastrophic_collapse_and_false_positives(variant):
    sample, regions = severe_sample(variant)
    prepared = ocr.recognize_pdf(sample.pdf)
    expected_output = []
    for line in prepared.pages[0].lines:
        expected_output.append(line.text)
        if line.unresolved_review:
            expected_output.append("")
    outcome = build_ocr_docx(prepared)
    assert paragraph_texts(Document(io.BytesIO(outcome.docx))) == expected_output
    for name, truth, (x0, y0, x1, y1) in regions:
        lines = [line for line in prepared.pages[0].lines if y0 <= (line.bbox[1] + line.bbox[3]) / 2 <= y1]
        actual = compact("".join(line.text for line in lines))
        if name.startswith("control"):
            assert not any(line.review for line in lines)
        else:
            assert character_errors(compact(truth), actual).cer <= 0.1
        if name != "inverted":
            assert not any(line.review for line in lines)
    if variant != "clear":
        reviewed = [line for line in prepared.pages[0].lines if line.review]
        assert len(reviewed) == 1 and reviewed[0].review.recovered
        assert outcome.ocr_status == prepared.status
        assert not any(line.unresolved_review for line in prepared.pages[0].lines)



def test_older_docx_without_comments_keeps_visible_initial_text_for_unresolved(monkeypatch):
    from docx.document import Document as DocumentClass
    monkeypatch.delattr(DocumentClass, "add_comment")
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(ScriptedBase([crop_image(inverted=True)], ["短乱码"], candidate="未恢复")))
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),)))
    document = Document(io.BytesIO(outcome.docx))
    texts = paragraph_texts(document)
    assert texts[0] == "短乱码"
    assert "初次识别：短乱码" in texts[1]
    assert len(document.inline_shapes) == 1 and outcome.ocr_status == "partial"


def test_overlapping_reviewed_text_keeps_one_line_and_original_evidence(monkeypatch):
    from .test_ocr import _image_pdf
    image = crop_image()
    _, encoded = cv2.imencode(".png", image)
    review = ocr.LineReview("短乱码", 0.99, encoded.tobytes(), "synthetic optical anomaly")
    native = ocr.OcrLine(LONG_TEXT, (10, 10, 150, 40))
    monkeypatch.setattr(ocr, "_native_lines", lambda page: [native])
    monkeypatch.setattr(ocr.RenderBudget, "render", lambda *args, **kwargs: (b"image", 1.0, 1.0))
    monkeypatch.setattr(ocr, "ocr_image", lambda *args, **kwargs: [ocr.OcrLine(LONG_TEXT, native.bbox, review=review)])
    prepared = ocr.recognize_pdf(_image_pdf(1))
    assert prepared.pages[0].duplicate_lines == 1
    assert len(prepared.pages[0].lines) == 1
    assert prepared.pages[0].lines[0].review == review
    outcome = build_ocr_docx(prepared)
    document = Document(io.BytesIO(outcome.docx))
    assert paragraph_texts(document) == [LONG_TEXT, ""]
    assert len(document.inline_shapes) == 1 and outcome.ocr_status == "partial"


def test_word_only_shows_source_and_initial_text_for_unresolved_review():
    _, png = cv2.imencode(".png", crop_image())
    source = png.tobytes()
    recovered = ocr.LineReview("已恢复前的乱码", 0.99, source, "review accepted", recovered=True)
    unresolved = ocr.LineReview(
        "未恢复的乱码", 0.99, source, "conflicting candidates",
        candidate_text=LONG_TEXT * 2,  # A longer candidate is not a success flag.
    )
    lines = (
        ocr.OcrLine("正常首行", (0, 0, 100, 20)),
        ocr.OcrLine(LONG_TEXT, (0, 30, 100, 50), review=recovered),
        ocr.OcrLine("未恢复的乱码", (0, 60, 100, 80), review=unresolved),
        ocr.OcrLine("正常末行", (0, 90, 100, 110)),
    )
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(lines, attempted=True),)))
    document = Document(io.BytesIO(outcome.docx))
    assert paragraph_texts(document) == ["正常首行", LONG_TEXT, "未恢复的乱码", "", "正常末行"]
    assert len(document.inline_shapes) == 1 and outcome.ocr_status == "partial"
    with zipfile.ZipFile(io.BytesIO(outcome.docx)) as archive:
        comments = archive.read("word/comments.xml").decode("utf-8")
        assert "未恢复的乱码" in comments
        assert "已恢复前的乱码" not in comments


def test_older_docx_successful_recovery_has_no_visible_initial_text_or_image(monkeypatch):
    from docx.document import Document as DocumentClass
    monkeypatch.delattr(DocumentClass, "add_comment")
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(ScriptedBase([crop_image()], ["短乱码"])))
    assert lines[0].review.recovered
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),)))
    document = Document(io.BytesIO(outcome.docx))
    assert paragraph_texts(document) == [LONG_TEXT]
    assert len(document.inline_shapes) == 0 and outcome.ocr_status == "applied"


@pytest.mark.parametrize("score,geometry_valid", [(0.2, True), (0.99, False)])
def test_recovery_does_not_hide_independent_uncertainty(score, geometry_valid):
    review = ocr.LineReview("初次乱码", 0.99, b"unused image", "accepted", recovered=True)
    line = ocr.OcrLine(LONG_TEXT, (0, 0, 100, 20), score, geometry_valid, review)
    assert line.uncertain and not line.unresolved_review
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage((line,), attempted=True),)))
    document = Document(io.BytesIO(outcome.docx))
    assert outcome.ocr_status == "partial"
    assert paragraph_texts(document) == [LONG_TEXT] and len(document.inline_shapes) == 0


def test_recovered_ocr_font_failure_keeps_font_warning_without_ocr_fallback(monkeypatch):
    def fail(data):
        raise RuntimeError("synthetic font enhancement failure")
    monkeypatch.setattr("app.pdf_to_word.font_normalizer.normalize_docx", fail)
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(ScriptedBase([crop_image()], ["短乱码"])))
    outcome = build_ocr_docx(ocr.OcrDocument((ocr.OcrPage(tuple(lines), attempted=True),)))
    assert not outcome.fonts_normalized and outcome.ocr_status == "applied"
    assert paragraph_texts(Document(io.BytesIO(outcome.docx))) == [LONG_TEXT]
