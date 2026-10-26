"""Local environment configuration and an explicit, secret-safe authentication check."""

from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from motif_forge.config import Settings


class ModelSettingsData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["not_configured", "configured", "connected", "failed"]
    error_code: (
        Literal[
            "AUTHENTICATION_FAILED",
            "PROVIDER_UNAVAILABLE",
            "CONNECTION_FAILED",
            "INVALID_RESPONSE",
            "ENDPOINT_UNSUPPORTED",
        ]
        | None
    ) = None


class ModelSettingsResponse(BaseModel):
    data: ModelSettingsData


def build_model_settings_router(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/model-settings", tags=["settings"])

    @router.get("", response_model=ModelSettingsResponse)
    async def read_model_settings(response: Response) -> ModelSettingsResponse:
        response.headers["Cache-Control"] = "no-store"
        return ModelSettingsResponse(
            data=ModelSettingsData(
                state="configured" if settings.deepseek_configured else "not_configured",
            )
        )

    @router.post("/check", response_model=ModelSettingsResponse)
    async def check_model_settings(request: Request, response: Response) -> ModelSettingsResponse:
        # A custom header requires a CORS preflight; this local API does not allow CORS.
        if (
            request.headers.get("X-Motif-Configuration-Check") != "1"
            or request.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            raise HTTPException(
                status_code=403, detail="Explicit local configuration check required"
            )
        response.headers["Cache-Control"] = "no-store"
        if not settings.deepseek_configured:
            return ModelSettingsResponse(data=ModelSettingsData(state="not_configured"))
        if settings.deepseek_base_url.rstrip("/") not in (
            "https://api.deepseek.com",
            "https://api.deepseek.com/v1",
        ):
            return ModelSettingsResponse(
                data=ModelSettingsData(
                    state="failed",
                    error_code="ENDPOINT_UNSUPPORTED",
                )
            )
        assert settings.deepseek_api_key is not None
        error: (
            Literal[
                "AUTHENTICATION_FAILED",
                "PROVIDER_UNAVAILABLE",
                "CONNECTION_FAILED",
                "INVALID_RESPONSE",
                "ENDPOINT_UNSUPPORTED",
            ]
            | None
        ) = None
        try:
            async with httpx.AsyncClient(
                transport=transport,
                timeout=5.0,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                upstream = await client.get(
                    "https://api.deepseek.com/models",
                    headers={
                        "Authorization": "Bearer " + settings.deepseek_api_key.get_secret_value()
                    },
                )
            if upstream.status_code in (401, 403):
                error = "AUTHENTICATION_FAILED"
            elif upstream.status_code != 200:
                error = "PROVIDER_UNAVAILABLE"
            else:
                value = upstream.json()
                if (
                    not isinstance(value, dict)
                    or value.get("object") != "list"
                    or not isinstance(
                        value.get("data"),
                        list,
                    )
                ):
                    error = "INVALID_RESPONSE"
        except httpx.HTTPError:
            error = "CONNECTION_FAILED"
        except ValueError:
            error = "INVALID_RESPONSE"
        return ModelSettingsResponse(
            data=ModelSettingsData(
                state="connected" if error is None else "failed",
                error_code=error,
            )
        )

    return router
