"""
ONE量化 - 机构记忆系统 (RAG)

向量检索历史决策、研报、事故复盘，为 AI 智能体提供上下文参考。

设计原则：
- 全中文注释和输出
- AI 无否决权：只提供参考，决策仍需风控确认
- 支持内存模式（开发/测试）和 Redis 模式（生产）
- 所有异步方法完整类型标注
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────── 文档类型枚举 ────────────────────


class DocumentType:
    """文档类型常量。"""

    DECISION = "decision"  # 历史决策
    REPORT = "report"  # 研报
    INCIDENT = "incident"  # 事故复盘
    STRATEGY = "strategy"  # 策略记录
    MARKET = "market"  # 市场分析
    OTHER = "other"  # 其他


# ──────────────────── 文档数据类 ────────────────────


@dataclass
class Document:
    """存储在机构记忆中的文档。"""

    doc_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)
    created_at: int = 0

    def __post_init__(self) -> None:
        if self.created_at == 0:
            self.created_at = time.time_ns()


@dataclass
class SearchResult:
    """检索结果。"""

    doc_id: str
    content: str
    metadata: dict[str, Any]
    score: float  # 相似度分数 0-1


# ──────────────────── 简易 TF-IDF 向量化器 ────────────────────


class SimpleVectorizer:
    """简易中文 TF-IDF 向量化器。

    不依赖外部库，适合开发和测试。
    生产环境可替换为专业 embedding API。
    """

    def __init__(self, dim: int = 128) -> None:
        """初始化向量化器。

        Args:
            dim: 向量维度。
        """
        self._dim = dim
        self._idf: dict[str, float] = {}
        self._doc_count = 0

    def _tokenize(self, text: str) -> list[str]:
        """中文分词（简易实现：按字 + 二元组）。

        Args:
            text: 输入文本。

        Returns:
            token 列表。
        """
        # 清洗
        text = re.sub(r"[^\u4e00-\u9fff\w]", " ", text)
        tokens: list[str] = []

        # 提取中文字符
        cn_chars = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(cn_chars)

        # 中文二元组
        for i in range(len(cn_chars) - 1):
            tokens.append(cn_chars[i] + cn_chars[i + 1])

        # 英文单词
        en_words = re.findall(r"[a-zA-Z]{2,}", text.lower())
        tokens.extend(en_words)

        return tokens

    def _compute_tf(self, tokens: list[str]) -> dict[str, float]:
        """计算词频 (TF)。

        Args:
            tokens: token 列表。

        Returns:
            {token: tf_score}
        """
        if not tokens:
            return {}
        counter = Counter(tokens)
        total = len(tokens)
        return {t: c / total for t, c in counter.items()}

    def _hash_to_vector(self, token: str) -> list[float]:
        """将 token 哈希映射到固定维度向量。

        Args:
            token: 输入 token。

            Returns:
                维度为 self._dim 的浮点向量。
        """
        h = hashlib.md5(token.encode("utf-8")).digest()
        vec: list[float] = []
        for i in range(self._dim):
            byte_val = h[i % len(h)]
            # 映射到 [-1, 1]
            vec.append((byte_val / 127.5) - 1.0)
        return vec

    def fit(self, documents: list[str]) -> None:
        """拟合 IDF 值。

        Args:
            documents: 文档文本列表。
        """
        self._doc_count = len(documents)
        df: Counter[str] = Counter()  # 文档频率

        for doc in documents:
            tokens = set(self._tokenize(doc))
            for t in tokens:
                df[t] += 1

        # IDF = log(N / (df + 1)) + 1
        self._idf = {}
        for t, count in df.items():
            self._idf[t] = math.log(self._doc_count / (count + 1)) + 1

    def vectorize(self, text: str) -> list[float]:
        """将文本转换为 TF-IDF 加权向量。

        Args:
            text: 输入文本。

            Returns:
                维度为 self._dim 的浮点向量。
        """
        tokens = self._tokenize(text)
        tf = self._compute_tf(tokens)

        # 初始化结果向量
        vec = [0.0] * self._dim

        for token, tf_score in tf.items():
            idf_score = self._idf.get(token, 1.0)
            weight = tf_score * idf_score

            # 哈希映射并累加
            token_vec = self._hash_to_vector(token)
            for i in range(self._dim):
                vec[i] += weight * token_vec[i]

        # L2 归一化
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]

        return vec


# ──────────────────── 机构记忆 ────────────────────


class InstitutionalMemory:
    """机构记忆：向量检索历史决策/研报/事故。

    支持：
    - 文档存储与索引
    - 语义检索（向量相似度）
    - 按类型过滤
    - 类似决策检索

    使用方式：
        memory = InstitutionalMemory()
        memory.fit(["历史文档1", "历史文档2", ...])
        await memory.store("doc_1", "决策内容", {"type": "decision"})
        results = await memory.search("类似情形", top_k=5)
    """

    def __init__(self, vectorizer: SimpleVectorizer | None = None) -> None:
        """初始化机构记忆。

        Args:
            vectorizer: 向量化器实例，None 则使用默认 TF-IDF 向量化器。
        """
        self._vectorizer = vectorizer or SimpleVectorizer(dim=128)
        self._documents: dict[str, Document] = {}
        self._fitted = False

    def fit(self, corpus: list[str]) -> None:
        """用语料库拟合向量化器。

        Args:
            corpus: 训练语料（历史文档文本列表）。
        """
        all_texts = list(corpus)
        # 包含已存储的文档
        for doc in self._documents.values():
            all_texts.append(doc.content)

        self._vectorizer.fit(all_texts)
        self._fitted = True

        # 重新计算已存储文档的向量
        for doc in self._documents.values():
            doc.embedding = self._vectorizer.vectorize(doc.content)

        logger.info("机构记忆拟合完成: 语料 %d 篇, 已索引 %d 篇", len(corpus), len(self._documents))

    async def store(
        self,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """存储文档到机构记忆。

        Args:
            doc_id: 文档唯一 ID。
            content: 文档内容。
            metadata: 元数据（type, symbol, date, tags 等）。
        """
        if not content.strip():
            logger.warning("跳过空文档: doc_id=%s", doc_id)
            return

        metadata = metadata or {}

        # 生成向量（如果已拟合）
        embedding: list[float] = []
        if self._fitted:
            embedding = self._vectorizer.vectorize(content)

        doc = Document(
            doc_id=doc_id,
            content=content,
            metadata=metadata,
            embedding=embedding,
        )
        self._documents[doc_id] = doc

        logger.info(
            "文档存入机构记忆: doc_id=%s type=%s len=%d",
            doc_id,
            metadata.get("type", "unknown"),
            len(content),
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        doc_type: str | None = None,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """语义检索：找到最相关的历史文档。

        Args:
            query: 查询文本。
            top_k: 返回结果数量。
            doc_type: 过滤文档类型（None 表示不过滤）。
            min_score: 最低相似度阈值。

        Returns:
            检索结果列表，按相似度降序排列。
        """
        if not self._documents:
            return []

        if not self._fitted:
            logger.warning("向量化器未拟合，返回空结果")
            return []

        # 查询向量化
        query_vec = self._vectorizer.vectorize(query)

        # 计算相似度
        results: list[SearchResult] = []
        for doc in self._documents.values():
            # 类型过滤
            if doc_type and doc.metadata.get("type") != doc_type:
                continue

            if not doc.embedding:
                continue

            # 余弦相似度（向量已归一化，直接点积）
            score = sum(a * b for a, b in zip(query_vec, doc.embedding))

            if score >= min_score:
                results.append(
                    SearchResult(
                        doc_id=doc.doc_id,
                        content=doc.content,
                        metadata=doc.metadata,
                        score=score,
                    )
                )

        # 排序并截取 top_k
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    async def get_similar_decisions(
        self,
        situation: str,
        top_k: int = 3,
    ) -> list[SearchResult]:
        """检索类似情形的历史决策。

        Args:
            situation: 当前情形描述。
            top_k: 返回结果数量。

        Returns:
            类似决策列表。
        """
        return await self.search(
            query=situation,
            top_k=top_k,
            doc_type=DocumentType.DECISION,
        )

    async def get_similar_incidents(
        self,
        situation: str,
        top_k: int = 3,
    ) -> list[SearchResult]:
        """检索类似的历史事故复盘。

        Args:
            situation: 当前情形描述。
            top_k: 返回结果数量。

        Returns:
            类似事故列表。
        """
        return await self.search(
            query=situation,
            top_k=top_k,
            doc_type=DocumentType.INCIDENT,
        )

    async def get_context_for_agent(
        self,
        query: str,
        top_k: int = 5,
    ) -> str:
        """为智能体生成上下文字符串（注入 prompt）。

        Args:
            query: 查询文本。
            top_k: 返回结果数量。

        Returns:
            格式化的上下文字符串，可直接注入 prompt。
        """
        results = await self.search(query, top_k=top_k)

        if not results:
            return "（无相关历史记录）"

        lines = ["以下是与当前情形相关的历史记录，仅供参考：\n"]
        for i, r in enumerate(results, 1):
            doc_type = r.metadata.get("type", "未知")
            date_str = r.metadata.get("date", "未知日期")
            lines.append(f"--- 记录 {i} [{doc_type}] {date_str} (相似度: {r.score:.3f}) ---")
            # 限制长度避免 prompt 过长
            content = r.content[:500] + ("..." if len(r.content) > 500 else "")
            lines.append(content)
            lines.append("")

        return "\n".join(lines)

    def get_stats(self) -> dict[str, Any]:
        """获取机构记忆统计信息。

        Returns:
            统计字典。
        """
        type_counts: dict[str, int] = {}
        for doc in self._documents.values():
            t = doc.metadata.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "total_documents": len(self._documents),
            "by_type": type_counts,
            "fitted": self._fitted,
        }
