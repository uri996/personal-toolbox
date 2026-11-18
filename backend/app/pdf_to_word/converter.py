import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import (
    ConversionFailedError,
    EncryptedPdfError,
    InvalidPdfError,
    PdfResourceLimitError,
    ScannedPdfError,
)

LOGGER = logging.getLogger(__name__)

# Minimum extractable text length to consider a PDF as having a real text layer.
# Scanned image PDFs contain no extractable text (0 characters), so a small
# positive threshold safely distinguishes them from short text documents.
MIN_TEXT_THRESHOLD = 5
MAX_PDF_PAGES = 100
MAX_PAGE_SIDE = 14400  # 200 inches, also bounds downstream image/layout operations.
MAX_IMAGES_PER_PAGE = 32
MAX_SOURCE_IMAGE_PIXELS = 40_000_000
MAX_TOTAL_SOURCE_IMAGE_PIXELS = 80_000_000


@dataclass(frozen=True)
class ConversionOutcome:
    """Converted document plus the result of the optional steps.

    ``fonts_normalized`` is False when the DOCX was produced successfully but
    the optional font repair failed, so the file is still valid and
    downloadable while needing a user-visible warning.

    ``ocr_status`` reports the OCR outcome: ``disabled`` when OCR was not
    requested, ``not-needed`` when requested but no page needed recognition,
    ``applied`` when recognized text was added, and ``partial`` when some pages
    could not be recognized or retained text needs review.
    """

    docx: bytes
    fonts_normalized: bool
    ocr_status: str = "disabled"


def inspect_pdf(pdf_bytes: bytes, *, allow_scanned: bool = False) -> None:
    """Open the PDF with PyMuPDF and raise domain errors for unsupported cases.

    Args:
        pdf_bytes: the raw PDF content.
        allow_scanned: when True (OCR enabled), documents without a text layer
            are accepted because recognition will supply the text instead.

    Raises:
        InvalidPdfError: the bytes are not a parseable PDF.
        EncryptedPdfError: the PDF requires a password.
        ScannedPdfError: the PDF has no meaningful extractable text and
            ``allow_scanned`` is False.
    """
    try:
        import pymupdf

        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as error:
        LOGGER.info("PDF parsing failed: %s", error)
        raise InvalidPdfError from error

    try:
        if document.is_encrypted:
            raise EncryptedPdfError
        if len(document) > MAX_PDF_PAGES:
            raise PdfResourceLimitError
        image_pixels = 0
        for page in document:
            if max(page.rect.width, page.rect.height) > MAX_PAGE_SIDE:
                raise PdfResourceLimitError
            images = page.get_image_info()
            if len(images) > MAX_IMAGES_PER_PAGE:
                raise PdfResourceLimitError
            page_pixels = sum(image["width"] * image["height"] for image in images)
            image_pixels += page_pixels
            if (
                page_pixels > MAX_SOURCE_IMAGE_PIXELS
                or image_pixels > MAX_TOTAL_SOURCE_IMAGE_PIXELS
            ):
                raise PdfResourceLimitError
        if not allow_scanned and not _has_extractable_text(document):
            raise ScannedPdfError
    finally:
        document.close()


def _has_extractable_text(document: Any) -> bool:
    """Return True when the document has enough *visible* text.

    Invisible text (render mode 3) does not count: scans often carry a hidden
    garbage text layer, and treating it as content would convert meaningless
    characters instead of asking the user to enable OCR.
    """
    visible = 0
    for page in document:
        text = (page.get_text("text") or "").strip()
        visible += _visible_char_count(page, len(text))
        if visible >= MIN_TEXT_THRESHOLD:
            return True
    return False


def _visible_char_count(page: Any, fallback: int) -> int:
    """Count characters drawn with a visible rendering mode.

    Falls back to the extracted text length when the page cannot be inspected,
    so an unusual but valid text PDF is never misclassified as a scan.
    """
    try:
        spans = page.get_texttrace()
    except Exception:
        return fallback
    if not spans:
        return fallback
    count = 0
    for span in spans:
        if span.get("type") == 3 or span.get("opacity", 1) == 0:
            continue
        chars = span.get("chars") or ()
        count += len("".join(chr(char[0]) for char in chars).strip())
    return count


def has_extractable_text(pdf_bytes: bytes) -> bool:
    """Return True when the PDF contains a usable text layer."""
    import pymupdf

    document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return _has_extractable_text(document)
    finally:
        document.close()


def convert_pdf_to_docx(
    pdf_bytes: bytes,
    *,
    converter_factory: Callable[[bytes], Any] | None = None,
) -> ConversionOutcome:
    """Convert PDF bytes to a DOCX document using pdf2docx.

    Args:
        pdf_bytes: the raw PDF content.
        converter_factory: optional factory for injecting a Converter in tests.

    Returns:
        The generated DOCX bytes together with the font repair status.

    Raises:
        EncryptedPdfError: the PDF requires a password.
        ConversionFailedError: the conversion engine failed, or it produced no
            valid DOCX that could be returned safely.
    """
    from pdf2docx import Converter
    from pdf2docx.converter import ConversionException

    from .font_normalizer import normalize_docx_with_status

    factory = converter_factory or (lambda data: Converter(stream=data))
    converter = factory(pdf_bytes)
    output = io.BytesIO()
    try:
        try:
            converter.convert(output, ignore_page_error=False)
        except ConversionException as error:
            message = str(error).lower()
            if "password" in message:
                raise EncryptedPdfError from error
            LOGGER.warning("pdf2docx conversion failed: %s", error)
            raise ConversionFailedError from error
        except Exception as error:
            LOGGER.exception("Unexpected pdf2docx failure")
            raise ConversionFailedError from error
    finally:
        converter.close()

    result = output.getvalue()
    if not result:
        raise ConversionFailedError
    docx_bytes, fonts_normalized = normalize_docx_with_status(result)
    return ConversionOutcome(docx=docx_bytes, fonts_normalized=fonts_normalized)
