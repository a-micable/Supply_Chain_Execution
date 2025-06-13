# NexusOps

Supply Chain Execution and Logistics Optimization Platform for global enterprise logistics operations.

## Overview

NexusOps coordinates warehouses, inventory networks, shipments, transportation, procurement, and fulfillment systems through an event-driven architecture with deep cross-domain workflows.

## Domains

- **Inventory Network** — allocation, reservation, safety stock, forecasting, multi-warehouse visibility
- **Fulfillment Engine** — order routing, planning, shipment generation, partial fulfillment
- **Transportation Management** — route planning, carrier assignment, consolidation, scheduling
- **Procurement System** — purchase orders, supplier management, replenishment, vendor performance
- **Warehouse Operations** — receiving, putaway, picking, packing, transfers
- **Optimization Engine** — cost, placement, transportation, capacity planning
- **Event Processing** — inventory, shipment, routing, forecast events
- **Audit & Compliance** — inventory/shipment history, planning decisions, manual overrides

## Stack

- Python 3.12 / FastAPI / SQLAlchemy 2.0 / PostgreSQL / Redis / Alembic / Pytest

## Quick Start

```bash
./scripts/dev.sh          # starts postgres+redis, migrates, runs tests
uvicorn nexusops.main:app --reload   # API on http://127.0.0.1:8000
# Docker API alternative: http://127.0.0.1:8001
```

Copy `.env.example` to `.env` if needed (Postgres on **localhost:5433** avoids system Postgres on 5432).

## API

Base path: `/api/v2`

| Endpoint | Description |
|----------|-------------|
| `POST /orders` | Create customer order |
| `POST /orders/{id}/fulfill` | Run fulfillment workflow |
| `GET /inventory/network/{sku_id}` | Network-wide inventory visibility |
| `POST /inventory/allocate` | Allocate inventory for order line |
| `POST /inventory/reconcile/{warehouse_id}` | Run reconciliation |
| `POST /shipments/{id}/route` | Plan delivery routes |
| `POST /optimization/run` | Execute optimization engine |

## Architecture

```
API Layer → Service Layer → Domain Engine → Repository Layer → PostgreSQL
                ↓                              ↑
           Event Bus ← Worker System → Redis Cache
                ↓
           Audit Trail
```

## License

Proprietary — NexusOps Engineering
