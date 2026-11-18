"""Recognition context stability and synthetic scan visibility regressions."""
import io

import pymupdf
from docx import Document
import pytest

from app.pdf_to_word import ocr
from app.pdf_to_word.service import MAX_FILE_SIZE
from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts
from .test_ocr_text_quality import _assert_model_quality
from .recognition_samples import dialogue_sample
from .synthetic_pdfs import punctuation_scan_pdf
from .quality_metrics import compact


@pytest.mark.parametrize("variant", ["clean", "low-dpi", "compressed", "blur", "skew", "scaled"])
def test_dialogue_variants_keep_their_visible_ground_truth(variant):
    sample = dialogue_sample(variant)
    assert len(sample.pdf) < MAX_FILE_SIZE
    assert len(sample.rows) == len(sample.expected_pages)
    for expected, rows in zip(sample.expected_pages, sample.rows):
        assert compact("".join(text for text, _ in rows)) == compact("".join(expected))
        for _, (x0, y0, x1, y1) in rows:
            assert 0 < x0 < x1 < 595
            assert 0 < y0 < y1 < 842


def test_same_line_recognition_is_independent_of_neighboring_batch_padding():
    engine = ocr._get_engine()
    with pymupdf.open(stream=punctuation_scan_pdf(), filetype="pdf") as source:
        image_bytes, _, _ = ocr.RenderBudget().render(source[0])
    image = engine.load_img(image_bytes)
    processed, operations = engine.preprocess_img(image)
    crops, _ = engine.detect_and_crop(processed, operations)
    classified, _ = engine.cls_and_rotate(crops)
    target = 1  # second physical row of this checked fixture
    alone = engine.recognize_txt([classified[target]])
    together = engine.recognize_txt(classified)
    assert together.txts[target] == alone.txts[0]
    assert together.scores[target] == pytest.approx(alone.scores[0], abs=1e-6)



@pytest.mark.parametrize("variant", ["clean", "low-dpi", "compressed", "blur", "skew", "scaled"])
def test_real_dense_dialogue_variants_keep_content_and_recognition_quality(variant):
    sample = dialogue_sample(variant)
    prepared = ocr.recognize_pdf(sample.pdf)
    expected_output = []
    for index, page in enumerate(prepared.pages):
        assert not page.failed_regions and not page.empty_regions
        if index:
            expected_output.append("")
        expected_output.extend(line.text for line in page.lines)
    final = paragraph_texts(Document(io.BytesIO(build_ocr_docx(prepared).docx)))
    assert final == expected_output
    expected = [line for page in sample.expected_pages for line in page]
    # The recorded batch-six stress baseline reached 6.9853% overall CER.
    # Keep that 7% envelope and the existing punctuation test's 20% line bound.
    # Detailed per-sample improvements and regressions remain in the diagnostic
    # comparison, so this guard is not a claim of perfect recognition.
    _assert_model_quality(expected, final, max_cer=0.07, max_line_error=0.20)
