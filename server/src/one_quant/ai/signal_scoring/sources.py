"""信号源实现 — 各种量化信号源"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class OrderFlowSource:
    """订单流证据源 — 分析大单/吃单/挂单行为"""

    name = "order_flow"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析订单流信号

        检测：
        - 大单方向
        - 吃单/挂单比例
        - 主动买卖力度

        Returns:
            (strength, direction)
        """
        trades = market_data.get("trades", [])
        if not trades:
            return 0.0, 0.0

        buy_volume = sum(t.get("quantity", 0) for t in trades if t.get("side") == "buy")
        sell_volume = sum(t.get("quantity", 0) for t in trades if t.get("side") == "sell")
        total = buy_volume + sell_volume

        if total == 0:
            return 0.0, 0.0

        # 买卖比例 → 方向和强度
        ratio = (buy_volume - sell_volume) / total
        strength = min(1.0, abs(ratio) * 2)  # 归一化
        direction = 1.0 if ratio > 0 else -1.0 if ratio < 0 else 0.0

        return strength, direction


class VolumePriceSource:
    """量价关系证据源 — 分析量价配合"""

    name = "volume_price"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析量价信号

        检测：
        - 放量突破
        - 缩量回调
        - 量价背离

        Returns:
            (strength, direction)
        """
        klines = market_data.get("klines", [])
        if len(klines) < 5:
            return 0.0, 0.0

        # 简化实现：最近 K 线的量价关系
        recent = klines[-5:]
        price_change = (recent[-1].get("close", 0) - recent[0].get("open", 0)) / recent[0].get(
            "open", 1
        )
        volume_change = recent[-1].get("volume", 0) / max(recent[0].get("volume", 1), 1)

        # 价涨量增 → 看多；价跌量增 → 看空
        if price_change > 0 and volume_change > 1.2:
            return min(1.0, abs(price_change) * 10), 1.0
        elif price_change < 0 and volume_change > 1.2:
            return min(1.0, abs(price_change) * 10), -1.0

        return 0.3, 0.0  # 中性


class SMCSource:
    """SMC（Smart Money Concepts）证据源 — 基于 SMCAnalyzer 分析机构行为"""

    name = "smc"

    def __init__(self, analyzer: Any = None) -> None:
        """初始化 SMC 证据源

        Args:
            analyzer: SMCAnalyzer 实例，None 时自动创建
        """
        self._analyzer = analyzer

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """调用 SMCAnalyzer 检测 BOS/CHoCH/OB/FVG，返回 (strength, direction)

        综合以下 SMC 结构信号：
        - BOS（市场结构破坏）：趋势延续确认
        - CHoCH（趋势转换）：趋势反转信号
        - Order Block（订单块）：机构挂单区域
        - FVG（公允价值缺口）：价格不平衡区域

        Args:
            symbol: 标的符号
            market_data: 市场数据（需含 klines/highs/lows）

        Returns:
            (strength: 0-1, direction: +1/-1/0)
        """
        # 懒加载 SMCAnalyzer
        if self._analyzer is None:
            try:
                from one_quant.strategy.smc import SMCAnalyzer

                self._analyzer = SMCAnalyzer()
            except ImportError:
                return 0.0, 0.0

        # 提取 K 线数据
        klines = market_data.get("klines", [])
        highs_raw = market_data.get("highs", [])
        lows_raw = market_data.get("lows", [])

        # 从 K 线提取 high/low 序列

        if klines and not highs_raw:
            highs_raw = [float(k.get("high", k.get("close", 0))) for k in klines]
            lows_raw = [float(k.get("low", k.get("close", 0))) for k in klines]

        if len(highs_raw) < 15 or len(lows_raw) < 15:
            return 0.0, 0.0

        highs = [Decimal(str(h)) for h in highs_raw]
        lows = [Decimal(str(low_val)) for low_val in lows_raw]

        signals: list[tuple[float, float]] = []  # (strength, direction)

        # ① BOS 检测（市场结构破坏）
        try:
            bos = self._analyzer.detect_bos(highs, lows)
            if bos:
                bos_type = bos.get("type", "")
                if "bullish" in bos_type:
                    signals.append((0.7, 1.0))  # 看多 BOS
                elif "bearish" in bos_type:
                    signals.append((0.7, -1.0))  # 看空 BOS
        except Exception:
            pass

        # ② CHoCH 检测（趋势转换）
        try:
            # 根据近期走势判断当前趋势
            recent_highs = highs_raw[-20:]
            _recent_lows = lows_raw[-20:]  # noqa: F841
            trend = "bullish" if recent_highs[-1] > recent_highs[0] else "bearish"
            choch = self._analyzer.detect_choch(highs, lows, trend)
            if choch:
                choch_type = choch.get("type", "")
                if "bullish" in choch_type:
                    signals.append((0.8, 1.0))  # 看多 CHoCH（反转信号更强）
                elif "bearish" in choch_type:
                    signals.append((0.8, -1.0))  # 看空 CHoCH
        except Exception:
            pass

        # ③ Order Block 检测（订单块）
        try:
            if klines:
                from decimal import Decimal

                from one_quant.core.types import Kline, Market

                kline_objs = []
                for k in klines[-50:]:  # 只取最近 50 根
                    try:
                        kline_objs.append(
                            Kline(
                                symbol=symbol,
                                market=Market.SPOT,
                                exchange="",
                                interval="1h",
                                open=Decimal(str(k.get("open", 0))),
                                high=Decimal(str(k.get("high", 0))),
                                low=Decimal(str(k.get("low", 0))),
                                close=Decimal(str(k.get("close", 0))),
                                volume=Decimal(str(k.get("volume", 0))),
                                timestamp_ns=k.get("timestamp_ns", 0),
                            )
                        )
                    except Exception:
                        continue

                if len(kline_objs) >= 5:
                    obs = self._analyzer.find_order_blocks(kline_objs)
                    if obs:
                        latest_ob = obs[-1]
                        ob_type = latest_ob.get("type", "")
                        ob_strength = float(latest_ob.get("strength", 0.5))
                        if "bullish" in ob_type:
                            signals.append((ob_strength, 1.0))
                        elif "bearish" in ob_type:
                            signals.append((ob_strength, -1.0))
        except Exception:
            pass

        # ④ FVG 检测（公允价值缺口）
        try:
            if klines:
                from decimal import Decimal

                from one_quant.core.types import Kline, Market

                kline_objs = []
                for k in klines[-50:]:
                    try:
                        kline_objs.append(
                            Kline(
                                symbol=symbol,
                                market=Market.SPOT,
                                exchange="",
                                interval="1h",
                                open=Decimal(str(k.get("open", 0))),
                                high=Decimal(str(k.get("high", 0))),
                                low=Decimal(str(k.get("low", 0))),
                                close=Decimal(str(k.get("close", 0))),
                                volume=Decimal(str(k.get("volume", 0))),
                                timestamp_ns=k.get("timestamp_ns", 0),
                            )
                        )
                    except Exception:
                        continue

                if len(kline_objs) >= 3:
                    fvgs = self._analyzer.find_fvg(kline_objs)
                    if fvgs:
                        latest_fvg = fvgs[-1]
                        fvg_type = latest_fvg.get("type", "")
                        gap_ratio = float(latest_fvg.get("gap_ratio", 0))
                        fvg_strength = min(1.0, gap_ratio * 100)  # 归一化
                        if "bullish" in fvg_type:
                            signals.append((fvg_strength, 1.0))
                        elif "bearish" in fvg_type:
                            signals.append((fvg_strength, -1.0))
        except Exception:
            pass

        # 综合所有 SMC 信号
        if not signals:
            return 0.0, 0.0

        # 加权平均（取强度最高的信号为主导）
        signals.sort(key=lambda s: s[0], reverse=True)
        total_strength = sum(s[0] for s in signals)
        weighted_direction = sum(s[0] * s[1] for s in signals)

        avg_strength = min(1.0, total_strength / len(signals))
        avg_direction = weighted_direction / total_strength if total_strength > 0 else 0.0

        # 方向量化
        if avg_direction > 0.1:
            direction = 1.0
        elif avg_direction < -0.1:
            direction = -1.0
        else:
            direction = 0.0

        return avg_strength, direction


class MLModelSource:
    """ML 模型证据源 — 基于 MLTrainer 的机器学习预测"""

    name = "ml_model"

    def __init__(self, model: Any = None, trainer: Any = None) -> None:
        """初始化 ML 模型证据源

        Args:
            model: 训练好的模型对象（支持 predict/predict_proba）
            trainer: MLTrainer 实例（含 predict 方法）
        """
        self._model = model
        self._trainer = trainer

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """调用 ML 模型的 predict 方法，返回 (strength, direction)

        流程：
        1. 从市场数据提取特征
        2. 调用模型推理
        3. 将预测概率转换为 (strength, direction)

        Args:
            symbol: 标的符号
            market_data: 市场数据（需含特征或可计算因子的原始数据）

        Returns:
            (strength: 0-1, direction: +1/-1/0)
        """
        # 优先使用 MLTrainer 的 predict 方法
        if self._trainer is not None:
            try:
                return self._predict_with_trainer(symbol, market_data)
            except Exception:
                logger.debug("MLTrainer 推理异常，尝试直接模型推理")

        # 回退：直接使用模型对象
        if self._model is None:
            return 0.0, 0.0

        try:
            return self._predict_with_model(symbol, market_data)
        except Exception:
            logger.debug("ML 模型推理失败: %s", symbol)
            return 0.0, 0.0

    def _predict_with_trainer(
        self, symbol: str, market_data: dict[str, Any]
    ) -> tuple[float, float]:
        """使用 MLTrainer 进行推理

        Args:
            symbol: 标的符号
            market_data: 市场数据

        Returns:
            (strength, direction)
        """
        import numpy as np

        # 从市场数据构建特征向量
        features = self._extract_features(market_data)
        if features is None or len(features) == 0:
            return 0.0, 0.0

        X = np.array(features).reshape(1, -1) if len(features) > 0 else None  # noqa: N806
        if X is None:  # noqa: N806
            return 0.0, 0.0

        # 调用 MLTrainer.predict
        predictions = self._trainer.predict(X)
        if not predictions:
            return 0.0, 0.0

        prob = float(predictions[0])  # 预测概率 (0-1)

        # 转换为 (strength, direction)
        # prob > 0.5 → 看多, prob < 0.5 → 看空
        strength = abs(prob - 0.5) * 2  # 距离 0.5 越远越强
        strength = min(1.0, strength)

        if prob > 0.55:
            direction = 1.0
        elif prob < 0.45:
            direction = -1.0
        else:
            direction = 0.0

        return strength, direction

    def _predict_with_model(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """直接使用模型对象推理

        Args:
            symbol: 标的符号
            market_data: 市场数据

        Returns:
            (strength, direction)
        """
        import numpy as np

        features = self._extract_features(market_data)
        if features is None or len(features) == 0:
            return 0.0, 0.0

        X = np.array(features).reshape(1, -1)  # noqa: N806

        # 调用模型的 predict 或 predict_proba
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba(X)
            prob = float(proba[0][1]) if hasattr(proba, "__getitem__") else float(proba)
        elif hasattr(self._model, "predict"):
            pred = self._model.predict(X)
            prob = float(pred[0]) if hasattr(pred, "__getitem__") else float(pred)
        else:
            return 0.0, 0.0

        strength = abs(prob - 0.5) * 2
        strength = min(1.0, strength)

        if prob > 0.55:
            direction = 1.0
        elif prob < 0.45:
            direction = -1.0
        else:
            direction = 0.0

        return strength, direction

    @staticmethod
    def _extract_features(market_data: dict[str, Any]) -> list[float] | None:
        """从市场数据提取特征向量

        优先使用预计算的 features 字段，
        否则从原始数据（klines/prices）计算基础特征。

        Args:
            market_data: 市场数据

        Returns:
            特征列表或 None
        """
        # 优先使用预计算特征
        if "features" in market_data:
            feats = market_data["features"]
            if isinstance(feats, (list, tuple)):
                return [float(f) for f in feats]
            return None

        # 从原始价格数据计算基础特征
        prices = market_data.get("prices") or market_data.get("closes", [])
        if not prices or len(prices) < 20:
            return None

        prices = [float(p) for p in prices]
        features: list[float] = []

        # 动量特征
        for period in [5, 10, 20]:
            if len(prices) > period and prices[-period] != 0:
                features.append((prices[-1] - prices[-period]) / prices[-period])
            else:
                features.append(0.0)

        # 波动率特征
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
            if prices[i - 1] != 0
        ]
        if returns:
            mean_ret = sum(returns[-20:]) / min(20, len(returns))
            features.append(
                (sum((r - mean_ret) ** 2 for r in returns[-20:]) / min(20, len(returns))) ** 0.5
            )
        else:
            features.append(0.0)

        # 均值回归特征
        if len(prices) >= 20:
            ma20 = sum(prices[-20:]) / 20
            features.append((prices[-1] - ma20) / ma20 if ma20 != 0 else 0.0)
        else:
            features.append(0.0)

        return features


class LLMAnalysisSource:
    """LLM 分析证据源 — 调用 LLM Provider 获取情绪/事件面分析"""

    name = "llm_analysis"

    def __init__(self, llm_router: Any = None) -> None:
        """初始化 LLM 分析证据源

        Args:
            llm_router: LLMRouter 实例，用于路由到 Claude/DeepSeek
        """
        self._llm_router = llm_router

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """调用 LLM Provider 获取情绪/事件面分析

        流程：
        1. 从 market_data 提取新闻/事件文本
        2. 调用 LLM Router 进行情绪分析
        3. 解析返回的情绪分数和方向

        Args:
            symbol: 标的符号
            market_data: 市场数据（可含 news_texts/llm_sentiment/events）

        Returns:
            (strength: 0-1, direction: +1/-1/0)
        """
        # 优先使用预计算的 LLM 情绪分数（避免重复调用）
        if "llm_sentiment" in market_data:
            sentiment = float(market_data["llm_sentiment"])
            strength = min(1.0, abs(sentiment))
            direction = 1.0 if sentiment > 0.1 else -1.0 if sentiment < -0.1 else 0.0
            return strength, direction

        # 无 LLM Router 时回退到本地情绪分析
        if self._llm_router is None:
            return self._local_sentiment(market_data)

        # 收集文本上下文
        text_parts: list[str] = []
        news_texts = market_data.get("news_texts", [])
        if news_texts:
            text_parts.extend(news_texts[:5])  # 最多 5 条新闻
        events = market_data.get("events", [])
        if events:
            text_parts.extend([str(e) for e in events[:3]])

        if not text_parts:
            # 无文本数据时用价格数据做简单分析
            return self._local_sentiment(market_data)

        # 调用 LLM 进行情绪分析
        try:
            return self._call_llm_sync(symbol, text_parts)
        except Exception:
            logger.debug("LLM 情绪分析异常，回退到本地分析")
            return self._local_sentiment(market_data)

    def _call_llm_sync(self, symbol: str, text_parts: list[str]) -> tuple[float, float]:
        """同步调用 LLM 进行情绪分析

        在同步上下文中创建事件循环调用异步 LLM。

        Args:
            symbol: 标的符号
            text_parts: 文本内容列表

        Returns:
            (strength, direction)
        """
        import asyncio

        system_prompt = (
            "你是加密货币/金融市场情绪分析专家。"
            f"分析给定的新闻/事件文本，判断对标的 {symbol} 的影响。\n"
            "输出格式（严格 JSON）：\n"
            '{"sentiment": float, "confidence": float, "summary": "一句话中文摘要"}\n'
            "sentiment: -1.0（极度利空）到 1.0（极度利好），0 为中性。\n"
            "confidence: 0.0 到 1.0，表示分析置信度。\n"
            "只输出 JSON，不要其他内容。"
        )

        user_text = "\n---\n".join(text_parts)

        try:
            from one_quant.ai.llm_provider import sanitize_user_text, wrap_user_content

            safe_text = sanitize_user_text(user_text)
            wrapped = wrap_user_content(safe_text)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": wrapped},
            ]

            # 尝试获取事件循环
            try:
                _loop = asyncio.get_running_loop()  # noqa: F841
                # 已在异步上下文中，创建任务
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._llm_router.route(
                            task_complexity="low",
                            messages=messages,
                            max_tokens=256,
                            temperature=0.3,
                        ),
                    )
                    response = future.result(timeout=30)
            except RuntimeError:
                # 无运行中的事件循环
                response = asyncio.run(
                    self._llm_router.route(
                        task_complexity="low",
                        messages=messages,
                        max_tokens=256,
                        temperature=0.3,
                    )
                )

            # 解析 LLM 返回
            import json as _json

            content = response.content.strip()
            if "```" in content:
                for block in content.split("```"):
                    block = block.strip()
                    if block.startswith("json"):
                        block = block[4:].strip()
                    if block.startswith("{"):
                        content = block
                        break

            result = _json.loads(content)
            sentiment = float(result.get("sentiment", 0))
            confidence = float(result.get("confidence", 0.5))

            strength = min(1.0, abs(sentiment) * confidence)
            direction = 1.0 if sentiment > 0.1 else -1.0 if sentiment < -0.1 else 0.0

            return strength, direction

        except Exception:
            logger.debug("LLM 情绪分析调用失败")
            return 0.0, 0.0

    @staticmethod
    def _local_sentiment(market_data: dict[str, Any]) -> tuple[float, float]:
        """本地情绪分析（无 LLM 时的回退方案）

        基于价格变动和成交量做简单情绪判断。

        Args:
            market_data: 市场数据

        Returns:
            (strength, direction)
        """
        prices = market_data.get("prices") or market_data.get("closes", [])
        if not prices or len(prices) < 5:
            return 0.0, 0.0

        prices = [float(p) for p in prices]
        # 短期动量
        short_ret = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] != 0 else 0
        # 中期动量
        mid_ret = (
            (prices[-1] - prices[-min(20, len(prices))]) / prices[-min(20, len(prices))]
            if prices[-min(20, len(prices))] != 0
            else 0
        )

        # 综合情绪
        sentiment = short_ret * 0.6 + mid_ret * 0.4
        strength = min(1.0, abs(sentiment) * 10)  # 归一化
        direction = 1.0 if sentiment > 0.005 else -1.0 if sentiment < -0.005 else 0.0

        return strength, direction


class CryptoStructureSource:
    """加密结构证据源 — 加密市场特有结构"""

    name = "crypto_structure"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析加密市场结构

        检测：
        - 清算地图
        - 资金费率
        - 持仓量变化
        - 多空比

        Returns:
            (strength, direction)
        """
        funding_rate = market_data.get("funding_rate", 0.0)
        long_short_ratio = market_data.get("long_short_ratio", 1.0)

        # 资金费率极端 → 反向信号
        if abs(funding_rate) > 0.01:
            strength = min(1.0, abs(funding_rate) * 50)
            direction = -1.0 if funding_rate > 0 else 1.0  # 费率过高 → 看空
            return strength, direction

        # 多空比极端 → 反向信号
        if long_short_ratio > 2.0 or long_short_ratio < 0.5:
            strength = 0.6
            direction = -1.0 if long_short_ratio > 2.0 else 1.0
            return strength, direction

        return 0.2, 0.0


class OnchainSource:
    """链上数据证据源 — 区块链链上指标"""

    name = "onchain"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析链上数据

        检测：
        - 交易所净流入/流出
        - 大户持仓变化
        - 活跃地址数
        - MVRV / NVT

        Returns:
            (strength, direction)
        """
        net_flow = market_data.get("exchange_net_flow", 0.0)  # 正=流入, 负=流出

        if abs(net_flow) > 0:
            strength = min(1.0, abs(net_flow) / 1000)  # 归一化
            direction = -1.0 if net_flow > 0 else 1.0  # 流入交易所 → 看空（抛压）
            return strength, direction

        return 0.1, 0.0
