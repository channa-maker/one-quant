"""Tests for data/lineage.py — 数据血缘"""

import pytest

from one_quant.data.lineage import DataLineage, LineageEdge, LineageNode


@pytest.fixture
def lineage():
    return DataLineage()


# ── LineageNode ────────────────────────────────────────────────


class TestLineageNode:
    def test_creation(self):
        node = LineageNode(name="binance_ticker", node_type="source")
        assert node.name == "binance_ticker"
        assert node.node_type == "source"
        assert node.metadata == {}

    def test_with_metadata(self):
        node = LineageNode(name="x", node_type="bronze", metadata={"format": "parquet"})
        assert node.metadata["format"] == "parquet"


# ── LineageEdge ────────────────────────────────────────────────


class TestLineageEdge:
    def test_creation(self):
        src = LineageNode(name="a", node_type="source")
        tgt = LineageNode(name="b", node_type="bronze")
        edge = LineageEdge(source=src, target=tgt, transformation="raw_append")
        assert edge.source.name == "a"
        assert edge.target.name == "b"
        assert edge.transformation == "raw_append"
        assert edge.timestamp_ns == 0


# ── DataLineage ────────────────────────────────────────────────


class TestDataLineage:
    def test_register_node(self, lineage):
        node = LineageNode(name="binance", node_type="source")
        lineage.register_node(node)
        assert "binance" in lineage._nodes

    def test_record_creates_nodes_if_missing(self, lineage):
        lineage.record("src", "tgt", "transform", timestamp_ns=100)
        assert "src" in lineage._nodes
        assert "tgt" in lineage._nodes
        assert len(lineage._edges) == 1

    def test_record_uses_registered_nodes(self, lineage):
        src = LineageNode(name="a", node_type="source", metadata={"k": "v"})
        lineage.register_node(src)
        lineage.record("a", "b", "transform")
        assert lineage._nodes["a"].metadata == {"k": "v"}

    def test_trace_back(self, lineage):
        """Trace back from feature to source."""
        lineage.record("bronze_raw", "silver_clean", "clean")
        lineage.record("silver_clean", "gold_features", "compute")

        chain = lineage.trace_back("gold_features")
        assert len(chain) == 2
        assert chain[0].target.name == "gold_features"
        assert chain[0].source.name == "silver_clean"
        assert chain[1].target.name == "silver_clean"
        assert chain[1].source.name == "bronze_raw"

    def test_trace_back_no_chain(self, lineage):
        """Trace back on isolated node returns empty."""
        lineage.register_node(LineageNode(name="isolated", node_type="feature"))
        chain = lineage.trace_back("isolated")
        assert chain == []

    def test_trace_forward(self, lineage):
        """Trace forward from source to feature."""
        lineage.record("src", "bronze", "ingest")
        lineage.record("bronze", "silver", "clean")
        lineage.record("silver", "gold", "compute")

        chain = lineage.trace_forward("src")
        assert len(chain) == 3
        assert chain[0].source.name == "src"
        assert chain[-1].target.name == "gold"

    def test_trace_forward_no_chain(self, lineage):
        chain = lineage.trace_forward("nonexistent")
        assert chain == []

    def test_get_all_nodes(self, lineage):
        lineage.register_node(LineageNode(name="a", node_type="source"))
        lineage.register_node(LineageNode(name="b", node_type="bronze"))
        nodes = lineage.get_all_nodes()
        assert len(nodes) == 2
        names = {n.name for n in nodes}
        assert names == {"a", "b"}

    def test_get_all_edges(self, lineage):
        lineage.record("a", "b", "t1")
        lineage.record("b", "c", "t2")
        edges = lineage.get_all_edges()
        assert len(edges) == 2

    def test_trace_back_cycle_protection(self, lineage):
        """Cyclic edges don't cause infinite loop."""
        lineage.record("a", "b", "t1")
        lineage.record("b", "a", "t2")
        chain = lineage.trace_back("a")
        # Should terminate without hanging
        assert len(chain) >= 1

    def test_trace_forward_cycle_protection(self, lineage):
        lineage.record("a", "b", "t1")
        lineage.record("b", "a", "t2")
        chain = lineage.trace_forward("a")
        assert len(chain) >= 1
