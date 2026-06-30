"""数据血缘记录 — 因子→Silver→Bronze→数据源 全程可追溯"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LineageNode:
    """血缘节点"""

    name: str
    node_type: str  # "source", "bronze", "silver", "gold", "feature"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LineageEdge:
    """血缘边：描述数据流转关系"""

    source: LineageNode
    target: LineageNode
    transformation: str  # 转换描述
    timestamp_ns: int = 0


class DataLineage:
    """数据血缘管理器。

    记录数据从源头到最终特征的完整流转路径。
    支持正向追踪（数据去哪了）和反向溯源（数据从哪来）。
    """

    def __init__(self) -> None:
        self._edges: list[LineageEdge] = []
        self._nodes: dict[str, LineageNode] = {}

    def register_node(self, node: LineageNode) -> None:
        """注册血缘节点"""
        self._nodes[node.name] = node

    def record(
        self,
        source_name: str,
        target_name: str,
        transformation: str,
        timestamp_ns: int = 0,
    ) -> None:
        """记录数据流转关系。

        Args:
            source_name: 源节点名
            target_name: 目标节点名
            transformation: 转换描述
            timestamp_ns: 时间戳
        """
        source = self._nodes.get(source_name)
        target = self._nodes.get(target_name)

        if not source:
            source = LineageNode(name=source_name, node_type="unknown")
            self._nodes[source_name] = source
        if not target:
            target = LineageNode(name=target_name, node_type="unknown")
            self._nodes[target_name] = target

        edge = LineageEdge(
            source=source,
            target=target,
            transformation=transformation,
            timestamp_ns=timestamp_ns,
        )
        self._edges.append(edge)

    def trace_back(self, feature_name: str) -> list[LineageEdge]:
        """反向溯源：从特征追溯到原始数据源。

        Args:
            feature_name: 特征名称

        Returns:
            血缘链（从特征到源头）
        """
        chain: list[LineageEdge] = []
        current = feature_name
        visited: set[str] = set()

        while current and current not in visited:
            visited.add(current)
            # 找到指向 current 的边
            found = None
            for edge in reversed(self._edges):
                if edge.target.name == current:
                    found = edge
                    break
            if found:
                chain.append(found)
                current = found.source.name
            else:
                break

        return chain

    def trace_forward(self, source_name: str) -> list[LineageEdge]:
        """正向追踪：从源头追踪到下游特征。

        Args:
            source_name: 源节点名

        Returns:
            血缘链（从源头到特征）
        """
        chain: list[LineageEdge] = []
        current = source_name
        visited: set[str] = set()

        while current and current not in visited:
            visited.add(current)
            found = None
            for edge in self._edges:
                if edge.source.name == current:
                    found = edge
                    break
            if found:
                chain.append(found)
                current = found.target.name
            else:
                break

        return chain

    def get_all_nodes(self) -> list[LineageNode]:
        """获取所有注册的血缘节点"""
        return list(self._nodes.values())

    def get_all_edges(self) -> list[LineageEdge]:
        """获取所有血缘边"""
        return list(self._edges)
