"""
ONE量化 - 注册表测试

验证策略/因子/算法注册表的注册和查询。
"""

import pytest

from one_quant.infra.registry import Registry


class TestRegistry:
    """通用注册表测试"""

    def test_register_and_get(self) -> None:
        reg = Registry[str]("test")

        @reg.register("hello")
        def greet() -> str:
            return "hello"

        assert reg.get("hello") is greet
        assert "hello" in reg
        assert len(reg) == 1

    def test_duplicate_raises(self) -> None:
        reg = Registry[str]("test")

        @reg.register("hello")
        def greet() -> str:
            return "hello"

        with pytest.raises(ValueError, match="已注册"):

            @reg.register("hello")
            def greet2() -> str:
                return "hello2"

    def test_get_or_raise(self) -> None:
        reg = Registry[str]("test")

        @reg.register("hello")
        def greet() -> str:
            return "hello"

        assert reg.get_or_raise("hello") is greet
        with pytest.raises(KeyError, match="未注册"):
            reg.get_or_raise("nonexistent")

    def test_list_keys(self) -> None:
        reg = Registry[str]("test")
        reg.register("a")("value_a")
        reg.register("b")("value_b")
        assert sorted(reg.list_keys()) == ["a", "b"]
