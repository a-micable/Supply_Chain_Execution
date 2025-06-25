"""Cross-domain dependency graph for workflow consistency."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

import networkx as nx

from nexusops.core.exceptions import DependencyGraphError
from nexusops.core.logging import get_logger

logger = get_logger(__name__)


class NodeType(StrEnum):
    ORDER = "order"
    ALLOCATION = "allocation"
    FULFILLMENT_PLAN = "fulfillment_plan"
    SHIPMENT = "shipment"
    PURCHASE_ORDER = "purchase_order"
    TRANSFER = "transfer"
    WAREHOUSE_TASK = "warehouse_task"


@dataclass
class DependencyNode:
    node_id: uuid.UUID
    node_type: NodeType
    status: str
    metadata: dict = field(default_factory=dict)


class DependencyGraph:
    """Tracks cross-entity dependencies to detect inconsistencies."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()

    def add_node(self, node: DependencyNode) -> None:
        self.graph.add_node(
            str(node.node_id),
            node_type=node.node_type.value,
            status=node.status,
            **node.metadata,
        )

    def add_dependency(
        self, dependent_id: uuid.UUID, dependency_id: uuid.UUID, relation: str = "requires"
    ) -> None:
        self.graph.add_edge(str(dependency_id), str(dependent_id), relation=relation)

    def validate_no_cycles(self) -> None:
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            raise DependencyGraphError(
                f"Dependency cycle detected: {cycles[:3]}",
                details={"cycle_count": len(cycles)},
            )

    def get_upstream(self, node_id: uuid.UUID) -> list[str]:
        return list(nx.ancestors(self.graph, str(node_id)))

    def get_downstream(self, node_id: uuid.UUID) -> list[str]:
        return list(nx.descendants(self.graph, str(node_id)))

    def find_orphan_nodes(self) -> list[str]:
        orphans = []
        for node in self.graph.nodes:
            if self.graph.in_degree(node) == 0 and self.graph.out_degree(node) == 0:
                orphans.append(node)
        return orphans

    def validate_shipment_dependencies(self, shipment_id: uuid.UUID) -> list[str]:
        """Verify all upstream allocations are confirmed before shipment."""
        issues: list[str] = []
        upstream = self.get_upstream(shipment_id)
        for node_id in upstream:
            node_data = self.graph.nodes.get(node_id, {})
            if node_data.get("node_type") == NodeType.ALLOCATION.value:
                if node_data.get("status") != "confirmed":
                    issues.append(
                        f"Allocation {node_id} not confirmed for shipment {shipment_id}"
                    )
        return issues

    def topological_order(self) -> list[str]:
        self.validate_no_cycles()
        return list(nx.topological_sort(self.graph))
