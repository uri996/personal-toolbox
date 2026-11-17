import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .exchange_rate.api import router as exchange_rate_router
from .exchange_rate.clients import production_bank_clients
from .exchange_rate.currencybeacon import CurrencyBeaconCache, CurrencyBeaconClient
from .exchange_rate.service import ExchangeRateService
from .pdf_to_word.api import router as pdf_to_word_router
from .pdf_to_word.service import PdfToWordService


DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


def create_app(service: ExchangeRateService | None = None) -> FastAPI:
    app = FastAPI(title="Personal Toolbox Exchange Rate API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.environ.get("FRONTEND_ORIGIN", DEFAULT_FRONTEND_ORIGIN)],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.state.exchange_rate_service = service or ExchangeRateService(
        production_bank_clients(),
        CurrencyBeaconCache(CurrencyBeaconClient()),
    )
    app.state.pdf_to_word_service = PdfToWordService()
    app.include_router(exchange_rate_router)
    app.include_router(pdf_to_word_router)
    return app


app = create_app()
