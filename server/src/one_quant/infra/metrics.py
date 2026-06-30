"""Prometheus 指标埋点 — 行情新鲜度、队列深度、延迟分段"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

# ── 系统信息 ──────────────────────────────────────────────────────────

SYSTEM_INFO = Info("one_quant", "ONE量化系统信息")
SYSTEM_INFO.info({"version": "0.1.0", "component": "server"})

# ── 行情指标 ──────────────────────────────────────────────────────────

# 行情消息计数（按交易所、通道分类）
MARKET_MESSAGES_TOTAL = Counter(
    "one_quant_market_messages_total",
    "行情消息总数",
    ["exchange", "channel"],  # channel: ticker / trade / orderbook / kline
)

# 行情数据新鲜度（秒）
MARKET_DATA_AGE_SECONDS = Gauge(
    "one_quant_market_data_age_seconds",
    "距最后一条行情消息的秒数",
    ["exchange"],
)

# 行情网关连接状态（1=连接, 0=断开）
MARKET_GATEWAY_CONNECTED = Gauge(
    "one_quant_market_gateway_connected",
    "行情网关连接状态",
    ["exchange"],
)

# 行情网关重连次数
MARKET_GATEWAY_RECONNECTS = Counter(
    "one_quant_market_gateway_reconnects_total",
    "行情网关重连次数",
    ["exchange"],
)

# ── EventBus 指标 ─────────────────────────────────────────────────────

# EventBus 发布计数
EVENTBUS_PUBLISH_TOTAL = Counter(
    "one_quant_eventbus_publish_total",
    "EventBus 消息发布总数",
    ["channel"],
)

# EventBus 消费计数
EVENTBUS_CONSUME_TOTAL = Counter(
    "one_quant_eventbus_consume_total",
    "EventBus 消息消费总数",
    ["channel"],
)

# EventBus 消费延迟
EVENTBUS_CONSUME_LATENCY = Histogram(
    "one_quant_eventbus_consume_latency_seconds",
    "EventBus 消费延迟（发布→消费）",
    ["channel"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# ── 数据管道指标 ──────────────────────────────────────────────────────

# Bronze 层写入计数
DATA_BRONZE_WRITES = Counter(
    "one_quant_data_bronze_writes_total",
    "Bronze 层写入记录数",
    ["source", "table"],
)

# 数据质检通过/拒绝计数
DATA_QUALITY_CHECKS = Counter(
    "one_quant_data_quality_checks_total",
    "数据质检结果",
    ["result"],  # passed / rejected
)

# 数据质检告警计数
DATA_QUALITY_ALERTS = Counter(
    "one_quant_data_quality_alerts_total",
    "数据质检告警次数",
    ["alert_type"],  # out_of_order / jump / latency / duplicate
)

# ── 风控指标 ──────────────────────────────────────────────────────────

# 风控决策计数
RISK_DECISIONS_TOTAL = Counter(
    "one_quant_risk_decisions_total",
    "风控决策总数",
    ["decision"],  # APPROVE / REJECT / REDUCE / FLATTEN
)

# 风控决策延迟
RISK_DECISION_LATENCY = Histogram(
    "one_quant_risk_decision_latency_seconds",
    "风控决策延迟",
    buckets=[0.0005, 0.001, 0.005, 0.01, 0.05, 0.1],
)

# ── 交易指标 ──────────────────────────────────────────────────────────

# 订单计数
ORDERS_TOTAL = Counter(
    "one_quant_orders_total",
    "订单总数",
    ["exchange", "side", "order_type"],
)

# 成交计数
FILLS_TOTAL = Counter(
    "one_quant_fills_total",
    "成交总数",
    ["exchange", "side"],
)

# 持仓价值
PORTFOLIO_VALUE = Gauge(
    "one_quant_portfolio_value",
    "当前组合价值（USD）",
    ["currency"],
)

# 未实现盈亏
UNREALIZED_PNL = Gauge(
    "one_quant_unrealized_pnl",
    "未实现盈亏（USD）",
    ["strategy"],
)
