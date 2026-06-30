"""ONE量化性能压测 — Locust

运行: locust -f locustfile.py --host http://localhost:8000
"""

from locust import HttpUser, task, between


class OneQuantUser(HttpUser):
    """模拟 ONE量化用户"""
    wait_time = between(1, 5)

    @task(5)
    def get_health(self):
        """健康检查"""
        self.client.get("/health")

    @task(3)
    def get_positions(self):
        """查询持仓"""
        self.client.get("/api/v1/positions")

    @task(3)
    def get_orders(self):
        """查询订单"""
        self.client.get("/api/v1/orders")

    @task(2)
    def get_strategies(self):
        """查询策略"""
        self.client.get("/api/v1/strategies")

    @task(2)
    def get_signals(self):
        """查询信号"""
        self.client.get("/api/v1/signals")

    @task(1)
    def submit_order(self):
        """提交订单"""
        self.client.post("/api/v1/orders", json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": "0.001",
            "price": "50000",
        })

    @task(1)
    def websocket_connect(self):
        """WebSocket 连接测试"""
        # Locust 不直接支持 WS，这里测 HTTP fallback
        self.client.get("/api/v1/ws/health")
