"""Dependency graph tests."""

from __future__ import annotations

import uuid

import pytest

from nexusops.core.dependency_graph import DependencyGraph, DependencyNode, NodeType
from nexusops.core.exceptions import DependencyGraphError


def test_add_nodes_and_dependencies():
    graph = DependencyGraph()
    order_id = uuid.uuid4()
    alloc_id = uuid.uuid4()
    ship_id = uuid.uuid4()

    graph.add_node(DependencyNode(order_id, NodeType.ORDER, "received"))
    graph.add_node(DependencyNode(alloc_id, NodeType.ALLOCATION, "confirmed"))
    graph.add_node(DependencyNode(ship_id, NodeType.SHIPMENT, "planned"))

    graph.add_dependency(ship_id, alloc_id)
    graph.add_dependency(alloc_id, order_id)

    graph.validate_no_cycles()
    upstream = graph.get_upstream(ship_id)
    assert str(alloc_id) in upstream


def test_cycle_detection_raises():
    graph = DependencyGraph()
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    graph.add_node(DependencyNode(a, NodeType.ORDER, "active"))
    graph.add_node(DependencyNode(b, NodeType.ALLOCATION, "active"))
    graph.add_node(DependencyNode(c, NodeType.SHIPMENT, "active"))

    graph.add_dependency(b, a)
    graph.add_dependency(c, b)
    graph.add_dependency(a, c)

    with pytest.raises(DependencyGraphError):
        graph.validate_no_cycles()


def test_shipment_dependency_validation():
    graph = DependencyGraph()
    alloc_id = uuid.uuid4()
    ship_id = uuid.uuid4()

    graph.add_node(DependencyNode(alloc_id, NodeType.ALLOCATION, "pending"))
    graph.add_node(DependencyNode(ship_id, NodeType.SHIPMENT, "planned"))
    graph.add_dependency(ship_id, alloc_id)

    issues = graph.validate_shipment_dependencies(ship_id)
    assert len(issues) == 1
    assert "not confirmed" in issues[0]


def test_topological_order():
    graph = DependencyGraph()
    ids = [uuid.uuid4() for _ in range(3)]
    for i, nid in enumerate(ids):
        graph.add_node(DependencyNode(nid, NodeType.ORDER, "active"))
    graph.add_dependency(ids[2], ids[1])
    graph.add_dependency(ids[1], ids[0])

    order = graph.topological_order()
    assert order.index(str(ids[0])) < order.index(str(ids[2]))
