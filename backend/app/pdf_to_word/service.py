import logging

from .converter import convert_pdf_to_docx, inspect_pdf
from .errors import (
    EmptyFileError,
    FileTooLargeError,
    InvalidPdfError,
    PdfToWordError,
    UnsupportedFileTypeError,
)

LOGGER = logging.getLogger(__name__)

MAX_FILE_SIZE = 3 * 1024 * 1024  # 3 MiB, below Vercel's ~4.5 MB request limit.
PDF_SIGNATURE = b"%PDF-"


class PdfToWordService:
    """Validate, inspect, and convert uploaded PDF files to DOCX."""

    def __init__(self, *, max_file_size: int = MAX_FILE_SIZE) -> None:
        self._max_file_size = max_file_size

    def convert(self, file_bytes: bytes, filename: str) -> bytes:
        self._validate(file_bytes, filename)
        inspect_pdf(file_bytes)
        return convert_pdf_to_docx(file_bytes)

    def _validate(self, file_bytes: bytes, filename: str) -> None:
        if not file_bytes:
            raise EmptyFileError

        if len(file_bytes) > self._max_file_size:
            raise FileTooLargeError

        if not self._is_pdf_signature(file_bytes) and not self._is_pdf_filename(filename):
            raise UnsupportedFileTypeError

        # Some PDFs may be prefixed with bytes before %PDF-; still require the
        # signature within the first kilobyte as a basic sanity check.
        if not self._is_pdf_signature(file_bytes) and PDF_SIGNATURE not in file_bytes[:1024]:
            raise InvalidPdfError

    @staticmethod
    def _is_pdf_signature(file_bytes: bytes) -> bool:
        return file_bytes.startswith(PDF_SIGNATURE)

    @staticmethod
    def _is_pdf_filename(filename: str) -> bool:
        return filename.lower().endswith(".pdf")


__all__ = ["PdfToWordService", "MAX_FILE_SIZE", "PdfToWordError"]
