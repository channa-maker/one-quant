"""
ONE量化 - LLM 多 Provider 接入层

支持 Claude / DeepSeek / Ollama / 本地模型等多 Provider，
按任务复杂度自动路由，Provider 级 failover，Token 计量 + 日预算硬上限。

设计原则：
- 全中文注释和输出
- AI 无否决权：只产 Signal/建议，必过风控
- Token 计量必须可单测
- Prompt 注入防护（外部文本清洗 + 隔离标记）
- 所有异步方法完整类型标注
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────── Prompt 注入防护 ────────────────────


def sanitize_user_text(text: str, max_length: int = 8000) -> str:
    """清洗外部用户文本，防止 Prompt 注入。

    策略：
    1. 截断过长文本
    2. 移除常见注入模式（ignore previous, system prompt 等）
    3. 用隔离标记包裹用户内容

    Args:
        text: 原始用户文本。
        max_length: 最大长度限制。

    Returns:
        清洗后的安全文本。
    """
    if not text:
        return ""

    # 截断
    text = text[:max_length]

    # 移除常见注入模式（中英文）
    injection_patterns = [
        r"(?i)ignore\s+(all\s+)?previous\s+instructions",
        r"(?i)ignore\s+(all\s+)?prior\s+instructions",
        r"(?i)disregard\s+(all\s+)?previous",
        r"(?i)you\s+are\s+now\s+",
        r"(?i)new\s+instructions?\s*:",
        r"(?i)system\s*:\s*",
        r"(?i)override\s+instructions",
        r"(?i)forget\s+(all\s+)?instructions",
        r"忽略(之前|上面|所有)(的)?(指令|提示|要求)",
        r"你的(新|真正)(身份|角色|指令)",
        r"系统提示词",
        r"输出你的(system\s*prompt|提示词|指令)",
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, "[已过滤]", text)

    return text


def wrap_user_content(text: str) -> str:
    """用隔离标记包裹用户内容，明确区分系统指令与用户输入。

    Args:
        text: 清洗后的用户文本。

    Returns:
        包裹后的文本。
    """
    return f"<user_content>{text}</user_content>"


# ──────────────────── LLM 响应模型 ────────────────────


class LLMResponse(BaseModel, frozen=True):
    """LLM 响应 — 不可变，保证数据一致性。"""

    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


# ──────────────────── 任务复杂度枚举 ────────────────────


class TaskComplexity(StrEnum):
    """任务复杂度等级，用于路由决策。"""

    HIGH = "high"  # 推理/规划/复杂分析
    MEDIUM = "medium"  # 分析/解读/总结
    LOW = "low"  # 分类/提取/格式化


# ──────────────────── LLM Provider 抽象基类 ────────────────────


class LLMProvider(ABC):
    """LLM Provider 抽象基类。

    所有 Provider 实现此类，提供统一的 complete 接口。
    """

    name: str
    supported_models: list[str]

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 LLM 生成补全。

        Args:
            messages: 消息列表，格式 [{"role": "system/user/assistant", "content": "..."}]。
            model: 模型名称，空字符串使用默认模型。
            max_tokens: 最大输出 token 数。
            temperature: 温度参数。
            **kwargs: 其他参数。

        Returns:
            LLMResponse 响应对象。
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """估算文本 token 数量。

        Args:
            text: 输入文本。

        Returns:
            估算的 token 数。
        """
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """估算调用成本（USD）。

        Args:
            input_tokens: 输入 token 数。
            output_tokens: 输出 token 数。

        Returns:
            成本（美元）。
        """
        ...


# ──────────────────── Claude Provider ────────────────────


class ClaudeProvider(LLMProvider):
    """Claude Provider (Anthropic Messages API)。

    支持 Opus/Sonnet/Haiku，按复杂度路由。
    """

    name = "claude"
    supported_models = [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-haiku-20241022",
    ]

    # 各模型定价（每 token）
    PRICING: dict[str, dict[str, Decimal]] = {
        "claude-sonnet-4-20250514": {
            "input": Decimal("0.000003"),
            "output": Decimal("0.000015"),
        },
        "claude-opus-4-20250514": {
            "input": Decimal("0.000015"),
            "output": Decimal("0.000075"),
        },
        "claude-3-5-haiku-20241022": {
            "input": Decimal("0.0000008"),
            "output": Decimal("0.000004"),
        },
    }

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-20250514") -> None:
        self._api_key = api_key
        self._default_model = default_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 Anthropic Messages API。"""
        import httpx

        model = model or self._default_model
        start = time.time()

        # 分离 system 消息和用户消息（Anthropic API 要求 system 单独传）
        system_text = ""
        user_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
            else:
                user_messages.append(msg)

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_text:
            payload["system"] = system_text

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        content = data["content"][0]["text"]
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)
        cost = self.estimate_cost(tokens_in, tokens_out, model)
        latency = (time.time() - start) * 1000

        logger.info(
            "Claude 调用完成: model=%s tokens_in=%d tokens_out=%d cost=$%s latency=%.0fms",
            model,
            tokens_in,
            tokens_out,
            cost,
            latency,
        )

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model=model,
            provider=self.name,
            latency_ms=latency,
        )

    def count_tokens(self, text: str) -> int:
        """粗略估算 token 数（Claude 约 1 token ≈ 3.5 字符中文）。"""
        # 简化估算：英文 ~4 字符/token，中文 ~1.5 字符/token
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ) -> Decimal:
        """估算 Claude 调用成本。"""
        model = model or self._default_model
        pricing = self.PRICING.get(model, self.PRICING[self._default_model])
        return Decimal(input_tokens) * pricing["input"] + Decimal(output_tokens) * pricing["output"]


# ──────────────────── DeepSeek Provider ────────────────────


class DeepSeekProvider(LLMProvider):
    """DeepSeek Provider（兼容 OpenAI 格式）。

    主力模型，成本低，适合中低复杂度任务。
    """

    name = "deepseek"
    supported_models = ["deepseek-chat", "deepseek-reasoner"]

    PRICING: dict[str, dict[str, Decimal]] = {
        "deepseek-chat": {
            "input": Decimal("0.00000014"),
            "output": Decimal("0.00000028"),
        },
        "deepseek-reasoner": {
            "input": Decimal("0.00000055"),
            "output": Decimal("0.00000219"),
        },
    }

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 DeepSeek Chat API（OpenAI 兼容格式）。"""
        import httpx

        model = model or "deepseek-chat"
        start = time.time()

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **kwargs,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        content = data["choices"][0]["message"]["content"]
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        cost = self.estimate_cost(tokens_in, tokens_out, model)
        latency = (time.time() - start) * 1000

        logger.info(
            "DeepSeek 调用完成: model=%s tokens_in=%d tokens_out=%d cost=$%s latency=%.0fms",
            model,
            tokens_in,
            tokens_out,
            cost,
            latency,
        )

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model=model,
            provider=self.name,
            latency_ms=latency,
        )

    def count_tokens(self, text: str) -> int:
        """粗略估算 token 数。"""
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ) -> Decimal:
        """估算 DeepSeek 调用成本。"""
        model = model or "deepseek-chat"
        pricing = self.PRICING.get(model, self.PRICING["deepseek-chat"])
        return Decimal(input_tokens) * pricing["input"] + Decimal(output_tokens) * pricing["output"]


# ──────────────────── 本地开源模型 Provider ────────────────────


class LocalProvider(LLMProvider):
    """本地开源模型 Provider（预留接口）。

    支持 vLLM / Ollama 等本地推理引擎。
    """

    name = "local"
    supported_models = ["local-default"]

    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "local-default"
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = model

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用本地模型 API（OpenAI 兼容格式）。"""
        import httpx

        model = model or self._default_model
        start = time.time()

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **kwargs,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        content = data["choices"][0]["message"]["content"]
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        latency = (time.time() - start) * 1000

        logger.info(
            "本地模型调用完成: model=%s tokens_in=%d tokens_out=%d latency=%.0fms",
            model,
            tokens_in,
            tokens_out,
            latency,
        )

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=Decimal("0"),  # 本地模型无费用
            model=model,
            provider=self.name,
            latency_ms=latency,
        )

    def count_tokens(self, text: str) -> int:
        """粗略估算 token 数。"""
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """本地模型无费用。"""
        return Decimal("0")


# ──────────────────── Ollama 本地 Provider ────────────────────


class OllamaProvider(LLMProvider):
    """Ollama 本地模型 Provider。

    优先落地的本地推理方案，通过 Ollama 服务运行开源模型。
    支持 OpenAI 兼容格式的 /v1/chat/completions 接口。
    本地运行无费用。

    常用模型：
    - qwen2.5:7b / qwen2.5:14b
    - llama3.1:8b
    - deepseek-coder-v2:16b
    """

    name = "ollama"
    supported_models = [
        "qwen2.5:7b",
        "qwen2.5:14b",
        "llama3.1:8b",
        "deepseek-coder-v2:16b",
    ]

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
    ) -> None:
        """初始化 Ollama Provider。

        Args:
            base_url: Ollama 服务地址。
            model: 默认模型名称。
        """
        self._base_url = base_url.rstrip("/")
        self._default_model = model
        if model not in self.supported_models:
            self.supported_models = list(self.supported_models) + [model]

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 Ollama API（OpenAI 兼容格式）。

        Args:
            messages: 消息列表。
            model: 模型名称，空字符串使用默认模型。
            max_tokens: 最大输出 token 数。
            temperature: 温度参数。
            **kwargs: 其他参数。

        Returns:
            LLMResponse 响应对象。
        """
        import httpx

        model = model or self._default_model
        start = time.time()

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **kwargs,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        content = data["choices"][0]["message"]["content"]
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        latency = (time.time() - start) * 1000

        logger.info(
            "Ollama 调用完成: model=%s tokens_in=%d tokens_out=%d latency=%.0fms",
            model,
            tokens_in,
            tokens_out,
            latency,
        )

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=Decimal("0"),  # 本地模型无费用
            model=model,
            provider=self.name,
            latency_ms=latency,
        )

    def count_tokens(self, text: str) -> int:
        """粗略估算 token 数。"""
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """本地模型无费用。"""
        return Decimal("0")


# ──────────────────── Provider 注册表 ────────────────────


# AGENT_PROVIDER 注册表：按名称映射 Provider 类
# 支持动态扩展，新增 Provider 只需在此注册
AGENT_PROVIDER: dict[str, type[LLMProvider]] = {
    "claude": ClaudeProvider,
    "deepseek": DeepSeekProvider,
    "local": LocalProvider,
    "ollama": OllamaProvider,
}


def create_provider_from_config(config: dict[str, Any]) -> LLMProvider:
    """从配置字典创建 Provider 实例。

    配置格式：
    {
        "type": "ollama",          # Provider 类型，对应 AGENT_PROVIDER 的 key
        "base_url": "http://...",   # 可选，服务地址
        "model": "qwen2.5:7b",     # 可选，默认模型
        "api_key": "sk-...",       # 可选，API 密钥
    }

    Args:
        config: Provider 配置字典。

    Returns:
        LLMProvider 实例。

    Raises:
        ValueError: 未知的 Provider 类型。
    """
    provider_type = config.get("type", "")
    if provider_type not in AGENT_PROVIDER:
        raise ValueError(
            f"未知的 Provider 类型: {provider_type}，支持的类型: {list(AGENT_PROVIDER.keys())}"
        )

    provider_cls = AGENT_PROVIDER[provider_type]

    # 根据不同类型传递不同参数
    if provider_type in ("ollama", "local"):
        kwargs: dict[str, Any] = {}
        if "base_url" in config:
            kwargs["base_url"] = config["base_url"]
        if "model" in config:
            kwargs["model"] = config["model"]
        return provider_cls(**kwargs)
    elif provider_type in ("claude", "deepseek"):
        kwargs = {}
        if "api_key" in config:
            kwargs["api_key"] = config["api_key"]
        if "base_url" in config:
            kwargs["base_url"] = config["base_url"]
        if "default_model" in config:
            kwargs["default_model"] = config["default_model"]
        return provider_cls(**kwargs)
    else:
        return provider_cls()  # type: ignore[call-arg]


# ──────────────────── LLM 路由器（含 Provider 级 Failover）────────────────────


class LLMRouter:
    """LLM 路由器：按任务复杂度/成本自动选择最优 Provider。

    路由策略（含 local 优先）：
    - 高复杂度 (推理/规划) → Ollama/Local → Claude Opus → DeepSeek Reasoner
    - 中复杂度 (分析/解读) → Ollama/Local → Claude Sonnet → DeepSeek Chat
    - 低复杂度 (分类/提取) → Ollama/Local → DeepSeek Chat → Claude Haiku

    Provider 级 failover：首选失败自动尝试下一个。
    """

    # 路由表：复杂度 → [(provider_name, model), ...] 按优先级排列
    ROUTE_TABLE: dict[TaskComplexity, list[tuple[str, str]]] = {
        TaskComplexity.HIGH: [
            ("ollama", "qwen2.5:14b"),
            ("claude", "claude-opus-4-20250514"),
            ("deepseek", "deepseek-reasoner"),
            ("claude", "claude-sonnet-4-20250514"),
        ],
        TaskComplexity.MEDIUM: [
            ("ollama", "qwen2.5:7b"),
            ("claude", "claude-sonnet-4-20250514"),
            ("deepseek", "deepseek-chat"),
        ],
        TaskComplexity.LOW: [
            ("ollama", "qwen2.5:7b"),
            ("deepseek", "deepseek-chat"),
            ("claude", "claude-3-5-haiku-20241022"),
        ],
    }

    def __init__(self, providers: dict[str, LLMProvider]) -> None:
        """初始化路由器。

        Args:
            providers: Provider 字典，key 为 provider name，value 为 provider 实例。
        """
        self._providers = providers

    async def route(
        self,
        task_complexity: TaskComplexity | str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """根据任务复杂度路由到最优 Provider。

        自动降级：首选 Provider 失败时尝试备选。

        Args:
            task_complexity: 任务复杂度。
            messages: 消息列表。
            max_tokens: 最大输出 token 数。
            temperature: 温度参数。
            **kwargs: 其他参数。

        Returns:
            LLMResponse 响应对象。

        Raises:
            RuntimeError: 所有 Provider 均失败。
        """
        if isinstance(task_complexity, str):
            task_complexity = TaskComplexity(task_complexity)

        routes = self.ROUTE_TABLE.get(task_complexity)
        if routes is None:
            # 降级到 MEDIUM，如果 MEDIUM 也不存在则用第一个可用路由
            routes = self.ROUTE_TABLE.get(
                TaskComplexity.MEDIUM,
                next(iter(self.ROUTE_TABLE.values()), []),
            )

        errors: list[str] = []
        for provider_name, model in routes:
            provider = self._providers.get(provider_name)
            if not provider:
                errors.append(f"Provider '{provider_name}' 未注册")
                continue

            try:
                resp = await provider.complete(
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                return resp
            except Exception as exc:
                error_msg = f"{provider_name}/{model} 调用失败: {exc}"
                logger.warning("路由降级: %s", error_msg)
                errors.append(error_msg)
                continue

        raise RuntimeError(f"所有 Provider 均失败: {'; '.join(errors)}")

    async def route_with_sanitize(
        self,
        task_complexity: TaskComplexity | str,
        system_prompt: str,
        user_text: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """带 Prompt 注入防护的路由调用。

        自动清洗用户文本并用隔离标记包裹。

        Args:
            task_complexity: 任务复杂度。
            system_prompt: 系统提示词。
            user_text: 用户输入文本（将被清洗）。
            max_tokens: 最大输出 token 数。
            temperature: 温度参数。
            **kwargs: 其他参数。

        Returns:
            LLMResponse 响应对象。
        """
        safe_text = sanitize_user_text(user_text)
        wrapped_text = wrap_user_content(safe_text)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": wrapped_text},
        ]

        return await self.route(
            task_complexity=task_complexity,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )


# ──────────────────── Token 计量器 ────────────────────


class TokenMeter:
    """Token 计量器 — 日预算硬上限 + 用量追踪。

    可单测：所有状态均为内部属性，支持注入日期。
    """

    def __init__(self, daily_budget_usd: Decimal = Decimal("50")) -> None:
        """初始化计量器。

        Args:
            daily_budget_usd: 日预算上限（美元）。
        """
        self._daily_budget = daily_budget_usd
        self._daily_usage: Decimal = Decimal("0")
        self._current_date: str = ""
        self._usage_log: list[dict[str, Any]] = []
        self._total_cost: Decimal = Decimal("0")
        self._total_calls: int = 0

    def _ensure_date(self, today: str | None = None) -> str:
        """确保日期计数器正确，跨日自动重置。

        Args:
            today: 当前日期字符串（ISO 格式），None 则自动获取。

        Returns:
            当前日期字符串。
        """
        if today is None:
            today = date.today().isoformat()
        if today != self._current_date:
            if self._current_date:
                logger.info(
                    "Token 计量跨日重置: %s → %s, 昨日消费: $%s",
                    self._current_date,
                    today,
                    self._daily_usage,
                )
            self._daily_usage = Decimal("0")
            self._current_date = today
        return today

    def record(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: Decimal,
        today: str | None = None,
    ) -> None:
        """记录一次 LLM 调用的用量。

        Args:
            provider: Provider 名称。
            model: 模型名称。
            tokens_in: 输入 token 数。
            tokens_out: 输出 token 数。
            cost_usd: 调用成本（美元）。
            today: 当前日期（测试用），None 自动获取。
        """
        today = self._ensure_date(today)

        self._daily_usage += cost_usd
        self._total_cost += cost_usd
        self._total_calls += 1

        entry = {
            "date": today,
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": str(cost_usd),
            "timestamp": datetime.now().isoformat(),
        }
        self._usage_log.append(entry)

        if self._daily_usage >= self._daily_budget:
            logger.error(
                "⚠️ Token 日预算已耗尽！今日消费: $%s / 预算: $%s",
                self._daily_usage,
                self._daily_budget,
            )

    def record_response(self, response: LLMResponse, today: str | None = None) -> None:
        """从 LLMResponse 记录用量（便捷方法）。

        Args:
            response: LLM 响应对象。
            today: 当前日期（测试用）。
        """
        self.record(
            provider=response.provider,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            today=today,
        )

    def check_budget(self, today: str | None = None) -> bool:
        """检查是否在预算内。

        Args:
            today: 当前日期（测试用）。

        Returns:
            True 表示预算充足，False 表示已超限。
        """
        self._ensure_date(today)
        return self._daily_usage < self._daily_budget

    def remaining_budget(self, today: str | None = None) -> Decimal:
        """查询剩余预算。

        Args:
            today: 当前日期（测试用）。

        Returns:
            剩余预算（美元）。
        """
        self._ensure_date(today)
        return max(Decimal("0"), self._daily_budget - self._daily_usage)

    def get_daily_summary(self, today: str | None = None) -> dict[str, Any]:
        """获取当日用量汇总。

        Args:
            today: 当前日期（测试用）。

        Returns:
            汇总字典。
        """
        today = self._ensure_date(today)
        daily_entries = [e for e in self._usage_log if e["date"] == today]

        # 按 Provider 分组
        by_provider: dict[str, dict[str, Any]] = {}
        for entry in daily_entries:
            p = entry["provider"]
            if p not in by_provider:
                by_provider[p] = {
                    "calls": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost_usd": Decimal("0"),
                }
            by_provider[p]["calls"] += 1
            by_provider[p]["tokens_in"] += entry["tokens_in"]
            by_provider[p]["tokens_out"] += entry["tokens_out"]
            by_provider[p]["cost_usd"] += Decimal(entry["cost_usd"])

        # 序列化 Decimal
        by_provider_ser: dict[str, dict[str, Any]] = {}
        for p, stats in by_provider.items():
            by_provider_ser[p] = {
                **stats,
                "cost_usd": str(stats["cost_usd"]),
            }

        return {
            "date": today,
            "total_calls": len(daily_entries),
            "total_cost_usd": str(self._daily_usage),
            "daily_budget_usd": str(self._daily_budget),
            "remaining_usd": str(self.remaining_budget(today)),
            "budget_ok": self.check_budget(today),
            "by_provider": by_provider_ser,
        }

    @property
    def total_cost(self) -> Decimal:
        """累计总消费。"""
        return self._total_cost

    @property
    def total_calls(self) -> int:
        """累计调用次数。"""
        return self._total_calls

    @property
    def usage_log(self) -> list[dict[str, Any]]:
        """完整用量日志（只读副本）。"""
        return list(self._usage_log)
