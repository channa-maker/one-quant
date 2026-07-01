"""
ONE量化 - YAML 声明式 LLM 策略 Playbook 框架

核心设计:
- YAML 声明分析策略（提示词、工具、市场 regime、优先级）
- @register_playbook 注册表管理
- LLMPlaybookRunner 驱动 LLM + tools → 子信号
- 与代码策略并存: 代码策略走量化执行，YAML 策略走 LLM 定性分析
- 子信号接入 signal_scoring 融合（作为一路证据源）

架构:
  YAML 文件 → load_playbook → LLMPlaybook → register_playbook → PlaybookRegistry
                                                       ↓
  LLMPlaybookRunner.run(playbook, symbol, market_data)
    → 构建 messages（instructions + tools 结果）
    → 调用 LLM
    → 解析 JSON → PlaybookSubSignal
    → PlaybookEvidenceSource.compute() → (strength, direction) → SignalScorer 融合
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────── 数据结构 ────────────────────


@dataclass(frozen=True)
class MarketRegimeConfig:
    """市场 regime 配置"""

    priority: int = 5
    weight_boost: float = 0.0


@dataclass(frozen=True)
class LLMPlaybook:
    """LLM 声明式策略 Playbook

    从 YAML 加载，描述一个 LLM 分析任务:
    - name: 唯一标识
    - display_name: 中文显示名
    - instructions: 提示词模板（{symbol} 等占位符会被替换）
    - required_tools: 需要的工具列表
    - market_regimes: 各市场环境下的优先级和权重
    """

    name: str
    display_name: str = ""
    description: str = ""
    category: str = "general"  # technical / sentiment / event / fundamental / custom
    required_tools: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    default_priority: int = 5
    market_regimes: dict[str, MarketRegimeConfig] = field(default_factory=dict)
    instructions: str = ""

    def get_regime_priority(self, regime: str) -> int:
        """获取指定 regime 下的优先级，不存在则回退默认"""
        cfg = self.market_regimes.get(regime)
        return cfg.priority if cfg else self.default_priority

    def get_regime_weight_boost(self, regime: str) -> float:
        """获取指定 regime 下的权重加成"""
        cfg = self.market_regimes.get(regime)
        return cfg.weight_boost if cfg else 0.0


@dataclass(frozen=True)
class PlaybookSubSignal:
    """Playbook 运行产出的子信号"""

    playbook_name: str
    symbol: str
    direction: str  # "long" / "short" / "neutral"
    confidence: float  # 0.0 - 1.0
    strength: float  # 证据强度 0.0 - 1.0
    reason: str  # 中文分析理由
    raw_response: str = ""  # LLM 原始返回
    tokens_used: int = 0


# ──────────────────── YAML 加载器 ────────────────────


def _parse_market_regimes(raw: dict[str, Any] | None) -> dict[str, MarketRegimeConfig]:
    """解析 market_regimes 配置"""
    if not raw:
        return {}
    result: dict[str, MarketRegimeConfig] = {}
    for regime_name, regime_data in raw.items():
        if isinstance(regime_data, dict):
            result[regime_name] = MarketRegimeConfig(
                priority=regime_data.get("priority", 5),
                weight_boost=float(regime_data.get("weight_boost", 0.0)),
            )
        else:
            result[regime_name] = MarketRegimeConfig()
    return result


def load_playbook_from_yaml(path: Path | str) -> LLMPlaybook:
    """从 YAML 文件加载单个 playbook

    Args:
        path: YAML 文件路径

    Returns:
        LLMPlaybook 实例

    Raises:
        FileNotFoundError: 文件不存在
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Playbook 文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"YAML 格式错误: {path}（顶层必须是字典）")

    return LLMPlaybook(
        name=data.get("name", path.stem),
        display_name=data.get("display_name", ""),
        description=data.get("description", ""),
        category=data.get("category", "general"),
        required_tools=data.get("required_tools", []),
        aliases=data.get("aliases", []),
        default_priority=data.get("default_priority", 5),
        market_regimes=_parse_market_regimes(data.get("market_regimes")),
        instructions=data.get("instructions", ""),
    )


def load_playbooks_from_dir(directory: Path | str) -> list[LLMPlaybook]:
    """从目录批量加载所有 .yaml/.yml 文件

    Args:
        directory: 目录路径

    Returns:
        Playbook 列表（跳过加载失败的文件）
    """
    directory = Path(directory)
    if not directory.is_dir():
        logger.warning("Playbook 目录不存在: %s", directory)
        return []

    playbooks: list[LLMPlaybook] = []
    for yaml_file in sorted(directory.glob("*.y*ml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            pb = load_playbook_from_yaml(yaml_file)
            playbooks.append(pb)
        except Exception:
            logger.exception("加载 Playbook 失败: %s", yaml_file)

    return playbooks


# ──────────────────── 注册表 ────────────────────


class PlaybookRegistry:
    """全局 Playbook 注册表

    管理所有已注册的 LLMPlaybook 实例。
    支持按 name 和 alias 查询。
    """

    _playbooks: dict[str, LLMPlaybook] = {}
    _aliases: dict[str, str] = {}  # alias → name

    @classmethod
    def register(cls, playbook: LLMPlaybook) -> None:
        """注册 playbook（带别名索引）"""
        if playbook.name in cls._playbooks:
            raise ValueError(f"Playbook '{playbook.name}' 已注册")

        cls._playbooks[playbook.name] = playbook
        for alias in playbook.aliases:
            cls._aliases[alias] = playbook.name

        logger.info("Playbook 注册: %s (%s)", playbook.name, playbook.display_name)

    @classmethod
    def get(cls, name_or_alias: str) -> LLMPlaybook | None:
        """按名称或别名查询"""
        # 先按 name 查
        pb = cls._playbooks.get(name_or_alias)
        if pb:
            return pb
        # 再按 alias 查
        real_name = cls._aliases.get(name_or_alias)
        if real_name:
            return cls._playbooks.get(real_name)
        return None

    @classmethod
    def list_all(cls) -> list[str]:
        """列举所有已注册 playbook 名称"""
        return list(cls._playbooks.keys())

    @classmethod
    def load_dir(cls, directory: Path | str) -> int:
        """从目录加载并注册所有 playbook

        Returns:
            成功注册的数量
        """
        playbooks = load_playbooks_from_dir(directory)
        count = 0
        for pb in playbooks:
            if pb.name not in cls._playbooks:
                cls._playbooks[pb.name] = pb
                for alias in pb.aliases:
                    cls._aliases[alias] = pb.name
                count += 1
        return count

    @classmethod
    def clear(cls) -> None:
        """清空注册表（测试用）"""
        cls._playbooks.clear()
        cls._aliases.clear()


def register_playbook(playbook: LLMPlaybook) -> LLMPlaybook:
    """注册 playbook 到全局注册表

    可作为函数调用（类似 register_strategy）。

    Args:
        playbook: 要注册的 playbook

    Returns:
        原始 playbook（不修改）
    """
    PlaybookRegistry.register(playbook)
    return playbook


def reset_registry() -> None:
    """清空注册表（测试用）"""
    PlaybookRegistry.clear()


# ──────────────────── Playbook Runner ────────────────────

# 工具执行器类型：async (tool_name, params) → result
ToolExecutor = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class LLMPlaybookRunner:
    """LLM Playbook 运行器

    驱动流程:
    1. 从 playbook.instructions 构建 system prompt
    2. 调用 required_tools 获取数据
    3. 将数据填入 user message
    4. 调用 LLM 获取分析结果
    5. 解析 JSON → PlaybookSubSignal
    """

    def __init__(
        self,
        llm_provider: Any,  # LLMProvider 实例（需有 async complete 方法）
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._tool_executor = tool_executor

    async def run(
        self,
        playbook: LLMPlaybook,
        symbol: str,
        market_data: dict[str, Any],
        regime: str = "default",
    ) -> PlaybookSubSignal:
        """运行 playbook

        Args:
            playbook: 要运行的 playbook
            symbol: 标的符号（如 BTCUSDT）
            market_data: 市场数据上下文
            regime: 当前市场 regime

        Returns:
            PlaybookSubSignal 子信号
        """
        # ① 收集工具数据
        tool_results: dict[str, Any] = {}
        if self._tool_executor and playbook.required_tools:
            for tool_name in playbook.required_tools:
                try:
                    result = await self._tool_executor(tool_name, {"symbol": symbol})
                    tool_results[tool_name] = result
                except Exception:
                    logger.warning("工具 %s 调用失败", tool_name)
                    tool_results[tool_name] = {"error": "调用失败"}

        # ② 构建 messages
        system_prompt = playbook.instructions.format(
            symbol=symbol,
            regime=regime,
            **{k: json.dumps(v, ensure_ascii=False) for k, v in tool_results.items()},
        )

        user_content = f"请分析标的 {symbol}"
        if tool_results:
            user_content += (
                f"\n\n工具数据:\n{json.dumps(tool_results, ensure_ascii=False, indent=2)}"
            )
        if market_data:
            user_content += (
                f"\n\n市场数据:\n{json.dumps(market_data, ensure_ascii=False, indent=2)}"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        # ③ 调用 LLM
        try:
            response = await self._llm_provider.complete(
                messages=messages,
                max_tokens=1024,
                temperature=0.3,
            )
            raw_content = response.content.strip()
            tokens_used = getattr(response, "tokens_in", 0) + getattr(response, "tokens_out", 0)
        except Exception:
            logger.exception("LLM 调用失败: playbook=%s symbol=%s", playbook.name, symbol)
            return PlaybookSubSignal(
                playbook_name=playbook.name,
                symbol=symbol,
                direction="neutral",
                confidence=0.0,
                strength=0.0,
                reason="LLM 调用失败",
            )

        # ④ 解析 JSON 响应
        return self._parse_response(
            playbook_name=playbook.name,
            symbol=symbol,
            raw_content=raw_content,
            tokens_used=tokens_used,
        )

    @staticmethod
    def _parse_response(
        playbook_name: str,
        symbol: str,
        raw_content: str,
        tokens_used: int,
    ) -> PlaybookSubSignal:
        """解析 LLM 返回的 JSON

        支持:
        - 纯 JSON 字符串
        - Markdown 包裹的 JSON（```json ... ```）
        """
        # 尝试提取 JSON
        json_str = raw_content

        # 处理 markdown 包裹
        if "```" in raw_content:
            for block in raw_content.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                if block.startswith("{"):
                    json_str = block
                    break

        # 尝试直接匹配 JSON 对象
        match = re.search(r"\{[^{}]*\}", json_str, re.DOTALL)
        if match:
            json_str = match.group()

        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "Playbook %s 返回非 JSON: %s",
                playbook_name,
                raw_content[:200],
            )
            return PlaybookSubSignal(
                playbook_name=playbook_name,
                symbol=symbol,
                direction="neutral",
                confidence=0.0,
                strength=0.0,
                reason=f"LLM 返回解析失败: {raw_content[:100]}",
                raw_response=raw_content,
                tokens_used=tokens_used,
            )

        # 提取字段
        direction = data.get("direction", "neutral")
        if direction not in ("long", "short", "neutral"):
            direction = "neutral"

        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        reason = str(data.get("reason", ""))

        # strength = confidence * direction 权重
        # 用于 signal_scoring 融合时的证据强度
        strength = confidence

        return PlaybookSubSignal(
            playbook_name=playbook_name,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            strength=strength,
            reason=reason,
            raw_response=raw_content,
            tokens_used=tokens_used,
        )


# ──────────────────── 证据源适配器 ────────────────────


class PlaybookEvidenceSource:
    """将 Playbook 子信号适配为 signal_scoring.EvidenceSource 协议

    接入 SignalScorer 时使用:
        source = PlaybookEvidenceSource(playbook, cached_result)
        scorer.register_source(source)
    """

    def __init__(
        self,
        playbook: LLMPlaybook,
        cached_result: dict[str, Any] | None = None,
    ) -> None:
        """初始化

        Args:
            playbook: 关联的 playbook
            cached_result: 缓存的子信号结果
                         {"direction": str, "confidence": float, "strength": float}
        """
        self._playbook = playbook
        self._cached = cached_result or {}

    @property
    def name(self) -> str:
        return f"playbook_{self._playbook.name}"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """实现 EvidenceSource 协议

        Returns:
            (strength, direction) — 用于 SignalScorer 融合
        """
        direction_str = self._cached.get("direction", "neutral")
        strength = float(self._cached.get("strength", 0.0))

        direction_map = {"long": 1.0, "short": -1.0, "neutral": 0.0}
        direction = direction_map.get(direction_str, 0.0)

        return max(0.0, min(1.0, strength)), direction

    def update(self, result: PlaybookSubSignal) -> None:
        """更新缓存的子信号结果"""
        self._cached = {
            "direction": result.direction,
            "confidence": result.confidence,
            "strength": result.strength,
        }
