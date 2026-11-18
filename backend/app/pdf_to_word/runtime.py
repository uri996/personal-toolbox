"""Bound PDF processing to one isolated worker per application process.

PyMuPDF and the OCR singleton are used serially inside the child. A disconnected
request keeps its slot until the worker actually finishes. Worker crashes are
reported and the next request receives a fresh worker.
"""

import asyncio
import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from .errors import ConversionBusyError, ConversionFailedError
from .service import PdfToWordService


def _convert(file_bytes: bytes, filename: str, ocr_enabled: bool):
    return PdfToWordService().convert(file_bytes, filename, ocr_enabled=ocr_enabled)


def _new_pool() -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    )


class ConversionRunner:
    def __init__(self):
        self._slot = threading.BoundedSemaphore(1)
        self._pool = _new_pool()
        self._closed = False

    def _restart_pool(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
        if not self._closed:
            self._pool = _new_pool()

    def _job_finished(self, future):
        try:
            if not future.cancelled() and isinstance(future.exception(), BrokenProcessPool):
                self._restart_pool()
        finally:
            self._slot.release()

    async def convert(self, file_bytes: bytes, filename: str, *, ocr_enabled: bool = False):
        if not self._slot.acquire(blocking=False):
            raise ConversionBusyError
        try:
            future = self._pool.submit(_convert, file_bytes, filename, ocr_enabled)
        except BrokenProcessPool as error:
            self._restart_pool()
            self._slot.release()
            raise ConversionFailedError from error
        except Exception as error:
            self._slot.release()
            raise ConversionFailedError from error
        future.add_done_callback(self._job_finished)
        wrapped = asyncio.wrap_future(future)
        # Retrieve failures even when the HTTP caller has disconnected.
        wrapped.add_done_callback(_consume_exception)
        try:
            return await asyncio.shield(wrapped)
        except BrokenProcessPool as error:
            raise ConversionFailedError from error

    def close(self):
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)


def _consume_exception(future):
    if not future.cancelled():
        future.exception()
