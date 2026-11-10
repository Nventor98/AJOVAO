from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.api.auth import profile_router, router as auth_router
from app.api.catalogue import router as catalogue_router
from app.api.health import router as health_router
from app.api.identity import router as identity_router
from app.api.purchasing import router as purchasing_router
from app.shared.responses import APIError


def create_app() -> FastAPI:
    app = FastAPI(
        title="NaijaLife AI API",
        version="0.1.0",
        description="Shared backend foundation for NaijaLife AI.",
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(identity_router)
    app.include_router(catalogue_router)
    app.include_router(purchasing_router)

    @app.get("/")
    async def root() -> dict:
        return {"success": True, "data": {"message": "NaijaLife AI backend foundation is live."}, "meta": {}}

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=400, content=exc.to_dict())

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        code = {
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            503: "SERVICE_UNAVAILABLE",
        }.get(exc.status_code, "REQUEST_ERROR")
        body = {"success": False, "error": {"code": code, "message": detail, "details": []}}
        headers = exc.headers or {}
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"location": [str(part) for part in error.get("loc", ())], "message": error.get("msg", "Invalid value.")}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The supplied request is invalid.",
                    "details": errors,
                },
            },
        )

    return app


app = create_app()
