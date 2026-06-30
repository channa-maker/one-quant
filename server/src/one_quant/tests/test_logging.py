"""
ONE量化 - 日志测试

验证脱敏功能。
"""

from one_quant.infra.logging import log_mask


class TestLogMask:
    """日志脱敏测试"""

    def test_short_string(self) -> None:
        assert log_mask("abc") == "***"

    def test_normal_string(self) -> None:
        result = log_mask("abcdefghijklmnop")
        assert result == "abcd***mnop"
        assert len(result) == 11  # 4 + 3 + 4

    def test_exact_8_chars(self) -> None:
        assert log_mask("12345678") == "***"

    def test_api_key(self) -> None:
        key = "sk-1234567890abcdef"
        result = log_mask(key)
        assert result.startswith("sk-1")
        assert result.endswith("cdef")
        assert "***" in result
