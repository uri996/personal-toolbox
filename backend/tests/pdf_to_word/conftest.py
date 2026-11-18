import pytest

from app.pdf_to_word.runtime import ConversionRunner
from app.pdf_to_word.service import PdfToWordService

# Keep monkeypatched recognition/conversion visible in API tests. Actual worker
# spawning, cancellation and admission are exercised separately in test_runtime.
PROCESS_CONVERT = ConversionRunner.convert


@pytest.fixture(autouse=True)
def inline_api_conversion(monkeypatch):
    async def convert(self, data, filename, *, ocr_enabled=False):
        return PdfToWordService().convert(data, filename, ocr_enabled=ocr_enabled)

    monkeypatch.setattr(ConversionRunner, "convert", convert)
