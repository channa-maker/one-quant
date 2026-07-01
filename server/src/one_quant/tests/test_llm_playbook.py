"""LLM Playbook 声明式策略框架测试

测试覆盖:
1. YAML 加载器 — 从文件/目录加载 playbook
2. @register_playbook 注册表 — 注册/查询/列举
3. LLMPlaybook 数据类 — 字段完整性
4. LLMPlaybookRunner — 驱动 LLM + tools 产出子信号
5. 内置 YAML 策略 — 全部可加载、无需改核心代码
6. 与 signal_scoring 集成 — 子信号可融合为证据源
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from one_quant.ai.llm_playbook import (
    LLMPlaybook,
    LLMPlaybookRunner,
    PlaybookRegistry,
    load_playbook_from_yaml,
    load_playbooks_from_dir,
    register_playbook,
    reset_registry,
)
from one_quant.ai.playbooks import PLAYBOOKS_DIR

# ──────────────────── Fixtures ────────────────────


SAMPLE_YAML = """
name: test_analysis
display_name: 测试分析策略
description: 用于单元测试的示例分析策略
category: technical
required_tools:
  - get_klines
  - get_indicators
aliases:
  - test_ta
  - 测试分析
default_priority: 7
market_regimes:
  trending:
    priority: 9
    weight_boost: 0.2
  ranging:
    priority: 5
    weight_boost: 0.0
instructions: |
  你是专业的技术分析师。
  分析标的 {symbol} 的当前走势。

  步骤：
  1. 获取最近 20 根 K 线
  2. 计算 RSI、MACD 指标
  3. 给出方向判断和置信度

  输出 JSON:
  {{"direction": "long/short/neutral", "confidence": 0.0-1.0, "reason": "中文分析理由"}}
"""


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个测试前清空注册表"""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def sample_yaml_path(tmp_path: Path) -> Path:
    """写入示例 YAML 文件"""
    p = tmp_path / "test_analysis.yaml"
    p.write_text(SAMPLE_YAML, encoding="utf-8")
    return p


@pytest.fixture
def sample_playbook(sample_yaml_path: Path) -> LLMPlaybook:
    """加载示例 playbook"""
    return load_playbook_from_yaml(sample_yaml_path)


# ──────────────────── 1. YAML 加载器 ────────────────────


class TestYAMLLoader:
    """YAML 加载器测试"""

    def test_load_from_file(self, sample_yaml_path: Path):
        """从单个 YAML 文件加载"""
        pb = load_playbook_from_yaml(sample_yaml_path)
        assert pb.name == "test_analysis"
        assert pb.display_name == "测试分析策略"
        assert pb.category == "technical"
        assert "get_klines" in pb.required_tools
        assert pb.default_priority == 7
        assert "trending" in pb.market_regimes
        assert "你是专业的技术分析师" in pb.instructions

    def test_load_from_dir(self, tmp_path: Path):
        """从目录批量加载"""
        # 创建多个 YAML
        for i in range(3):
            yaml_content = SAMPLE_YAML.replace("test_analysis", f"strategy_{i}")
            (tmp_path / f"strategy_{i}.yaml").write_text(yaml_content, encoding="utf-8")

        # 加一个非 YAML 文件（应被忽略）
        (tmp_path / "readme.txt").write_text("not a playbook", encoding="utf-8")

        playbooks = load_playbooks_from_dir(tmp_path)
        assert len(playbooks) == 3
        names = {pb.name for pb in playbooks}
        assert names == {"strategy_0", "strategy_1", "strategy_2"}

    def test_load_builtin_playbooks(self):
        """加载内置 playbooks 目录"""
        playbooks = load_playbooks_from_dir(PLAYBOOKS_DIR)
        assert len(playbooks) >= 8  # 至少 8 个内置策略

        # 验证每个 playbook 必需字段
        for pb in playbooks:
            assert pb.name, "playbook 缺少 name"
            assert pb.display_name, f"{pb.name} 缺少 display_name"
            assert pb.instructions, f"{pb.name} 缺少 instructions"
            assert pb.category, f"{pb.name} 缺少 category"

    def test_load_missing_file(self, tmp_path: Path):
        """加载不存在的文件"""
        with pytest.raises(FileNotFoundError):
            load_playbook_from_yaml(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml(self, tmp_path: Path):
        """加载格式错误的 YAML"""
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: test\n  invalid_indent: {{bad}}", encoding="utf-8")
        # 应该不崩溃，只是跳过或报错
        with pytest.raises(Exception):
            load_playbook_from_yaml(bad)

    def test_load_missing_required_field(self, tmp_path: Path):
        """缺少必需字段的 YAML"""
        bad = tmp_path / "minimal.yaml"
        bad.write_text("name: minimal_playbook\ndescription: too minimal", encoding="utf-8")
        # 应该能加载，缺失字段用默认值
        pb = load_playbook_from_yaml(bad)
        assert pb.name == "minimal_playbook"
        assert pb.default_priority == 5  # 默认优先级


# ──────────────────── 2. 注册表 ────────────────────


class TestPlaybookRegistry:
    """Playbook 注册表测试"""

    def test_register_and_get(self, sample_playbook: LLMPlaybook):
        """注册并查询"""
        register_playbook(sample_playbook)
        assert PlaybookRegistry.get("test_analysis") is sample_playbook

    def test_register_duplicate_raises(self, sample_playbook: LLMPlaybook):
        """重复注册相同 name 应报错"""
        register_playbook(sample_playbook)
        with pytest.raises(ValueError, match="已注册"):
            register_playbook(sample_playbook)

    def test_list_all(self, sample_playbook: LLMPlaybook):
        """列举所有已注册"""
        register_playbook(sample_playbook)
        names = PlaybookRegistry.list_all()
        assert "test_analysis" in names

    def test_get_by_alias(self, sample_playbook: LLMPlaybook):
        """通过别名查询"""
        register_playbook(sample_playbook)
        assert PlaybookRegistry.get("test_ta") is sample_playbook
        assert PlaybookRegistry.get("测试分析") is sample_playbook

    def test_get_nonexistent(self):
        """查询不存在的 playbook"""
        assert PlaybookRegistry.get("nonexistent") is None

    def test_register_playbooks_from_dir(self, tmp_path: Path):
        """从目录批量注册"""
        for i in range(3):
            yaml_content = SAMPLE_YAML.replace("test_analysis", f"batch_{i}")
            (tmp_path / f"batch_{i}.yaml").write_text(yaml_content, encoding="utf-8")

        count = PlaybookRegistry.load_dir(tmp_path)
        assert count == 3
        assert PlaybookRegistry.get("batch_0") is not None
        assert PlaybookRegistry.get("batch_2") is not None

    def test_builtin_playbooks_registered(self):
        """加载内置 playbooks 目录到注册表"""
        count = PlaybookRegistry.load_dir(PLAYBOOKS_DIR)
        assert count >= 8

        # 验证特定内置策略存在
        expected = [
            "trend_analysis",
            "ma_analysis",
            "chanlun_analysis",
            "wave_analysis",
            "hotspot_analysis",
            "event_analysis",
            "growth_analysis",
            "expectation_analysis",
        ]
        for name in expected:
            pb = PlaybookRegistry.get(name)
            assert pb is not None, f"内置策略 '{name}' 未注册"


# ──────────────────── 3. LLMPlaybook 数据类 ────────────────────


class TestLLMPlaybook:
    """LLMPlaybook 数据类测试"""

    def test_fields(self, sample_playbook: LLMPlaybook):
        """字段完整性"""
        pb = sample_playbook
        assert pb.name == "test_analysis"
        assert pb.display_name == "测试分析策略"
        assert pb.description == "用于单元测试的示例分析策略"
        assert pb.category == "technical"
        assert pb.required_tools == ["get_klines", "get_indicators"]
        assert pb.aliases == ["test_ta", "测试分析"]
        assert pb.default_priority == 7
        assert "trending" in pb.market_regimes
        assert "ranging" in pb.market_regimes

    def test_market_regime_priority(self, sample_playbook: LLMPlaybook):
        """市场 regime 优先级查询"""
        assert sample_playbook.get_regime_priority("trending") == 9
        assert sample_playbook.get_regime_priority("ranging") == 5
        assert sample_playbook.get_regime_priority("unknown") == 7  # 回退默认

    def test_market_regime_weight_boost(self, sample_playbook: LLMPlaybook):
        """市场 regime 权重加成"""
        assert sample_playbook.get_regime_weight_boost("trending") == pytest.approx(0.2)
        assert sample_playbook.get_regime_weight_boost("ranging") == pytest.approx(0.0)
        assert sample_playbook.get_regime_weight_boost("unknown") == pytest.approx(0.0)


# ──────────────────── 4. LLMPlaybookRunner ────────────────────


class TestLLMPlaybookRunner:
    """LLM Playbook 运行器测试"""

    @pytest.fixture
    def mock_llm_provider(self):
        """模拟 LLM Provider"""
        mock = AsyncMock()

        # 模拟 LLM 返回分析结果
        response = MagicMock()
        response.content = json.dumps(
            {
                "direction": "long",
                "confidence": 0.75,
                "reason": "均线金叉，RSI 超卖反弹，MACD 底部背离",
            },
            ensure_ascii=False,
        )
        response.tokens_in = 500
        response.tokens_out = 200
        mock.complete.return_value = response
        return mock

    @pytest.fixture
    def mock_tool_executor(self):
        """模拟工具执行器"""

        async def executor(tool_name: str, params: dict[str, Any]) -> Any:
            if tool_name == "get_klines":
                return [{"open": 100, "close": 105, "high": 108, "low": 98, "volume": 1000}]
            if tool_name == "get_indicators":
                return {"rsi": 35, "macd": {"macd": 0.5, "signal": 0.3, "histogram": 0.2}}
            return {}

        return executor

    @pytest.mark.asyncio
    async def test_run_produces_sub_signal(
        self, sample_playbook, mock_llm_provider, mock_tool_executor
    ):
        """运行 playbook 产出子信号"""
        runner = LLMPlaybookRunner(
            llm_provider=mock_llm_provider,
            tool_executor=mock_tool_executor,
        )

        result = await runner.run(
            playbook=sample_playbook,
            symbol="BTCUSDT",
            market_data={"price": 50000},
        )

        # 验证子信号结构
        assert result.playbook_name == "test_analysis"
        assert result.symbol == "BTCUSDT"
        assert result.direction in ("long", "short", "neutral")
        assert 0.0 <= result.confidence <= 1.0
        assert result.reason  # 非空理由
        assert result.strength >= 0.0  # 证据强度

    @pytest.mark.asyncio
    async def test_run_calls_llm_with_instructions(
        self, sample_playbook, mock_llm_provider, mock_tool_executor
    ):
        """运行时 LLM 被正确调用（instructions 作为 system prompt）"""
        runner = LLMPlaybookRunner(
            llm_provider=mock_llm_provider,
            tool_executor=mock_tool_executor,
        )

        await runner.run(
            playbook=sample_playbook,
            symbol="ETHUSDT",
            market_data={"price": 3000},
        )

        # 验证 LLM 被调用
        mock_llm_provider.complete.assert_called_once()
        call_args = mock_llm_provider.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]

        # system prompt 应包含 playbook instructions
        system_msg = next(m for m in messages if m["role"] == "system")
        assert "你是专业的技术分析师" in system_msg["content"]
        assert "ETHUSDT" in system_msg["content"]  # symbol 被填入

    @pytest.mark.asyncio
    async def test_run_llm_error_returns_neutral(self, sample_playbook, mock_tool_executor):
        """LLM 调用失败时返回中性信号"""
        mock_provider = AsyncMock()
        mock_provider.complete.side_effect = RuntimeError("LLM 服务不可用")

        runner = LLMPlaybookRunner(
            llm_provider=mock_provider,
            tool_executor=mock_tool_executor,
        )

        result = await runner.run(
            playbook=sample_playbook,
            symbol="BTCUSDT",
            market_data={},
        )

        assert result.direction == "neutral"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_run_malformed_json_returns_neutral(self, sample_playbook, mock_tool_executor):
        """LLM 返回非 JSON 时返回中性信号"""
        mock_provider = AsyncMock()
        response = MagicMock()
        response.content = "这不是一个 JSON 响应"
        response.tokens_in = 100
        response.tokens_out = 50
        mock_provider.complete.return_value = response

        runner = LLMPlaybookRunner(
            llm_provider=mock_provider,
            tool_executor=mock_tool_executor,
        )

        result = await runner.run(
            playbook=sample_playbook,
            symbol="BTCUSDT",
            market_data={},
        )

        assert result.direction == "neutral"


# ──────────────────── 5. 内置 YAML 策略 ────────────────────


class TestBuiltinPlaybooks:
    """内置 YAML 策略测试"""

    @pytest.mark.parametrize(
        "filename,expected_name,expected_category",
        [
            ("trend_analysis.yaml", "trend_analysis", "technical"),
            ("ma_analysis.yaml", "ma_analysis", "technical"),
            ("chanlun_analysis.yaml", "chanlun_analysis", "technical"),
            ("wave_analysis.yaml", "wave_analysis", "technical"),
            ("hotspot_analysis.yaml", "hotspot_analysis", "sentiment"),
            ("event_analysis.yaml", "event_analysis", "event"),
            ("growth_analysis.yaml", "growth_analysis", "fundamental"),
            ("expectation_analysis.yaml", "expectation_analysis", "fundamental"),
        ],
    )
    def test_load_each_builtin(self, filename, expected_name, expected_category):
        """每个内置 YAML 可单独加载"""
        filepath = PLAYBOOKS_DIR / filename
        assert filepath.exists(), f"内置策略文件不存在: {filename}"

        pb = load_playbook_from_yaml(filepath)
        assert pb.name == expected_name
        assert pb.category == expected_category
        assert pb.instructions  # 非空提示词
        assert pb.display_name  # 非空显示名

    def test_all_have_market_regimes(self):
        """所有内置策略都有 market_regimes 配置"""
        playbooks = load_playbooks_from_dir(PLAYBOOKS_DIR)
        for pb in playbooks:
            assert pb.market_regimes, f"{pb.name} 缺少 market_regimes"

    def test_no_code_change_needed_for_new_yaml(self, tmp_path: Path):
        """新增 YAML 文件无需改核心代码即可加载"""
        # 模拟新增一个策略 YAML
        new_yaml = tmp_path / "custom_strategy.yaml"
        new_yaml.write_text(
            """
name: custom_strategy
display_name: 自定义策略
description: 用户自定义分析策略
category: custom
default_priority: 6
market_regimes:
  trending:
    priority: 8
instructions: |
  这是用户自定义的分析策略。
  输出 JSON: {"direction": "neutral", "confidence": 0.5, "reason": "自定义分析"}
""",
            encoding="utf-8",
        )

        # 直接加载目录即可发现新策略
        playbooks = load_playbooks_from_dir(tmp_path)
        assert len(playbooks) == 1
        assert playbooks[0].name == "custom_strategy"

        # 注册后可查询
        register_playbook(playbooks[0])
        assert PlaybookRegistry.get("custom_strategy") is not None


# ──────────────────── 6. 与 signal_scoring 集成 ────────────────────


class TestSignalScoringIntegration:
    """Playbook 与 signal_scoring 融合测试"""

    def test_playbook_as_evidence_source(self, sample_playbook):
        """Playbook 子信号可作为 EvidenceSource 接入 SignalScorer"""
        from one_quant.ai.llm_playbook import PlaybookEvidenceSource

        source = PlaybookEvidenceSource(
            playbook=sample_playbook,
            cached_result={
                "direction": "long",
                "confidence": 0.8,
                "strength": 0.7,
            },
        )

        assert source.name == "playbook_test_analysis"

        strength, direction = source.compute("BTCUSDT", {})
        assert 0.0 <= strength <= 1.0
        assert direction in (-1.0, 0.0, 1.0)
        assert direction == 1.0  # long → +1

    def test_multiple_playbooks_as_sources(self):
        """多个 playbook 注册为不同证据源"""
        from one_quant.ai.llm_playbook import PlaybookEvidenceSource

        sources = []
        for name, dir_str, conf in [
            ("trend", "long", 0.8),
            ("ma", "long", 0.6),
            ("wave", "short", 0.4),
        ]:
            pb = LLMPlaybook(
                name=name,
                display_name=name,
                description="",
                category="technical",
                instructions="test",
            )
            source = PlaybookEvidenceSource(
                playbook=pb,
                cached_result={"direction": dir_str, "confidence": conf, "strength": conf},
            )
            sources.append(source)

        # 验证各源独立
        assert sources[0].name == "playbook_trend"
        assert sources[1].name == "playbook_ma"
        assert sources[2].name == "playbook_wave"

        # 方向正确
        s1, d1 = sources[0].compute("BTC", {})
        s2, d2 = sources[1].compute("BTC", {})
        s3, d3 = sources[2].compute("BTC", {})
        assert d1 == 1.0  # long
        assert d2 == 1.0  # long
        assert d3 == -1.0  # short
