"""Transportation route planning and optimization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.config.settings import get_settings
from nexusops.core.logging import get_logger
from nexusops.models.transportation import RoutePlan
from nexusops.repositories.transportation import CarrierRepository, RoutePlanRepository, ShipmentRepository

logger = get_logger(__name__)


@dataclass
class RouteStop:
    stop_id: uuid.UUID
    address: dict
    latitude: float
    longitude: float
    service_time_minutes: int = 15


@dataclass
class RouteOption:
    carrier_id: uuid.UUID
    stops: list[RouteStop]
    total_distance_km: Decimal
    total_duration_minutes: int
    estimated_cost: Decimal
    route_geometry: dict = field(default_factory=dict)


@dataclass
class RoutePlanningResult:
    shipment_id: uuid.UUID
    options: list[RouteOption]
    selected_option: RouteOption | None = None
    optimization_run_id: uuid.UUID | None = None


class RoutePlanner:
    """Plans delivery routes using graph-based optimization."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.shipment_repo = ShipmentRepository(session)
        self.carrier_repo = CarrierRepository(session)
        self.route_repo = RoutePlanRepository(session)
        self.settings = get_settings()

    async def plan_routes(self, shipment_id: uuid.UUID) -> RoutePlanningResult:
        shipment = await self.shipment_repo.get_with_stops(shipment_id)
        if shipment is None:
            raise ValueError(f"Shipment {shipment_id} not found")

        carriers = await self.carrier_repo.list_active()
        stops = self._build_stops(shipment)
        options: list[RouteOption] = []

        for carrier in carriers:
            option = self._compute_route(carrier.id, stops, carrier)
            options.append(option)

        options.sort(key=lambda o: o.estimated_cost)
        run_id = uuid.uuid4()

        result = RoutePlanningResult(
            shipment_id=shipment_id,
            options=options,
            selected_option=options[0] if options else None,
            optimization_run_id=run_id,
        )

        await self._persist_route_plans(shipment_id, options, run_id)
        if result.selected_option:
            await self._select_route(shipment_id, result.selected_option, run_id)

        logger.info(
            "routes_planned",
            shipment_id=str(shipment_id),
            option_count=len(options),
            selected_cost=str(result.selected_option.estimated_cost) if result.selected_option else None,
        )
        return result

    def _build_stops(self, shipment) -> list[RouteStop]:
        stops = []
        for stop in sorted(shipment.stops, key=lambda s: s.sequence):
            addr = stop.address
            stops.append(
                RouteStop(
                    stop_id=stop.id,
                    address=addr,
                    latitude=float(addr.get("latitude", 0)),
                    longitude=float(addr.get("longitude", 0)),
                )
            )
        return stops

    def _compute_route(self, carrier_id: uuid.UUID, stops: list[RouteStop], carrier) -> RouteOption:
        if len(stops) <= 1:
            return RouteOption(
                carrier_id=carrier_id,
                stops=stops,
                total_distance_km=Decimal("0"),
                total_duration_minutes=0,
                estimated_cost=Decimal("0"),
            )

        graph = nx.Graph()
        for i, stop_a in enumerate(stops):
            for j, stop_b in enumerate(stops):
                if i < j:
                    dist = self._haversine(
                        stop_a.latitude, stop_a.longitude,
                        stop_b.latitude, stop_b.longitude,
                    )
                    graph.add_edge(i, j, weight=dist)

        if len(stops) > self.settings.max_route_stops:
            ordered_indices = list(range(min(len(stops), self.settings.max_route_stops)))
        else:
            ordered_indices = self._solve_tsp(graph, len(stops))

        ordered_stops = [stops[i] for i in ordered_indices]
        total_distance = Decimal("0")
        total_duration = 0

        for i in range(len(ordered_stops) - 1):
            dist = self._haversine(
                ordered_stops[i].latitude, ordered_stops[i].longitude,
                ordered_stops[i + 1].latitude, ordered_stops[i + 1].longitude,
            )
            total_distance += Decimal(str(round(dist, 2)))
            total_duration += int(dist * 2) + ordered_stops[i].service_time_minutes

        cost_per_kg = carrier.cost_per_kg or Decimal("0.50")
        estimated_cost = total_distance * cost_per_kg + Decimal("25.00")

        return RouteOption(
            carrier_id=carrier_id,
            stops=ordered_stops,
            total_distance_km=total_distance,
            total_duration_minutes=total_duration,
            estimated_cost=estimated_cost,
            route_geometry={"ordered_stop_ids": [str(s.stop_id) for s in ordered_stops]},
        )

    def _solve_tsp(self, graph: nx.Graph, n: int) -> list[int]:
        if n <= 2:
            return list(range(n))
        try:
            path = nx.approximation.traveling_salesman_problem(
                graph, cycle=False, method=nx.approximation.greedy_tsp
            )
            return list(path)
        except Exception:
            return list(range(n))

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        import math
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        )
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    async def _persist_route_plans(
        self, shipment_id: uuid.UUID, options: list[RouteOption], run_id: uuid.UUID
    ) -> None:
        for i, option in enumerate(options):
            plan = RoutePlan(
                shipment_id=shipment_id,
                carrier_id=option.carrier_id,
                total_distance_km=option.total_distance_km,
                total_duration_minutes=option.total_duration_minutes,
                estimated_cost=option.estimated_cost,
                route_geometry=option.route_geometry,
                optimization_run_id=run_id,
                is_selected=(i == 0),
            )
            await self.route_repo.add(plan)

    async def _select_route(
        self, shipment_id: uuid.UUID, option: RouteOption, run_id: uuid.UUID
    ) -> None:
        plans = await self.route_repo.list_alternatives(shipment_id)
        for plan in plans:
            plan.is_selected = plan.carrier_id == option.carrier_id
