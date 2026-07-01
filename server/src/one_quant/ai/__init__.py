"""AI 智能体框架 — 多 Provider + token 计量 + 日预算硬上限 + 机构记忆"""

from __future__ import annotations

from one_quant.ai.llm_provider import (
    AGENT_PROVIDER,
    ClaudeProvider,
    DeepSeekProvider,
    LLMProvider,
    LLMResponse,
    LLMRouter,
    LocalProvider,
    OllamaProvider,
    TaskComplexity,
    TokenMeter,
    create_provider_from_config,
    sanitize_user_text,
    wrap_user_content,
)
from one_quant.ai.memory import (
    Document,
    DocumentType,
    InstitutionalMemory,
    SearchResult,
    SimpleVectorizer,
)

# 兼容旧入口：保留原有类名映射
AnthropicProvider = ClaudeProvider
LLMTokenMeter = TokenMeter

__all__ = [
    # LLM Provider 层
    "LLMProvider",
    "LLMResponse",
    "LLMRouter",
    "AGENT_PROVIDER",
    "ClaudeProvider",
    "DeepSeekProvider",
    "LocalProvider",
    "OllamaProvider",
    "TaskComplexity",
    "TokenMeter",
    "create_provider_from_config",
    "sanitize_user_text",
    "wrap_user_content",
    # 机构记忆
    "InstitutionalMemory",
    "SimpleVectorizer",
    "Document",
    "SearchResult",
    "DocumentType",
    # 兼容旧名
    "AnthropicProvider",
    "LLMTokenMeter",
]
