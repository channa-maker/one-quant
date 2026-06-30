"""Grafana 中文大盘配置 — 系统健康 + 数据质量"""

from __future__ import annotations

import json
from pathlib import Path


def generate_dashboard_json() -> dict:
    """生成 Grafana 大盘 JSON 配置"""
    return {
        "annotations": {"list": []},
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "liveNow": False,
        "panels": [
            {
                "title": "🟢 系统健康总览",
                "type": "row",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 0},
                "collapsed": False,
            },
            {
                "title": "行情网关连接状态",
                "type": "stat",
                "gridPos": {"h": 4, "w": 6, "x": 0, "y": 1},
                "targets": [
                    {"expr": "one_quant_market_gateway_connected", "legendFormat": "{{exchange}}"}
                ],
                "fieldConfig": {
                    "defaults": {
                        "mappings": [
                            {
                                "type": "value",
                                "options": {"0": {"text": "❌ 断开", "color": "red"}},
                            },
                            {
                                "type": "value",
                                "options": {"1": {"text": "✅ 连接", "color": "green"}},
                            },
                        ],
                        "thresholds": {
                            "steps": [
                                {"color": "red", "value": None},
                                {"color": "green", "value": 1},
                            ]
                        },
                    }
                },
            },
            {
                "title": "行情数据新鲜度 (秒)",
                "type": "gauge",
                "gridPos": {"h": 4, "w": 6, "x": 6, "y": 1},
                "targets": [
                    {"expr": "one_quant_market_data_age_seconds", "legendFormat": "{{exchange}}"}
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "s",
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": None},
                                {"color": "yellow", "value": 10},
                                {"color": "red", "value": 60},
                            ]
                        },
                    }
                },
            },
            {
                "title": "EventBus 消息吞吐 (每秒)",
                "type": "timeseries",
                "gridPos": {"h": 4, "w": 6, "x": 12, "y": 1},
                "targets": [
                    {
                        "expr": "rate(one_quant_eventbus_publish_total[1m])",
                        "legendFormat": "发布 {{channel}}",
                    },
                    {
                        "expr": "rate(one_quant_eventbus_consume_total[1m])",
                        "legendFormat": "消费 {{channel}}",
                    },
                ],
            },
            {
                "title": "网关重连次数",
                "type": "stat",
                "gridPos": {"h": 4, "w": 6, "x": 18, "y": 1},
                "targets": [
                    {
                        "expr": "one_quant_market_gateway_reconnects_total",
                        "legendFormat": "{{exchange}}",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": None},
                                {"color": "orange", "value": 5},
                                {"color": "red", "value": 20},
                            ]
                        }
                    }
                },
            },
            {
                "title": "📊 数据质量",
                "type": "row",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 5},
                "collapsed": False,
            },
            {
                "title": "数据质检通过率",
                "type": "gauge",
                "gridPos": {"h": 4, "w": 8, "x": 0, "y": 6},
                "targets": [
                    {
                        "expr": "one_quant_data_quality_checks_total{result='passed'} / (one_quant_data_quality_checks_total{result='passed'} + one_quant_data_quality_checks_total{result='rejected'})",
                        "legendFormat": "通过率",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "percentunit",
                        "thresholds": {
                            "steps": [
                                {"color": "red", "value": None},
                                {"color": "yellow", "value": 0.95},
                                {"color": "green", "value": 0.99},
                            ]
                        },
                    }
                },
            },
            {
                "title": "数据质检告警",
                "type": "stat",
                "gridPos": {"h": 4, "w": 8, "x": 8, "y": 6},
                "targets": [
                    {
                        "expr": "one_quant_data_quality_alerts_total",
                        "legendFormat": "{{alert_type}}",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": None},
                                {"color": "orange", "value": 10},
                                {"color": "red", "value": 100},
                            ]
                        }
                    }
                },
            },
            {
                "title": "Bronze 层写入量",
                "type": "timeseries",
                "gridPos": {"h": 4, "w": 8, "x": 16, "y": 6},
                "targets": [
                    {
                        "expr": "rate(one_quant_data_bronze_writes_total[5m])",
                        "legendFormat": "{{source}}/{{table}}",
                    }
                ],
            },
            {
                "title": "💰 风控与交易",
                "type": "row",
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": 10},
                "collapsed": False,
            },
            {
                "title": "风控决策分布",
                "type": "piechart",
                "gridPos": {"h": 4, "w": 8, "x": 0, "y": 11},
                "targets": [
                    {"expr": "one_quant_risk_decisions_total", "legendFormat": "{{decision}}"}
                ],
            },
            {
                "title": "风控决策延迟 P99",
                "type": "stat",
                "gridPos": {"h": 4, "w": 8, "x": 8, "y": 11},
                "targets": [
                    {
                        "expr": "histogram_quantile(0.99, rate(one_quant_risk_decision_latency_seconds_bucket[5m]))",
                        "legendFormat": "P99",
                    }
                ],
                "fieldConfig": {
                    "defaults": {
                        "unit": "s",
                        "thresholds": {
                            "steps": [
                                {"color": "green", "value": None},
                                {"color": "yellow", "value": 0.005},
                                {"color": "red", "value": 0.01},
                            ]
                        },
                    }
                },
            },
            {
                "title": "订单统计",
                "type": "timeseries",
                "gridPos": {"h": 4, "w": 8, "x": 16, "y": 11},
                "targets": [
                    {
                        "expr": "rate(one_quant_orders_total[5m])",
                        "legendFormat": "下单 {{exchange}}",
                    },
                    {
                        "expr": "rate(one_quant_fills_total[5m])",
                        "legendFormat": "成交 {{exchange}}",
                    },
                ],
            },
        ],
        "refresh": "10s",
        "schemaVersion": 38,
        "style": "dark",
        "tags": ["one-quant", "中文"],
        "templating": {"list": []},
        "time": {"from": "now-1h", "to": "now"},
        "title": "ONE量化 · 系统监控大盘",
        "uid": "one-quant-main",
    }


def save_dashboard(path: str = "deploy/grafana/dashboards/one-quant.json") -> None:
    """保存大盘配置到文件"""
    dashboard = generate_dashboard_json()
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
