"""Extended API endpoint tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from nexusops.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_health_returns_version():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v2/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["version"] == "2.14.3"


@pytest.mark.asyncio
async def test_correlation_id_header_echoed():
    transport = ASGITransport(app=app)
    cid = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v2/health",
            headers={"X-Correlation-ID": cid},
        )
    assert response.headers.get("X-Correlation-ID") == cid


@pytest.mark.asyncio
async def test_response_timing_header():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v2/health")
    assert "X-Response-Time-Ms" in response.headers


@pytest.mark.asyncio
async def test_optimization_endpoint_requires_body():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v2/optimization/run", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_order_requires_lines():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v2/orders", json={
            "external_order_id": "API-TEST-001",
            "customer_id": "CUST-API",
            "ship_to_address": {
                "street": "123 Main",
                "city": "Boston",
                "state": "MA",
                "postal_code": "02101",
            },
            "lines": [],
        })
    assert response.status_code == 422
