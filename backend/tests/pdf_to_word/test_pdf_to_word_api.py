import io
from pathlib import Path

import pymupdf
from docx import Document
from fastapi.testclient import TestClient

from app.main import create_app
from app.pdf_to_word.service import MAX_FILE_SIZE


def _client() -> TestClient:
    return TestClient(create_app())


def _make_pdf(
    text: str = "PDF to Word conversion test",
    *,
    fontname: str = "helv",
    encrypt: bool = False,
    scan_like: bool = False,
) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    if scan_like:
        page.draw_rect(pymupdf.Rect(0, 0, 595, 842), color=(1, 1, 1), fill=(1, 1, 1))
    else:
        page.insert_font(fontname=fontname)
        page.insert_text((72, 72), text, fontsize=14, fontname=fontname)
    buffer = io.BytesIO()
    if encrypt:
        document.save(
            buffer,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )
    else:
        document.save(buffer)
    document.close()
    return buffer.getvalue()


def _docx_from_response(content: bytes) -> Document:
    return Document(io.BytesIO(content))


def test_converts_text_pdf_to_valid_docx_with_editable_text() -> None:
    pdf_bytes = _make_pdf("PDF to Word conversion test", fontname="helv")

    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    document = _docx_from_response(response.content)
    full_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "PDF to Word" in full_text


def test_preserves_chinese_text() -> None:
    pdf_bytes = _make_pdf("你好世界 PDF 转 Word 测试", fontname="china-s")

    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("中文.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    document = _docx_from_response(response.content)
    full_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "你好世界" in full_text
    assert "转 Word" in full_text


def test_content_disposition_uses_original_filename_with_docx_extension() -> None:
    pdf_bytes = _make_pdf()

    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("annual report.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''annual%20report.docx" in disposition


def test_rejects_empty_file() -> None:
    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert "空" in response.json()["detail"]


def test_rejects_non_pdf_file_by_signature() -> None:
    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("note.pdf", b"this is plain text", "application/pdf")},
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_rejects_non_pdf_extension_and_content() -> None:
    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("note.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 400


def test_rejects_oversized_file() -> None:
    oversized = b"%PDF-1.4\n" + b"x" * (MAX_FILE_SIZE + 1)

    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )

    assert response.status_code == 400
    assert "3 MB" in response.json()["detail"]


def test_rejects_encrypted_pdf() -> None:
    pdf_bytes = _make_pdf(encrypt=True)

    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("locked.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 400
    assert "加密" in response.json()["detail"]


def test_rejects_scanned_pdf_without_text_layer() -> None:
    pdf_bytes = _make_pdf(scan_like=True)

    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("scan.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 400
    assert "扫描" in response.json()["detail"]


def test_invalid_pdf_bytes_return_clear_error() -> None:
    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("broken.pdf", b"%PDF-1.4\n%not a real pdf", "application/pdf")},
    )

    assert response.status_code == 400


def test_conversion_does_not_leave_temp_files_in_temp_dir(
    monkeypatch,
) -> None:
    # The service operates fully in memory (BytesIO). Verify that no PDF/DOCX
    # temp files are created in the system temp directory during conversion.
    import tempfile

    pdf_bytes = _make_pdf("Temp file cleanup test")
    temp_dir = Path(tempfile.gettempdir())
    before = {p.name for p in temp_dir.iterdir() if p.is_file()}

    response = _client().post(
        "/api/pdf-to-word/convert",
        files={"file": ("cleanup.pdf", pdf_bytes, "application/pdf")},
    )

    after = {p.name for p in temp_dir.iterdir() if p.is_file()}
    assert response.status_code == 200
    # No new .pdf or .docx files should be left behind by our code path.
    new_files = after - before
    assert not any(name.endswith((".pdf", ".docx")) for name in new_files)
