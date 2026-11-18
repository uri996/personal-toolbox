import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .exchange_rate.api import router as exchange_rate_router
from .exchange_rate.clients import production_bank_clients
from .exchange_rate.currencybeacon import CurrencyBeaconCache, CurrencyBeaconClient
from .exchange_rate.service import ExchangeRateService
from .pdf_to_word.api import UploadLimitMiddleware, router as pdf_to_word_router
from .pdf_to_word.service import PdfToWordService
from .pdf_to_word.runtime import ConversionRunner


DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


def create_app(service: ExchangeRateService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        yield
        application.state.pdf_to_word_runner.close()

    app = FastAPI(title="Personal Toolbox Exchange Rate API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(UploadLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.environ.get("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN)],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Font-Normalization", "X-Ocr-Status"],
    )
    app.state.exchange_rate_service = service or ExchangeRateService(
        production_bank_clients(),
        CurrencyBeaconCache(CurrencyBeaconClient()),
    )
    app.state.pdf_to_word_service = PdfToWordService()
    app.state.pdf_to_word_runner = ConversionRunner()
    app.include_router(exchange_rate_router)
    app.include_router(pdf_to_word_router)
    return app


app = create_app()
