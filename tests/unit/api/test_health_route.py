import pytest
from httpx import ASGITransport, AsyncClient

from crystra_evolution.app import create_app


class StubCompute:
    async def compute(self, request: object) -> object:
        raise AssertionError(request)


@pytest.mark.asyncio
async def test_health_is_local_liveness_without_dependency_details() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(StubCompute())), base_url="http://evolution"
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "ok\n"


@pytest.mark.asyncio
async def test_unpublished_fastapi_surfaces_remain_absent() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app(StubCompute())), base_url="http://evolution"
    ) as client:
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")

    assert docs.status_code == 404
    assert schema.status_code == 404
