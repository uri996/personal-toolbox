"""Synthetic direction failures: true rotations, conflicts, confidence and caps."""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.pdf_to_word import ocr
from app.pdf_to_word.line_review import MAX_LOCAL_RETRIES, ReviewedEngine
from .catastrophic_samples import LONG_TEXT
from .test_line_review import ScriptedBase, crop_image


class DirectionBase(ScriptedBase):
    """Read only the exact upright synthetic pixels; wrong inputs get nonsense."""

    def __init__(self, source_rotation, classified_label, *, dark=False, short_length=10):
        self.truth = LONG_TEXT * 2
        self.upright = crop_image(self.truth)
        source = 255 - self.upright if dark else self.upright.copy()
        if source_rotation:
            source = cv2.rotate(source, cv2.ROTATE_180)
        self.short = "甲乙丙丁戊己庚辛壬癸子丑"[:short_length]
        self.label = classified_label
        classified = cv2.rotate(source, cv2.ROTATE_180) if self.label == "180" else source
        initial = self.truth if np.array_equal(classified, self.upright) else self.short
        super().__init__([source], [initial])
        self.seen_local = []

    def run_ocr_steps(self, image, operations):
        detected, _, recognized, crops = super().run_ocr_steps(image, operations)
        recognized.scores = (0.9999,)
        return detected, SimpleNamespace(cls_res=[(self.label, 0.99999)]), recognized, crops

    def cls_and_rotate(self, crops):
        raise AssertionError("local review must not reapply the faulty classifier")

    def recognize_txt(self, crops):
        self.local_calls += 1
        self.seen_local.append(crops[0].copy())
        text = self.truth if np.array_equal(crops[0], self.upright) else self.short
        return SimpleNamespace(txts=(text,), scores=(0.9999,))


@pytest.mark.parametrize("short_length", [9, 10, 12])
@pytest.mark.parametrize("source_rotation,label", [(0, "180"), (180, "0")])
def test_high_confidence_wrong_white_direction_recovers_from_optical_collapse(short_length, source_rotation, label):
    base = DirectionBase(source_rotation, label, short_length=short_length)
    line = ocr.ocr_image(b"image", engine=ReviewedEngine(base))[0]
    assert line.text == base.truth
    assert base.local_calls == 1
    assert np.array_equal(base.seen_local[0], base.upright)
    assert line.review.recovered and not line.uncertain
    assert line.review.orientation_score == 0.99999
    assert line.review.original_score == 0.9999
    assert line.review.original_text == base.short
    assert line.review.selected_rotation == source_rotation
    assert line.review.method == "orientation"
    assert line.review.attempts == len(line.review.candidates) == 1


@pytest.mark.parametrize("source_rotation,label", [(0, "0"), (0, "180"), (180, "0"), (180, "180")])
def test_dark_polarity_review_checks_both_directions_without_classifier(source_rotation, label):
    base = DirectionBase(source_rotation, label, dark=True)
    line = ocr.ocr_image(b"image", engine=ReviewedEngine(base))[0]
    assert line.text == base.truth
    assert line.review.recovered and line.review.method == "polarity+orientation"
    assert line.review.selected_rotation == source_rotation
    assert base.local_calls == line.review.attempts == 2
    assert all(item.polarity_inverted for item in line.review.candidates)
    assert sum(item.eligible for item in line.review.candidates) == 1


@pytest.mark.parametrize("source_rotation,label", [(0, "0"), (180, "180")])
def test_correct_upright_and_genuinely_inverted_lines_keep_initial_classification(source_rotation, label):
    base = DirectionBase(source_rotation, label)
    line = ocr.ocr_image(b"image", engine=ReviewedEngine(base))[0]
    assert line.text == base.truth
    assert line.review is None and not line.uncertain
    assert base.local_calls == 0


class CandidateBase(ScriptedBase):
    def __init__(self, candidates):
        super().__init__([crop_image(inverted=True)], ["短乱码"])
        self.results = iter(candidates)

    def recognize_txt(self, crops):
        self.local_calls += 1
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        text, score = result
        return SimpleNamespace(txts=(text,), scores=(score,))


def test_two_conflicting_plausible_directions_are_not_resolved_by_length_or_score():
    base = CandidateBase([(LONG_TEXT, 0.99), (LONG_TEXT.replace("蓝", "绿"), 0.999)])
    line = ocr.ocr_image(b"image", engine=ReviewedEngine(base))[0]
    assert line.text == "短乱码"
    assert not line.review.recovered and line.review.image
    assert "conflicting" in line.review.reason
    assert all(item.eligible for item in line.review.candidates)


@pytest.mark.parametrize("candidates", [
    [("未恢复", 0.99), ("仍失败", 0.99)],
    [(LONG_TEXT, 0.79), (LONG_TEXT, 0.79)],
    [(LONG_TEXT * 10, 0.999), ("仍失败", 0.99)],
    [RuntimeError("synthetic failed direction"), (LONG_TEXT, 0.99)],
])
def test_unreliable_or_incomplete_comparison_keeps_initial_and_source(candidates):
    base = CandidateBase(candidates)
    line = ocr.ocr_image(b"image", engine=ReviewedEngine(base))[0]
    assert line.text == "短乱码"
    assert not line.review.recovered and line.review.image
    assert line.uncertain and base.local_calls == 2


def test_white_retry_budget_is_per_ocr_input_and_has_no_loop():
    base = ScriptedBase([crop_image()] * 6, ["短乱码"] * 6)
    lines = ocr.ocr_image(b"image", engine=ReviewedEngine(base))
    assert base.local_calls == MAX_LOCAL_RETRIES
    assert sum(line.review.attempts for line in lines) == MAX_LOCAL_RETRIES
    assert len(lines) == 6 and all(line.review.image for line in lines)
    assert all("budget" in line.review.reason for line in lines[MAX_LOCAL_RETRIES:])


@pytest.mark.parametrize("rotation", [0, 180])
@pytest.mark.parametrize("dark", [False, True])
def test_real_small_model_reads_upright_and_truly_inverted_synthetic_pdf(rotation, dark):
    import io
    import pymupdf
    from docx import Document
    from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts
    from .quality_metrics import character_errors, compact
    from .synthetic_pdfs import _image_only_pdf

    with pymupdf.open() as source:
        page = source.new_page()
        if dark:
            page.draw_rect(pymupdf.Rect(43, 136, 545, 155), fill=(0, 0, 0), color=(0, 0, 0))
        writer = pymupdf.TextWriter(page.rect)
        writer.append((48, 150), LONG_TEXT, font=pymupdf.Font(fontname="china-s"), fontsize=11)
        writer.write_text(page, color=(1, 1, 1) if dark else (0, 0, 0))
        pix = page.get_pixmap(dpi=150, alpha=False)
        image = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    if rotation:
        image = cv2.rotate(image, cv2.ROTATE_180)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    prepared = ocr.recognize_pdf(_image_only_pdf([encoded.tobytes()]))
    lines = prepared.pages[0].lines
    assert len(lines) == 1
    assert character_errors(compact(LONG_TEXT), compact(lines[0].text)).cer <= 0.1
    outcome = build_ocr_docx(prepared)
    expected = [lines[0].text] + ([""] if lines[0].unresolved_review else [])
    assert paragraph_texts(Document(io.BytesIO(outcome.docx))) == expected
