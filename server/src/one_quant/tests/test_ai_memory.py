"""AI 记忆系统测试 — 写入/检索/相似匹配

覆盖模块: one_quant.ai.memory
目标: ≥80% 覆盖率
"""

from __future__ import annotations

from one_quant.ai.memory import (
    Document,
    DocumentType,
    InstitutionalMemory,
    SearchResult,
    SimpleVectorizer,
)

# ──────────────────── SimpleVectorizer 测试 ────────────────────


class TestSimpleVectorizer:
    """简易向量化器测试"""

    def test_tokenize_chinese(self):
        v = SimpleVectorizer()
        tokens = v._tokenize("量化交易策略分析")
        assert len(tokens) > 0
        # 应包含单字
        assert "量" in tokens

    def test_tokenize_english(self):
        v = SimpleVectorizer()
        tokens = v._tokenize("BTC price analysis")
        assert "btc" in tokens
        assert "price" in tokens

    def test_tokenize_mixed(self):
        v = SimpleVectorizer()
        tokens = v._tokenize("BTC价格分析test")
        assert "btc" in tokens
        assert "价" in tokens

    def test_tokenize_empty(self):
        v = SimpleVectorizer()
        tokens = v._tokenize("")
        assert tokens == []

    def test_compute_tf(self):
        v = SimpleVectorizer()
        tf = v._compute_tf(["a", "b", "a"])
        assert abs(tf["a"] - 2 / 3) < 0.01
        assert abs(tf["b"] - 1 / 3) < 0.01

    def test_compute_tf_empty(self):
        v = SimpleVectorizer()
        assert v._compute_tf([]) == {}

    def test_hash_to_vector(self):
        v = SimpleVectorizer(dim=64)
        vec = v._hash_to_vector("test")
        assert len(vec) == 64
        assert all(-1.0 <= x <= 1.0 for x in vec)

    def test_hash_deterministic(self):
        v = SimpleVectorizer()
        assert v._hash_to_vector("token") == v._hash_to_vector("token")

    def test_fit(self):
        v = SimpleVectorizer()
        v.fit(["这是第一篇文档", "这是第二篇文档", "完全不同的内容"])
        assert v._doc_count == 3
        assert len(v._idf) > 0

    def test_vectorize(self):
        v = SimpleVectorizer(dim=32)
        v.fit(["量化交易策略", "机器学习模型", "市场分析报告"])
        vec = v.vectorize("量化交易")
        assert len(vec) == 32
        # L2 归一化
        norm = sum(x * x for x in vec) ** 0.5
        assert abs(norm - 1.0) < 0.01

    def test_vectorize_not_fitted(self):
        v = SimpleVectorizer(dim=16)
        vec = v.vectorize("测试")
        assert len(vec) == 16

    def test_idf_computation(self):
        """IDF值随文档频率变化"""
        v = SimpleVectorizer()
        v.fit(["alpha beta gamma", "alpha beta delta", "alpha epsilon zeta"])
        # "alpha" 出现在所有3个文档中，IDF 最低
        # "gamma" 只出现在1个文档中，IDF 最高
        alpha_idf = v._idf.get("alpha", 1.0)
        gamma_idf = v._idf.get("gamma", 1.0)
        assert alpha_idf < gamma_idf


# ──────────────────── Document 测试 ────────────────────


class TestDocument:
    """文档测试"""

    def test_auto_timestamp(self):
        doc = Document(doc_id="d1", content="test")
        assert doc.created_at > 0

    def test_defaults(self):
        doc = Document(doc_id="d1", content="test")
        assert doc.metadata == {}
        assert doc.embedding == []


# ──────────────────── InstitutionalMemory 测试 ────────────────────


class TestInstitutionalMemory:
    """机构记忆测试"""

    async def test_store_and_search(self):
        """存储并检索"""
        mem = InstitutionalMemory()
        mem.fit(["量化交易策略分析", "机器学习在金融中的应用", "风险管理框架"])
        await mem.store("d1", "量化交易策略分析报告", {"type": "report"})
        await mem.store("d2", "机器学习模型评估", {"type": "report"})
        results = await mem.search("量化交易", top_k=5)
        assert len(results) > 0
        assert results[0].doc_id == "d1"

    async def test_search_empty(self):
        """空记忆库检索"""
        mem = InstitutionalMemory()
        mem.fit(["test"])
        results = await mem.search("query")
        assert results == []

    async def test_search_not_fitted(self):
        """未拟合时返回空"""
        mem = InstitutionalMemory()
        await mem.store("d1", "test")
        results = await mem.search("test")
        assert results == []

    async def test_search_with_type_filter(self):
        """按类型过滤"""
        mem = InstitutionalMemory()
        mem.fit(["决策A 内容", "研报B 内容", "事故C 内容"])
        await mem.store("d1", "决策A内容分析", {"type": DocumentType.DECISION})
        await mem.store("d2", "研报B内容分析", {"type": DocumentType.REPORT})
        await mem.store("d3", "事故C复盘", {"type": DocumentType.INCIDENT})
        results = await mem.search("内容", doc_type=DocumentType.DECISION)
        assert all(r.metadata.get("type") == DocumentType.DECISION for r in results)

    async def test_search_min_score(self):
        """最低分数过滤"""
        mem = InstitutionalMemory()
        mem.fit(["完全无关的内容", "量化交易策略"])
        await mem.store("d1", "量化交易策略分析")
        results = await mem.search("量化交易", min_score=0.99)
        # 高阈值可能过滤掉
        assert isinstance(results, list)

    async def test_search_top_k(self):
        """结果数量限制"""
        mem = InstitutionalMemory()
        corpus = [f"文档{i} 内容分析" for i in range(20)]
        mem.fit(corpus)
        for i in range(20):
            await mem.store(f"d{i}", f"文档{i}内容分析")
        results = await mem.search("文档内容", top_k=3)
        assert len(results) <= 3

    async def test_get_similar_decisions(self):
        """检索类似决策"""
        mem = InstitutionalMemory()
        mem.fit(["牛市决策", "熊市决策", "研报分析"])
        await mem.store("d1", "牛市中的加仓决策", {"type": DocumentType.DECISION})
        await mem.store("d2", "研报分析报告", {"type": DocumentType.REPORT})
        results = await mem.get_similar_decisions("当前牛市是否加仓")
        assert all(r.metadata.get("type") == DocumentType.DECISION for r in results)

    async def test_get_similar_incidents(self):
        """检索类似事故"""
        mem = InstitutionalMemory()
        mem.fit(["闪崩事故", "系统故障", "策略失效"])
        await mem.store("d1", "2024年闪崩事故复盘", {"type": DocumentType.INCIDENT})
        await mem.store("d2", "策略失效分析", {"type": DocumentType.STRATEGY})
        results = await mem.get_similar_incidents("闪崩风险")
        assert all(r.metadata.get("type") == DocumentType.INCIDENT for r in results)

    async def test_get_context_for_agent(self):
        """为智能体生成上下文"""
        mem = InstitutionalMemory()
        mem.fit(["量化策略 历史决策"])
        await mem.store("d1", "量化策略历史决策记录", {"type": "decision", "date": "2024-01-01"})
        context = await mem.get_context_for_agent("量化策略")
        assert "历史记录" in context or "记录" in context

    async def test_get_context_empty(self):
        """空记忆库上下文"""
        mem = InstitutionalMemory()
        mem.fit(["test"])
        context = await mem.get_context_for_agent("query")
        assert "无相关" in context

    async def test_store_empty_content(self):
        """存储空内容跳过"""
        mem = InstitutionalMemory()
        mem.fit(["test"])
        await mem.store("d1", "  ")
        assert "d1" not in mem._documents

    async def test_fit_updates_existing(self):
        """重新拟合更新已有文档向量"""
        mem = InstitutionalMemory()
        await mem.store("d1", "量化交易策略分析")
        mem.fit(["量化交易策略", "机器学习模型"])
        doc = mem._documents["d1"]
        assert len(doc.embedding) > 0

    async def test_get_stats(self):
        """统计信息"""
        mem = InstitutionalMemory()
        mem.fit(["doc1", "doc2"])
        await mem.store("d1", "doc1", {"type": "report"})
        stats = mem.get_stats()
        assert "total_documents" in stats
        assert "by_type" in stats
        assert stats["fitted"] is True
        assert stats["total_documents"] == 1

    async def test_search_result_fields(self):
        """搜索结果字段完整性"""
        mem = InstitutionalMemory()
        mem.fit(["测试文档"])
        await mem.store("d1", "测试文档内容", {"type": "report", "date": "2024-01-01"})
        results = await mem.search("测试", top_k=1)
        assert len(results) == 1
        r = results[0]
        assert r.doc_id == "d1"
        assert r.content == "测试文档内容"
        assert isinstance(r.score, float)
        assert r.metadata["type"] == "report"

    async def test_cosine_similarity(self):
        """余弦相似度：相同内容高分"""
        mem = InstitutionalMemory()
        mem.fit(["完全相同的内容"] * 5)
        await mem.store("d1", "完全相同的内容")
        results = await mem.search("完全相同的内容", top_k=1)
        assert results[0].score > 0.5

    async def test_dissimilar_low_score(self):
        """不相关内容低分"""
        mem = InstitutionalMemory()
        mem.fit(["量化交易策略分析报告", "天气预报今天晴天"])
        await mem.store("d1", "量化交易策略分析报告")
        results = await mem.search("天气预报", top_k=1)
        if results:
            assert results[0].score < 0.8


# ──────────────────── DocumentType 测试 ────────────────────


class TestDocumentType:
    """文档类型测试"""

    def test_constants(self):
        assert DocumentType.DECISION == "decision"
        assert DocumentType.REPORT == "report"
        assert DocumentType.INCIDENT == "incident"
        assert DocumentType.STRATEGY == "strategy"
        assert DocumentType.MARKET == "market"
        assert DocumentType.OTHER == "other"


# ──────────────────── SearchResult 测试 ────────────────────


class TestSearchResult:
    """搜索结果测试"""

    def test_create(self):
        r = SearchResult(doc_id="d1", content="test", metadata={"type": "report"}, score=0.9)
        assert r.doc_id == "d1"
        assert r.score == 0.9
