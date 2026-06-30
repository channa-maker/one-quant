"""
Tests for strategy.registry (register_strategy, get_strategy, list_strategies)
"""

from one_quant.strategy.contracts import Strategy
from one_quant.strategy.registry import (
    STRATEGY_REGISTRY,
    get_strategy,
    list_strategies,
    register_strategy,
)

# ═══════════════════════ strategy.registry ═══════════════════════


class TestStrategyRegistry:
    def test_register_strategy(self):
        # Save and restore
        original = STRATEGY_REGISTRY.copy()

        @register_strategy
        class TestStrat1(Strategy):
            name = "test_reg_strat_1"
            enabled = True

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

        assert "test_reg_strat_1" in STRATEGY_REGISTRY
        assert STRATEGY_REGISTRY["test_reg_strat_1"] is TestStrat1

        # Cleanup
        STRATEGY_REGISTRY.update(original)

    def test_get_strategy(self):
        original = STRATEGY_REGISTRY.copy()

        @register_strategy
        class TestStrat2(Strategy):
            name = "test_reg_strat_2"
            enabled = False

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

        result = get_strategy("test_reg_strat_2")
        assert result is TestStrat2

        STRATEGY_REGISTRY.update(original)

    def test_get_strategy_not_found(self):
        result = get_strategy("nonexistent_strategy_xyz")
        assert result is None

    def test_list_strategies(self):
        original = STRATEGY_REGISTRY.copy()

        @register_strategy
        class TestStrat3(Strategy):
            name = "test_reg_strat_3"
            enabled = True

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

        strategies = list_strategies()
        assert "test_reg_strat_3" in strategies
        assert isinstance(strategies, list)

        STRATEGY_REGISTRY.update(original)

    def test_register_duplicate_same_class(self):
        original = STRATEGY_REGISTRY.copy()

        @register_strategy
        class TestStrat4(Strategy):
            name = "test_reg_strat_4"
            enabled = True

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

        # Re-registering the same class should not raise
        register_strategy(TestStrat4)

        STRATEGY_REGISTRY.update(original)

    def test_register_duplicate_different_class(self):
        original = STRATEGY_REGISTRY.copy()

        @register_strategy
        class TestStrat5a(Strategy):
            name = "test_reg_strat_5_dup"
            enabled = True

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

        try:

            @register_strategy
            class TestStrat5b(Strategy):
                name = "test_reg_strat_5_dup"
                enabled = False

                def on_ticker(self, ticker):
                    return []

                def on_kline(self, kline):
                    return []

            assert False, "Should raise ValueError for duplicate name"
        except ValueError as e:
            assert "已注册" in str(e)

        STRATEGY_REGISTRY.update(original)

    def test_register_missing_name(self):
        original = STRATEGY_REGISTRY.copy()

        try:

            @register_strategy
            class NoNameStrategy(Strategy):
                name = ""
                enabled = True

                def on_ticker(self, ticker):
                    return []

                def on_kline(self, kline):
                    return []

            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "name" in str(e).lower() or "缺少" in str(e)

        STRATEGY_REGISTRY.update(original)

    def test_registry_contains_key(self):
        original = STRATEGY_REGISTRY.copy()

        @register_strategy
        class TestStrat6(Strategy):
            name = "test_reg_strat_6"
            enabled = True

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

        assert "test_reg_strat_6" in STRATEGY_REGISTRY
        assert "nonexistent_xyz" not in STRATEGY_REGISTRY

        STRATEGY_REGISTRY.update(original)

    def test_registry_len(self):
        original = STRATEGY_REGISTRY.copy()

        before = len(STRATEGY_REGISTRY)

        @register_strategy
        class TestStrat7(Strategy):
            name = "test_reg_strat_7"
            enabled = True

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

        assert len(STRATEGY_REGISTRY) == before + 1

        STRATEGY_REGISTRY.update(original)
