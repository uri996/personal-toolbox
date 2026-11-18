import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.formparsers import MultiPartException

from .errors import (
    ERROR_MESSAGES,
    ConversionFailedError,
    ConversionBusyError,
    FileTooLargeError,
    OcrFailedError,
    OcrUnavailableError,
    PdfToWordError,
)
from .service import MAX_FILE_SIZE

LOGGER = logging.getLogger(__name__)

router = APIRouter()

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Signals whether the optional font repair step succeeded. Clients read this to
# warn the user without blocking the download of an otherwise valid document.
FONT_NORMALIZATION_HEADER = "X-Font-Normalization"

# Reports the OCR outcome: disabled | not-needed | applied | partial.
OCR_STATUS_HEADER = "X-Ocr-Status"

# Errors caused by the server-side engine rather than by the uploaded file.
_SERVER_ERROR_TYPES = (ConversionFailedError, OcrUnavailableError, OcrFailedError)


class UploadLimitMiddleware:
    """Bound multipart ingestion as well as the final in-memory file read."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/pdf-to-word/convert":
            return await self.app(scope, receive, send)
        limit = MAX_FILE_SIZE + 64 * 1024  # multipart names, headers and OCR flag
        headers = dict(scope.get("headers", ()))
        length = headers.get(b"content-length", b"0")
        if length.isdigit() and int(length) > limit:
            response = JSONResponse({"detail": ERROR_MESSAGES[FileTooLargeError]}, status_code=400)
            return await response(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                # The parser closes all spooled files on this exception.
                raise MultiPartException(ERROR_MESSAGES[FileTooLargeError])
            return message

        return await self.app(scope, bounded_receive, send)


@router.post("/api/pdf-to-word/convert")
async def convert_pdf_to_word(
    request: Request,
    file: UploadFile = File(...),
    ocr_enabled: Annotated[bool, Form()] = False,
) -> Response:
    filename = file.filename or "document.pdf"
    try:
        # UploadFile may already be spooled by the multipart parser. Read at
        # most the application limit plus one byte into conversion memory.
        raw_bytes = await file.read(MAX_FILE_SIZE + 1)
        if len(raw_bytes) > MAX_FILE_SIZE:
            raise FileTooLargeError
        outcome = await request.app.state.pdf_to_word_runner.convert(
            raw_bytes, filename, ocr_enabled=ocr_enabled
        )
    except PdfToWordError as error:
        message = ERROR_MESSAGES.get(type(error), "转换失败，请稍后重试。")
        # Input problems are client errors; engine/internal failures are 5xx.
        status_code = 500 if isinstance(error, _SERVER_ERROR_TYPES) else 400
        if isinstance(error, ConversionBusyError):
            status_code = 503
        raise HTTPException(status_code=status_code, detail=message) from error
    except Exception:
        LOGGER.exception("Unhandled pdf-to-word conversion error")
        raise HTTPException(status_code=500, detail="转换失败，请稍后重试。") from None
    finally:
        await file.close()

    docx_bytes = outcome.docx
    safe_name = _build_docx_filename(filename)
    content_disposition = _build_content_disposition(safe_name)

    return Response(
        content=docx_bytes,
        media_type=DOCX_CONTENT_TYPE,
        headers={
            "Content-Disposition": content_disposition,
            "Content-Length": str(len(docx_bytes)),
            FONT_NORMALIZATION_HEADER: (
                "applied" if outcome.fonts_normalized else "fallback"
            ),
            OCR_STATUS_HEADER: outcome.ocr_status,
        },
    )


def _build_docx_filename(original_filename: str) -> str:
    base = original_filename
    if base.lower().endswith(".pdf"):
        base = base[:-4]
    if not base:
        base = "document"
    return f"{base}.docx"


def _build_content_disposition(filename: str) -> str:
    # Use RFC 5987 encoding for non-ASCII filenames; also supply a fallback
    # ASCII name for older clients.
    ascii_fallback = "document.docx"
    encoded = quote(filename, safe="")
    return (
        f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'
    )


__all__ = ["router", "MAX_FILE_SIZE"]
