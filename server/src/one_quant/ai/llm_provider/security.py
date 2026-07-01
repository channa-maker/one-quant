"""
LLM Provider — Prompt 注入防护
"""

from __future__ import annotations

import re


def sanitize_user_text(text: str, max_length: int = 8000) -> str:
    """清洗外部用户文本，防止 Prompt 注入。

    策略：
    1. 截断过长文本
    2. 移除常见注入模式
    3. 用隔离标记包裹用户内容
    """
    if not text:
        return ""

    text = text[:max_length]

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
    """用隔离标记包裹用户内容，明确区分系统指令与用户输入。"""
    return f"<user_content>{text}</user_content>"
