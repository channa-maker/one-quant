"""
ONE量化 - LLM 多 Provider 接入层

支持 Claude / DeepSeek / 本地模型等多 Provider，
按任务复杂度自动路由，Token 计量 + 日预算硬上限。
"""

from __future__ import annotations

from typing import Any

from one_quant.ai.llm_provider.base import LLMProvider
from one_quant.ai.llm_provider.claude import ClaudeProvider
from one_quant.ai.llm_provider.deepseek import DeepSeekProvider
from one_quant.ai.llm_provider.local import LocalProvider
from one_quant.ai.llm_provider.meter import TokenMeter
from one_quant.ai.llm_provider.models import LLMResponse, TaskComplexity
from one_quant.ai.llm_provider.ollama import OllamaProvider
from one_quant.ai.llm_provider.router import LLMRouter
from one_quant.ai.llm_provider.security import sanitize_user_text, wrap_user_content

# Provider 注册表：类型名 → Provider 类
AGENT_PROVIDER: dict[str, type[LLMProvider]] = {
    "claude": ClaudeProvider,
    "deepseek": DeepSeekProvider,
    "local": LocalProvider,
    "ollama": OllamaProvider,
}


def create_provider_from_config(config: dict[str, Any]) -> LLMProvider:
    """从配置字典创建 provider 实例。

    Args:
        config: 配置字典，必须包含 "type" 键。
            - type: provider 类型（claude/deepseek/local/ollama）
            - api_key: API 密钥（claude/deepseek 需要）
            - base_url: 基础 URL（local/ollama 需要）
            - model: 默认模型

    Returns:
        LLMProvider 实例。

    Raises:
        ValueError: 未知的 provider 类型。
    """
    provider_type = config.get("type", "")
    provider_cls = AGENT_PROVIDER.get(provider_type)

    if provider_cls is None:
        raise ValueError(f"未知的 provider 类型: {provider_type}")

    kwargs: dict[str, Any] = {}
    if "api_key" in config:
        kwargs["api_key"] = config["api_key"]
    if "base_url" in config:
        kwargs["base_url"] = config["base_url"]
    if "model" in config:
        kwargs["model"] = config["model"]

    return provider_cls(**kwargs)


__all__ = [
    "AGENT_PROVIDER",
    "ClaudeProvider",
    "DeepSeekProvider",
    "LLMProvider",
    "LLMResponse",
    "LLMRouter",
    "LocalProvider",
    "OllamaProvider",
    "TaskComplexity",
    "TokenMeter",
    "create_provider_from_config",
    "sanitize_user_text",
    "wrap_user_content",
]
