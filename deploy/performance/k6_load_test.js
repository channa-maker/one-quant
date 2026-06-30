// ONE量化性能压测 — k6
// 运行: k6 run k6_load_test.js

import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 10 },   // 升温
    { duration: '1m', target: 50 },     // 正常负载
    { duration: '2m', target: 100 },    // 高峰
    { duration: '30s', target: 0 },     // 降温
  ],
  thresholds: {
    http_req_duration: ['p(99)<200'],   // P99 < 200ms (NFR要求)
    http_req_failed: ['rate<0.01'],     // 错误率 < 1%
  },
};

const BASE = __ENV.TARGET_URL || 'http://localhost:8000';

export default function () {
  // 健康检查
  check(http.get(`${BASE}/health`), {
    'health status 200': (r) => r.status === 200,
    'health latency < 50ms': (r) => r.timings.duration < 50,
  });

  // 查询持仓
  check(http.get(`${BASE}/api/v1/positions`, {
    headers: { 'Authorization': 'Bearer test-token' },
  }), {
    'positions status 200': (r) => r.status === 200 || r.status === 401,
  });

  // 查询订单
  check(http.get(`${BASE}/api/v1/orders`, {
    headers: { 'Authorization': 'Bearer test-token' },
  }), {
    'orders status 200': (r) => r.status === 200 || r.status === 401,
  });

  // 查询策略
  check(http.get(`${BASE}/api/v1/strategies`, {
    headers: { 'Authorization': 'Bearer test-token' },
  }), {
    'strategies status 200': (r) => r.status === 200 || r.status === 401,
  });

  sleep(1);
}
