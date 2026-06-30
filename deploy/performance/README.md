# 性能压测

## Locust

```bash
pip install locust
cd deploy/performance
locust -f locustfile.py --host http://localhost:8000
```

访问 http://localhost:8089 启动压测。

## k6

```bash
# 安装 k6
brew install k6  # macOS
# 或
sudo snap install k6  # Linux

# 运行压测
k6 run k6_load_test.js

# 自定义目标
TARGET_URL=http://your-api:8000 k6 run k6_load_test.js
```

## NFR 阈值

| 指标 | 目标 | k6 阈值 |
|------|------|---------|
| 行情→信号→下单 P99 | < 200ms | `p(99)<200` |
| 系统可用性 | 99.9% | — |
| 数据管道吞吐 | ≥ 50万 tick/秒 | — |
| 风控决策延迟 P99 | < 5ms | — |
| HTTP 错误率 | < 1% | `rate<0.01` |
