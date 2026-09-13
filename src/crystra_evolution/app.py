from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from crystra_evolution.api.models import ComputeRequest, ComputeResponse
from crystra_evolution.application import (
    ComputeService,
    ResolutionBoundExceeded,
    UpstreamContractMismatch,
    UpstreamUnavailable,
)


def _error(status: int, code: str, retryable: bool, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "retryable": retryable,
                "detail": detail[:2048],
            }
        },
    )


def create_app(service: object) -> FastAPI:
    compute_service = cast(ComputeService, service)
    app = FastAPI(
        title="crystra-evolution",
        version="0.1.1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz", response_class=PlainTextResponse)
    async def health() -> str:
        return "ok\n"

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: object, error: RequestValidationError) -> JSONResponse:
        details = [
            {
                "path": ".".join(str(part) for part in item["loc"]),
                "type": item["type"],
            }
            for item in error.errors()[:16]
        ]
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "retryable": False,
                    "detail": "request does not match evolution compute API v1",
                    "details": details,
                }
            },
        )

    @app.post(
        "/api/evolution/v1/evaluations:compute",
        response_model=ComputeResponse,
        response_model_exclude_none=True,
    )
    async def compute(request: ComputeRequest) -> ComputeResponse | JSONResponse:
        try:
            return await compute_service.compute(request)
        except UpstreamUnavailable as error:
            return _error(503, "UPSTREAM_UNAVAILABLE", True, str(error))
        except ResolutionBoundExceeded as error:
            return _error(413, "RESOLUTION_BOUND_EXCEEDED", False, str(error))
        except UpstreamContractMismatch as error:
            return _error(502, "UPSTREAM_INCOMPATIBLE", False, str(error))

    return app
