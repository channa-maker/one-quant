"""测试：插件注册表"""

import pytest

from one_quant.infra.registry import Registry


def test_register_and_get() -> None:
    """注册并查询"""
    registry = Registry[str]()

    @registry.register("my_item")
    class MyItem:
        pass

    assert registry.get("my_item") is MyItem
    assert registry.get("nonexistent") is None


def test_get_or_raise() -> None:
    """get_or_raise 找不到时抛异常"""
    registry = Registry[str]()
    with pytest.raises(KeyError, match="not_found"):
        registry.get_or_raise("not_found")


def test_list_keys() -> None:
    """列出所有注册名"""
    registry = Registry[str]()

    @registry.register("a")
    class A:
        pass

    @registry.register("b")
    class B:
        pass

    assert sorted(registry.list_keys()) == ["a", "b"]


def test_duplicate_register_raises() -> None:
    """重复注册抛异常"""
    registry = Registry[str]()

    @registry.register("dup")
    class First:
        pass

    with pytest.raises(ValueError, match="已注册"):

        @registry.register("dup")
        class Second:
            pass


def test_decorator_returns_class() -> None:
    """装饰器返回原类（不吞掉）"""
    registry = Registry[str]()

    @registry.register("my_class")
    class MyClass:
        pass

    assert MyClass.__name__ == "MyClass"
