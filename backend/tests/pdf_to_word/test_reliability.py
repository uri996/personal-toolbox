"""Page failures, resource budgets, isolated execution and download validity."""
import asyncio
import io
import zipfile
from concurrent.futures import Future

import pymupdf
import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.main import create_app
from app.pdf_to_word import ocr
from app.pdf_to_word.converter import convert_pdf_to_docx, inspect_pdf, MAX_IMAGES_PER_PAGE
from app.pdf_to_word.errors import ConversionBusyError, ConversionFailedError, PdfResourceLimitError
from app.pdf_to_word.font_normalizer import normalize_docx_with_status
from app.pdf_to_word.runtime import ConversionRunner
from .conftest import PROCESS_CONVERT
from .test_ocr import _image_pdf, _tiny_image
from .synthetic_pdfs import chinese_paragraphs_pdf


def test_second_page_parse_failure_is_never_silently_skipped(monkeypatch):
    from pdf2docx.page.Page import Page

    original = Page.parse
    def fail_second(self, **kwargs):
        if self.id == 1:
            raise RuntimeError("synthetic page error")
        return original(self, **kwargs)
    monkeypatch.setattr(Page, "parse", fail_second)
    with pymupdf.open() as source:
        for text in ["First page", "Second page must remain"]:
            source.new_page().insert_text((72, 72), text)
        data = source.tobytes()
    with pytest.raises(ConversionFailedError):
        convert_pdf_to_docx(data)


def test_malformed_docx_zip_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", b"invalid xml")
    with pytest.raises(ConversionFailedError):
        normalize_docx_with_status(buffer.getvalue())


def test_render_bounds_are_enforced_before_allocation(monkeypatch):
    class Page:
        rect = pymupdf.Rect(0, 0, 20000, 20000)
        def get_pixmap(self, **kwargs):
            matrix = kwargs["matrix"]
            assert self.rect.width * matrix.a <= ocr.MAX_RENDER_SIDE
            assert (self.rect.width * matrix.a) ** 2 <= ocr.MAX_RENDER_PIXELS
            raise RuntimeError("allocation boundary reached")
    with pytest.raises(RuntimeError, match="allocation boundary"):
        ocr.RenderBudget().render(Page())
    budget = ocr.RenderBudget(ocr.MAX_TOTAL_RENDER_PIXELS)
    with pytest.raises(PdfResourceLimitError):
        budget.render(Page())


def test_source_image_count_is_bounded():
    with pymupdf.open() as source:
        page = source.new_page()
        for index in range(MAX_IMAGES_PER_PAGE + 1):
            page.insert_image(pymupdf.Rect(10, 10 + index * 10, 20, 20 + index * 10), stream=_tiny_image())
        data = source.tobytes()
    with pytest.raises(PdfResourceLimitError):
        inspect_pdf(data, allow_scanned=True)


def test_large_multipart_is_rejected_before_conversion(monkeypatch):
    called = []
    async def convert(*args, **kwargs):
        called.append(True)
    monkeypatch.setattr(ConversionRunner, "convert", convert)
    response = TestClient(create_app()).post("/api/pdf-to-word/convert",
        files={"file": ("large.pdf", b"x" * (4 * 1024 * 1024), "application/pdf")})
    assert response.status_code == 400
    assert not called


def test_chunked_multipart_is_bounded():
    boundary = b"boundary"
    prefix = b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"large.pdf\"\r\nContent-Type: application/pdf\r\n\r\n"
    def chunks():
        yield prefix
        for _ in range(65):
            yield b"x" * 65536
        yield b"\r\n--" + boundary + b"--\r\n"
    response = TestClient(create_app()).post("/api/pdf-to-word/convert",
        headers={"Content-Type": "multipart/form-data; boundary=boundary"}, content=chunks())
    assert response.status_code == 400


def test_post_cors_exposes_download_and_warning_headers():
    client = TestClient(create_app())
    preflight = client.options("/api/pdf-to-word/convert", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 200
    response = client.post("/api/pdf-to-word/convert",
        headers={"Origin": "http://localhost:5173"},
        files={"file": ("sample.pdf", chinese_paragraphs_pdf(), "application/pdf")})
    assert response.status_code == 200
    exposed = response.headers["Access-Control-Expose-Headers"].lower()
    for header in ["content-disposition", "x-font-normalization", "x-ocr-status"]:
        assert header in exposed


def test_worker_slot_remains_busy_after_request_cancellation():
    runner = ConversionRunner()
    pending = Future()
    class Pool:
        def submit(self, *args):
            return pending
        def shutdown(self, **kwargs):
            pass
    runner.close()
    runner._pool = Pool()
    async def scenario():
        task = asyncio.create_task(PROCESS_CONVERT(runner, b"pdf", "sample.pdf"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ConversionBusyError):
            await PROCESS_CONVERT(runner, b"pdf", "sample.pdf")
        pending.set_result("done")
        await asyncio.sleep(0)
        assert runner._slot.acquire(blocking=False)
        runner._slot.release()
    asyncio.run(scenario())


def test_real_isolated_worker_keeps_event_loop_responsive():
    runner = ConversionRunner()
    async def scenario():
        task = asyncio.create_task(PROCESS_CONVERT(runner, chinese_paragraphs_pdf(), "sample.pdf"))
        ticks = 0
        while not task.done():
            await asyncio.sleep(0.01)
            ticks += 1
        outcome = await task
        assert ticks > 1
        assert "示例季度运营报告" in "".join(p.text for p in Document(io.BytesIO(outcome.docx)).paragraphs)
    try:
        asyncio.run(scenario())
    finally:
        runner.close()



def test_second_page_docx_creation_failure_is_never_silently_skipped(monkeypatch):
    from pdf2docx.page.Page import Page

    original = Page.make_docx
    def fail_second(self, *args):
        if self.id == 1:
            raise RuntimeError("synthetic creation error")
        return original(self, *args)
    monkeypatch.setattr(Page, "make_docx", fail_second)
    with pymupdf.open() as source:
        for text in ["First page", "Second page must remain"]:
            source.new_page().insert_text((72, 72), text)
        data = source.tobytes()
    with pytest.raises(ConversionFailedError):
        convert_pdf_to_docx(data)


@pytest.mark.parametrize("factory_name", ["styled_pdf", "table_pdf"])
def test_native_page_content_survives_assembly_with_scan(factory_name):
    from . import synthetic_pdfs
    from app.pdf_to_word.ocr import OcrDocument, OcrLine, OcrPage
    from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts

    factory = getattr(synthetic_pdfs, factory_name)
    native = convert_pdf_to_docx(factory())
    expected = paragraph_texts(Document(io.BytesIO(native.docx)))
    prepared = OcrDocument((
        OcrPage(native_pdf=factory()),
        OcrPage((OcrLine("扫描页完整文字㐀。", (0, 0, 100, 20)),), attempted=True),
    ))
    result = Document(io.BytesIO(build_ocr_docx(prepared).docx))
    assert paragraph_texts(result) == expected + ["", "扫描页完整文字㐀。"]
    assert len(result.sections) == 2
    if factory_name == "table_pdf":
        assert len(result.tables) == 1
    else:
        heading = next(run for paragraph in result.paragraphs for run in paragraph.runs if run.text == "蓝色标题示例")
        assert heading.font.size.pt == 20


def test_api_ocr_runs_through_the_real_isolated_worker():
    from types import MethodType
    from .synthetic_pdfs import scanned_chinese_pdf

    app = create_app()
    runner = app.state.pdf_to_word_runner
    runner.convert = MethodType(PROCESS_CONVERT, runner)
    with TestClient(app) as client:
        response = client.post("/api/pdf-to-word/convert", files={
            "file": ("synthetic.pdf", scanned_chinese_pdf(), "application/pdf")
        }, data={"ocr_enabled": "true"})
    assert response.status_code == 200
    assert response.headers["X-Ocr-Status"] == "applied"
    document = Document(io.BytesIO(response.content))
    assert "示例季度运营报告" in "".join(paragraph.text for paragraph in document.paragraphs)


def test_native_image_and_hyperlink_relationships_survive_page_assembly(monkeypatch):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    from app.pdf_to_word.converter import ConversionOutcome
    from app.pdf_to_word.ocr import OcrDocument, OcrPage
    from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts

    native = Document()
    paragraph = native.add_paragraph("Native ")
    rid = native.part.relate_to("https://example.test/", RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "link"
    run.append(text)
    link.append(run)
    paragraph._p.append(link)
    native.add_picture(io.BytesIO(_tiny_image()))
    buffer = io.BytesIO()
    native.save(buffer)
    monkeypatch.setattr("app.pdf_to_word.ocr_docx.convert_pdf_to_docx",
                        lambda data: ConversionOutcome(buffer.getvalue(), True))
    result = build_ocr_docx(OcrDocument((OcrPage(native_pdf=b"synthetic page"),)))
    document = Document(io.BytesIO(result.docx))
    assert paragraph_texts(document) == ["Native link", ""]
    assert len(document.inline_shapes) == 1
    assert any(relationship.is_external and relationship.target_ref == "https://example.test/"
               for relationship in document.part.rels.values())


def test_broken_worker_is_replaced_for_the_next_request(monkeypatch):
    from concurrent.futures.process import BrokenProcessPool
    from app.pdf_to_word import runtime

    failed = Future()
    failed.set_exception(BrokenProcessPool("synthetic worker failure"))
    recovered = Future()
    recovered.set_result("recovered")
    pending = [failed, recovered]

    class Pool:
        def __init__(self, **kwargs):
            pass

        def submit(self, *args):
            return pending.pop(0)

        def shutdown(self, **kwargs):
            pass

    monkeypatch.setattr(runtime, "ProcessPoolExecutor", Pool)
    runner = ConversionRunner()

    async def scenario():
        with pytest.raises(ConversionFailedError):
            await PROCESS_CONVERT(runner, b"pdf", "sample.pdf")
        assert await PROCESS_CONVERT(runner, b"pdf", "sample.pdf") == "recovered"

    try:
        asyncio.run(scenario())
    finally:
        runner.close()


def test_stream_overflow_closes_already_spooled_files(monkeypatch, tmp_path):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    prefix = (b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; "
              b"filename=\"large.pdf\"\r\nContent-Type: application/pdf\r\n\r\n")
    chunks = [prefix] + [b"x" * 65536] * 65
    messages = iter({"type": "http.request", "body": chunk, "more_body": True} for chunk in chunks)
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/api/pdf-to-word/convert",
        "raw_path": b"/api/pdf-to-word/convert", "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"multipart/form-data; boundary=boundary")],
        "server": ("testserver", 80), "client": ("testclient", 123),
    }
    asyncio.run(create_app()(scope, receive, send))
    assert sent[0]["status"] == 400
    assert not list(tmp_path.iterdir())
