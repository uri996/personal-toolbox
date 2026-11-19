"""Exercise the semaphore failure observed in the deployed Python runtime."""
import asyncio
import errno
import io
import threading
from types import MethodType

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.main import create_app
from app.pdf_to_word import runtime
from app.pdf_to_word.errors import ConversionBusyError
from .conftest import PROCESS_CONVERT
from .synthetic_pdfs import chinese_paragraphs_pdf


def unavailable_pool(monkeypatch, code=errno.ENOENT):
    def fail(**kwargs):
        raise OSError(code, "synthetic unavailable semaphore")
    monkeypatch.setattr(runtime, "ProcessPoolExecutor", fail)


def test_vercel_without_semaphores_starts_and_converts(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    unavailable_pool(monkeypatch)
    app = create_app()
    runner = app.state.pdf_to_word_runner
    runner.convert = MethodType(PROCESS_CONVERT, runner)
    with TestClient(app) as client:
        response = client.post('/api/pdf-to-word/convert', files={
            'file': ('synthetic.pdf', chinese_paragraphs_pdf(), 'application/pdf')
        })
        assert client.get('/api/exchange-rates/INVALID').status_code == 400
    assert response.status_code == 200
    document = Document(io.BytesIO(response.content))
    assert '示例季度运营报告' in ''.join(p.text for p in document.paragraphs)


def test_serial_fallback_keeps_slot_after_cancellation(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    unavailable_pool(monkeypatch, errno.ENOSYS)
    started, release = threading.Event(), threading.Event()
    def blocked(*args):
        started.set()
        assert release.wait(5)
        return 'finished'
    monkeypatch.setattr(runtime, '_convert', blocked)
    runner = runtime.ConversionRunner()
    async def scenario():
        task = asyncio.create_task(PROCESS_CONVERT(runner, b'pdf', 'synthetic.pdf'))
        while not started.is_set():
            await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ConversionBusyError):
            await PROCESS_CONVERT(runner, b'pdf', 'synthetic.pdf')
        release.set()
        for _ in range(100):
            await asyncio.sleep(.01)
            if runner._slot.acquire(blocking=False):
                runner._slot.release()
                break
        else:
            pytest.fail('worker did not release its slot')
        assert await PROCESS_CONVERT(runner, b'pdf', 'synthetic.pdf') == 'finished'
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        runner.close()


@pytest.mark.parametrize('vercel,code', [('1', errno.EACCES), ('0', errno.ENOENT)])
def test_unrelated_pool_errors_are_not_hidden(monkeypatch, vercel, code):
    monkeypatch.setenv('VERCEL', vercel)
    unavailable_pool(monkeypatch, code)
    with pytest.raises(OSError) as caught:
        runtime.ConversionRunner()
    assert caught.value.errno == code
