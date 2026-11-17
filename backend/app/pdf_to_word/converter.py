import io
import logging
from collections.abc import Callable
from typing import Any

from .errors import (
    ConversionFailedError,
    EncryptedPdfError,
    InvalidPdfError,
    ScannedPdfError,
)

LOGGER = logging.getLogger(__name__)

# Minimum extractable text length to consider a PDF as having a real text layer.
# Scanned image PDFs contain no extractable text (0 characters), so a small
# positive threshold safely distinguishes them from short text documents.
MIN_TEXT_THRESHOLD = 5


def inspect_pdf(pdf_bytes: bytes) -> None:
    """Open the PDF with PyMuPDF and raise domain errors for unsupported cases.

    Raises:
        InvalidPdfError: the bytes are not a parseable PDF.
        EncryptedPdfError: the PDF requires a password.
        ScannedPdfError: the PDF has no meaningful extractable text.
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
        if not _has_extractable_text(document):
            raise ScannedPdfError
    finally:
        document.close()


def _has_extractable_text(document: Any) -> bool:
    total_chars = 0
    for page in document:
        text = page.get_text("text") or ""
        total_chars += len(text.strip())
        if total_chars >= MIN_TEXT_THRESHOLD:
            return True
    return False


def convert_pdf_to_docx(
    pdf_bytes: bytes,
    *,
    converter_factory: Callable[[bytes], Any] | None = None,
) -> bytes:
    """Convert PDF bytes to DOCX bytes using pdf2docx.

    Args:
        pdf_bytes: the raw PDF content.
        converter_factory: optional factory for injecting a Converter in tests.

    Returns:
        The generated DOCX file bytes.

    Raises:
        EncryptedPdfError: the PDF requires a password.
        ConversionFailedError: the conversion engine failed.
    """
    from pdf2docx import Converter
    from pdf2docx.converter import ConversionException

    factory = converter_factory or (lambda data: Converter(stream=data))
    converter = factory(pdf_bytes)
    output = io.BytesIO()
    try:
        try:
            converter.convert(output)
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
    return result
