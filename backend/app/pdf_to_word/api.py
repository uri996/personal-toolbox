import logging
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from .errors import ERROR_MESSAGES, PdfToWordError
from .service import MAX_FILE_SIZE, PdfToWordService

LOGGER = logging.getLogger(__name__)

router = APIRouter()

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.post("/api/pdf-to-word/convert")
async def convert_pdf_to_word(
    request: Request,
    file: UploadFile = File(...),
) -> Response:
    service: PdfToWordService = request.app.state.pdf_to_word_service
    filename = file.filename or "document.pdf"

    raw_bytes = await file.read()

    try:
        docx_bytes = service.convert(raw_bytes, filename)
    except PdfToWordError as error:
        message = ERROR_MESSAGES.get(type(error), "转换失败，请稍后重试。")
        raise HTTPException(status_code=400, detail=message) from error
    except Exception:
        LOGGER.exception("Unhandled pdf-to-word conversion error")
        raise HTTPException(status_code=500, detail="转换失败，请稍后重试。") from None

    safe_name = _build_docx_filename(filename)
    content_disposition = _build_content_disposition(safe_name)

    return Response(
        content=docx_bytes,
        media_type=DOCX_CONTENT_TYPE,
        headers={
            "Content-Disposition": content_disposition,
            "Content-Length": str(len(docx_bytes)),
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
