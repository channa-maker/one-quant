# ONE量化

**机构级智能量化交易系统** — 覆盖加密货币（现货/合约/期权）与美股/美期权，LLM 定性分析 + ML 定量预测双 AI 引擎驱动，7×24 小时全自动运行。

---

## 目录

- [快速启动](#快速启动)
- [项目结构](#项目结构)
- [架构概览](#架构概览)
- [模块清单](#模块清单)
- [开发规范](#开发规范)
- [测试](#测试)
- [部署](#部署)
- [文档链接](#文档链接)
- [许可证](#许可证)

---

## 快速启动

### 前置要求

| 工具 | 版本要求 | 说明 |
|------|----------|------|
| Python | ≥ 3.12 | 后端运行时 |
| Node.js | ≥ 18 | 前端构建 |
| Docker & Docker Compose | 最新稳定版 | 基础设施与部署 |
| Git | ≥ 2.30 | 版本控制 |

### 1. 克隆项目

```bash
git clone <repo-url>
cd one-quant
```

### 2. 配置环境变量

```bash
# 后端环境变量
cp server/.env.example server/.env
# 编辑 server/.env 填入实际密钥与连接信息

# Docker 环境变量（可选）
cp deploy/docker/.env.docker deploy/docker/.env
```

### 3. 启动基础设施

```bash
cd deploy/docker
docker compose up -d postgres timescaledb redis clickhouse minio
```

### 4. 后端开发

```bash
cd server

# 安装依赖（推荐使用 uv）
pip install uv
uv pip install -e ".[dev]"

# 启动 API 服务
uvicorn one_quant.api.main:app --host 0.0.0.0 --port 8000 --reload

# 启动数据采集器
python -m one_quant.data.collector_main

# 启动策略引擎
python -m one_quant.runner.main
```

### 5. 前端开发

```bash
cd web
npm install
npm run dev          # 启动开发服务器（默认 http://localhost:5173）
npm run build        # 生产构建
npm run lint         # 代码检查
npm run type-check   # TypeScript 类型检查
```

### 6. 移动端开发

```bash
cd mobile
npm install
npx expo start       # 启动 Expo 开发服务器
```

### 7. 一键启动全部服务

```bash
cd deploy/docker
docker compose up -d
```

### 服务地址一览

| 服务 | 地址 | 说明 |
|------|------|------|
| API 服务 | http://localhost:8000 | FastAPI 主服务 |
| API 文档 | http://localhost:8000/docs | Swagger UI |
| PostgreSQL | localhost:5432 | 主数据库 |
| TimescaleDB | localhost:5433 | 时序数据库 |
| Redis | localhost:6379 | 缓存与消息总线 |
| ClickHouse | localhost:8123 | 分析数据库 |
| MinIO | http://localhost:9001 | 对象存储（控制台） |
| Prometheus | http://localhost:9090 | 监控指标 |
| Grafana | http://localhost:3000 | 监控面板 |
| Web 前端 | http://localhost:5173 | 开发服务器 |

---

## 项目结构

```
one-quant/
├── server/                         # 后端服务（Python 3.12 + FastAPI）
│   ├── src/one_quant/
│   │   ├── api/                    # HTTP/WebSocket API 层
│   │   │   ├── routes/             # 路由：health / orders / positions / strategies
│   │   │   ├── app.py              # FastAPI 应用工厂
│   │   │   ├── main.py             # 启动入口
│   │   │   ├── ws_hub.py           # WebSocket 消息枢纽
│   │   │   ├── permissions.py      # 权限与 RBAC
│   │   │   └── degradation.py      # 降级策略
│   │   ├── core/                   # 核心类型定义
│   │   │   └── types.py            # 通用领域类型（Ticker / Kline / OrderBook 等）
│   │   ├── data/                   # 数据采集与数据湖
│   │   │   ├── collector.py        # 采集器核心
│   │   │   ├── collector_main.py   # 采集器进程入口
│   │   │   ├── bronze.py           # Bronze 层（原始落盘）
│   │   │   ├── silver.py           # Silver 层（清洗对齐）
│   │   │   ├── gold.py             # Gold 层（因子计算）
│   │   │   ├── quality.py          # 数据质检门
│   │   │   ├── feature_store.py    # 特征商店
│   │   │   ├── instrument_master.py# 标的主数据
│   │   │   ├── lineage.py          # 数据血缘
│   │   │   ├── replay.py           # 历史回放
│   │   │   ├── symbol_validator.py # 标的校验
│   │   │   ├── tick_collector.py   # Tick 采集
│   │   │   └── tiered_storage.py   # 冷热分层存储
│   │   ├── strategy/               # 策略引擎
│   │   │   ├── contracts.py        # 策略接口契约（ABC）
│   │   │   ├── registry.py         # 策略注册表
│   │   │   ├── protocols.py        # 策略协议定义
│   │   │   ├── backtest.py         # 回测引擎
│   │   │   ├── ema_cross.py        # EMA 交叉策略
│   │   │   ├── rsi_reversal.py     # RSI 反转策略
│   │   │   ├── grid.py             # 网格策略
│   │   │   ├── smc.py              # 聪明钱结构策略
│   │   │   ├── order_flow.py       # 订单流策略
│   │   │   ├── volume_structure.py # 量价结构策略
│   │   │   ├── crypto_structure.py # 加密结构策略
│   │   │   ├── options.py          # 期权策略
│   │   │   ├── exit.py             # 出场引擎
│   │   │   ├── consistency.py      # 回测一致性校验
│   │   │   ├── corporate_actions.py# 公司行为处理
│   │   │   └── us_market_rules.py  # 美股规则
│   │   ├── runner/                 # 策略执行引擎
│   │   │   ├── engine.py           # 策略主循环
│   │   │   └── backtest.py         # 回测运行器
│   │   ├── risk/                   # 四层风控引擎
│   │   │   ├── engine.py           # 风控网关
│   │   │   ├── contracts.py        # 风控接口
│   │   │   ├── rules/              # 风控规则
│   │   │   │   ├── l1_static.py    # L1 静态限额
│   │   │   │   ├── l2_realtime.py  # L2 实时敞口
│   │   │   │   ├── l3_drawdown.py  # L3 回撤熔断
│   │   │   │   └── l4_circuit_breaker.py # L4 熔断器
│   │   │   ├── portfolio_optimizer.py # 组合优化
│   │   │   ├── stress_test.py      # 压力测试
│   │   │   └── audit.py            # 风控审计
│   │   ├── execution/              # 执行引擎（OMS/EMS）
│   │   │   ├── oms.py              # 订单管理系统
│   │   │   ├── ems.py              # 执行管理系统
│   │   │   ├── algorithms.py       # 执行算法（TWAP/VWAP/POV）
│   │   │   ├── netting.py          # 多策略净额轧差
│   │   │   ├── rate_limiter.py     # 客户端限流
│   │   │   ├── tca.py              # 交易成本分析
│   │   │   ├── ledger.py           # 复式记账
│   │   │   ├── audit.py            # 执行审计
│   │   │   ├── paper_trading.py    # 模拟盘
│   │   │   └── position_recovery.py# 持仓恢复
│   │   ├── exchange/               # 交易所/券商适配器
│   │   │   ├── binance_adapter.py  # 币安适配器
│   │   │   ├── binance_trading.py  # 币安交易
│   │   │   ├── binance_ws.py       # 币安 WebSocket
│   │   │   ├── okx_adapter.py      # OKX 适配器
│   │   │   ├── okx_trading.py      # OKX 交易
│   │   │   ├── okx_ws.py           # OKX WebSocket
│   │   │   ├── deribit_adapter.py  # Deribit 适配器
│   │   │   ├── ibkr_adapter.py     # IBKR 适配器
│   │   │   ├── unified_broker.py   # 统一券商抽象层
│   │   │   ├── gateway_base.py     # 网关基类
│   │   │   ├── contracts.py        # 适配器接口
│   │   │   └── pool.py             # 连接池管理
│   │   ├── marketgw/               # 行情网关
│   │   │   ├── base.py             # 行情网关基类
│   │   │   ├── binance_ws.py       # 币安行情
│   │   │   ├── okx_ws.py           # OKX 行情
│   │   │   ├── normalizer.py       # 行情归一化
│   │   │   ├── reconnect.py        # 断线重连
│   │   │   └── collector_main.py   # 行情采集入口
│   │   ├── ai/                     # AI 引擎
│   │   │   ├── llm_provider.py     # LLM 多 Provider 接入
│   │   │   ├── agents.py           # AI 智能体调度
│   │   │   ├── memory.py           # 机构记忆 / RAG
│   │   │   ├── signal_scoring.py   # 信号评分引擎
│   │   │   ├── evolution.py        # 自进化平台
│   │   │   └── model_governance.py # 模型治理
│   │   ├── agents/                 # LLM 智能体实现
│   │   │   ├── base.py             # 智能体基类
│   │   │   ├── briefer.py          # 简报官
│   │   │   ├── watcher.py          # 哨兵
│   │   │   ├── triager.py          # 分诊员
│   │   │   ├── analyzer.py         # 解读员
│   │   │   ├── sentiment.py        # 情绪分析师
│   │   │   ├── macro_agent.py      # 宏观分析师
│   │   │   └── debate.py           # 多空辩论组
│   │   ├── ml/                     # ML 选股选币
│   │   │   ├── factors.py          # 因子库
│   │   │   ├── pipeline.py         # 训练管线
│   │   │   ├── trainer.py          # 模型训练
│   │   │   └── model_registry.py   # 模型注册表
│   │   ├── screener/               # 选股选币引擎
│   │   │   ├── pipeline.py         # 选股管线
│   │   │   ├── filters.py          # 过滤器
│   │   │   └── constraints.py      # 约束条件
│   │   ├── accounting/             # 账户与会计
│   │   │   ├── account.py          # 账户管理
│   │   │   ├── settlement.py       # 结算
│   │   │   └── tax.py              # 税务处理
│   │   ├── infra/                  # 基础设施
│   │   │   ├── config.py           # 配置管理（pydantic-settings）
│   │   │   ├── event_bus.py        # EventBus（Redis Pub/Sub + Streams）
│   │   │   ├── logging.py          # 结构化日志
│   │   │   ├── metrics.py          # Prometheus 指标
│   │   │   ├── message_envelope.py # 消息信封
│   │   │   ├── registry.py         # 插件注册表
│   │   │   ├── notifier.py         # 通知器
│   │   │   ├── tracing.py          # OpenTelemetry 链路追踪
│   │   │   ├── grafana_dashboard.py# Grafana 大盘生成
│   │   │   ├── watchdog.py         # 看门狗
│   │   │   ├── self_heal.py        # 自愈策略
│   │   │   ├── stream_persistence.py # 流持久化
│   │   │   ├── incident.py         # 事故管理
│   │   │   ├── runbook.py          # 运维手册
│   │   │   ├── disaster_recovery.py# 灾备
│   │   │   ├── change_management.py# 变更管理
│   │   │   └── capacity.py         # 容量分析
│   │   └── tests/                  # 测试套件
│   │       ├── test_api.py
│   │       ├── test_accounting.py
│   │       ├── test_agents.py
│   │       ├── test_ai.py
│   │       ├── test_config.py
│   │       ├── test_data_quality.py
│   │       ├── test_ems.py
│   │       ├── test_event_bus.py
│   │       ├── test_exchange.py
│   │       ├── test_execution.py
│   │       ├── test_factors.py
│   │       ├── test_infra.py
│   │       ├── test_instrument_master.py
│   │       ├── test_logging.py
│   │       ├── test_marketgw.py
│   │       ├── test_ml.py
│   │       ├── test_oms.py
│   │       ├── test_quality.py
│   │       ├── test_rate_limiter.py
│   │       ├── test_registry.py
│   │       ├── test_risk_engine.py
│   │       ├── test_screener.py
│   │       ├── test_silver.py
│   │       ├── test_strategies.py
│   │       ├── test_strategy_runner.py
│   │       └── test_types.py
│   ├── pyproject.toml              # 项目配置与依赖
│   └── .env.example                # 环境变量模板
├── web/                            # Web 前端（React 18 + TypeScript + Vite + Ant Design 5）
│   ├── src/
│   │   ├── pages/                  # 页面组件
│   │   │   ├── Dashboard.tsx       # 总览大盘
│   │   │   ├── TradingTerminal.tsx # 交易终端
│   │   │   ├── StrategyManagement.tsx # 策略管理
│   │   │   ├── AIResearch.tsx      # AI 研报
│   │   │   ├── Portfolio.tsx       # 持仓账户
│   │   │   ├── RiskCenter.tsx      # 风控中心
│   │   │   ├── SystemMonitor.tsx   # 系统监控
│   │   │   └── Workstation.tsx     # 多屏盯盘工作站
│   │   ├── components/             # 通用组件
│   │   │   ├── monitoring/         # 盯盘组件（DOM / Footprint / Heatmap / CVD 等）
│   │   │   ├── SignalCard.tsx      # 信号卡
│   │   │   └── LayoutPanel.tsx     # 面板布局
│   │   ├── hooks/                  # 自定义 Hook
│   │   ├── store/                  # 状态管理（Zustand）
│   │   ├── services/               # API 服务层
│   │   └── types/                  # TypeScript 类型
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── mobile/                         # 移动端（Expo + React Native）
│   ├── src/
│   │   ├── screens/                # 页面
│   │   ├── hooks/                  # 自定义 Hook
│   │   └── services/               # 推送通知等服务
│   ├── App.tsx
│   └── package.json
├── deploy/
│   ├── docker/                     # Docker 部署配置
│   │   ├── docker-compose.yml      # 服务编排
│   │   ├── Dockerfile              # 应用镜像
│   │   ├── prometheus.yml          # Prometheus 配置
│   │   └── .env.docker             # Docker 环境变量模板
│   └── grafana/
│       └── dashboards/             # Grafana 大盘 JSON
├── docs/
│   ├── ONE量化_开发文档_v2.0_完整版.md  # 完整设计文档
│   └── ONE量化_开发工单_Backlog.md      # 开发工单
├── .github/
│   └── workflows/
│       └── ci.yml                  # CI 流水线
├── CONTRIBUTING.md                 # 贡献指南
├── CHANGELOG.md                    # 变更日志
└── README.md                       # 本文件
```

---

## 架构概览

### 系统总览

ONE量化 采用**事件驱动 + 三路径分层**架构：

```
┌──────────────────────────────────────────────────────────┐
│                    接入层 / 前端                           │
│     Web 交易终端 · 多屏盯盘工作站 · 移动端 · Grafana       │
└─────────────┬────────────────────────────┬───────────────┘
              │ HTTPS / WebSocket          │
┌─────────────▼────────────────────────────▼───────────────┐
│              API 网关层 (FastAPI)                          │
│    认证鉴权 · RBAC · 限流 · 幂等校验 · WS Hub              │
└─────────────┬────────────────────────────────────────────┘
              │ EventBus (Redis Pub/Sub + Streams)
┌─────────────▼────────────────────────────────────────────┐
│  热路径 (μs~ms)  行情 → 策略 → 风控 → 执行                │
│  温路径 (s~min)  调度 · AI 智能体 · 选股选币 · 持仓管理     │
│  冷路径 (离线)   数据湖 · 因子计算 · 模型训练 · 回测        │
└─────────────┬────────────────────────────────────────────┘
              ▼
  存储: TimescaleDB · PostgreSQL · ClickHouse ·
        DuckDB/Parquet · Redis · MinIO
```

### 核心数据流

```
交易所行情 → 行情网关(归一化) → EventBus(market.*)
  → 策略引擎 on_ticker/on_kline → Signal
  → 风控网关 check() (L1→L2→L3→L4) → APPROVE/REJECT
  → OMS.submit() → 算法拆单 → 交易所 API
  → 成交回报 → 持仓更新 → EventBus(fill.*) → 前端/审计/AI
```

### 进程模型

| 进程 | 职责 | 说明 |
|------|------|------|
| `one-api` | HTTP/WS、鉴权、查询 | FastAPI 主服务 |
| `one-runner` | 策略主循环 | 单 asyncio 事件循环 |
| `one-collector` | 全量数据采集落湖 | Bronze/Silver/Gold 三层 |
| `one-marketgw` | 行情网关、低延迟分发 | 归一化 + 分发 |
| `one-risk` | 风控守护 | L3 后台轮询 |
| `one-ai` | AI 智能体调度 | LLM + ML 双引擎 |
| `one-watchdog` | 看门狗、心跳与自愈 | 全进程守护 |

### 设计铁律

1. **风控阈值硬编码** — 最大回撤/杠杆/单仓上限是代码常量
2. **不可变审计** — 风控决策只增不改
3. **故障即停** — 风控异常触发熔断，禁止 `except: pass`
4. **AI 无否决权** — AI 只产建议，永远绕不过风控
5. **先影子后实盘** — 新逻辑先影子→灰度→主用
6. **中文优先** — 所有面向人的输出默认中文

---

## 模块清单

### 数据层

| 模块 | 路径 | 说明 |
|------|------|------|
| 行情网关 | `marketgw/` | 币安/OKX WebSocket 接入、归一化、断线重连 |
| 数据采集 | `data/` | Bronze→Silver→Gold 三层数据湖、质检、血缘 |
| 特征商店 | `data/feature_store.py` | 离线 Parquet + 在线 Redis |

### 策略层

| 模块 | 路径 | 说明 |
|------|------|------|
| 策略引擎 | `strategy/` | 策略注册表、回测引擎、多策略并行 |
| 基础策略 | `strategy/ema_cross.py` 等 | EMA 交叉 / RSI 反转 / 网格 |
| 高级策略 | `strategy/smc.py` 等 | 订单流 / 聪明钱 / 量价结构 |
| 期权策略 | `strategy/options.py` | 卖方、价差、Delta 中性 |

### 执行层

| 模块 | 路径 | 说明 |
|------|------|------|
| OMS | `execution/oms.py` | 订单状态机、幂等下单 |
| EMS | `execution/ems.py` | 算法拆单（TWAP/VWAP/POV） |
| 交易所适配器 | `exchange/` | 币安/OKX/Deribit/IBKR |
| 风控引擎 | `risk/` | 四层风控（静态/实时/回撤/熔断） |

### AI 层

| 模块 | 路径 | 说明 |
|------|------|------|
| LLM 智能体 | `agents/` | 简报官/哨兵/情绪/宏观/辩论组 |
| ML 选股选币 | `ml/` | 因子库、训练管线、模型注册表 |
| 信号评分 | `ai/signal_scoring.py` | 共振融合 + 评分校准 |
| 自进化 | `ai/evolution.py` | 冠军挑战者 + 自动再训练 |

### 基础设施

| 模块 | 路径 | 说明 |
|------|------|------|
| EventBus | `infra/event_bus.py` | Redis Pub/Sub + Streams |
| 配置管理 | `infra/config.py` | pydantic-settings |
| 监控 | `infra/metrics.py` | Prometheus 指标埋点 |
| 看门狗 | `infra/watchdog.py` | 全进程心跳 + 自愈 |

---

## 开发规范

### 代码风格

- **Python**: Ruff 格式化 + 检查，行宽 100 字符
- **TypeScript**: ESLint + Prettier
- **类型检查**: mypy strict 模式（Python）/ tsc --noEmit（TypeScript）

### 命名规范

- Python 包/模块: `snake_case`
- Python 类: `PascalCase`
- Python 常量: `UPPER_SNAKE_CASE`
- TypeScript 组件: `PascalCase`
- TypeScript hooks: `use` 前缀

### Git 提交规范

```
<类型>(<范围>): <描述>

类型: feat / fix / refactor / test / docs / chore / perf
范围: 模块名（如 risk / strategy / api）
描述: 中文，简洁明了
```

示例：
```
feat(risk): 新增 L4 熔断器半开态探测
fix(exchange): 修复币安 WebSocket 断线后未重连的问题
docs(readle): 补充项目架构说明
```

### 文件组织

- 单文件 200–400 行为宜，上限 800 行
- 遵循高内聚原则，一个模块一个职责
- 接口契约定义在 `contracts.py` 或 `protocols.py`

### 分支策略

- `main` — 生产分支，保护分支
- `develop` — 开发分支
- `feat/*` — 功能分支
- `fix/*` — 修复分支

---

## 测试

### 运行测试

```bash
cd server

# 全量测试
pytest src/one_quant/tests/ --cov=one_quant

# 指定模块测试
pytest src/one_quant/tests/test_risk_engine.py -v

# 生成覆盖率报告
pytest src/one_quant/tests/ --cov=one_quant --cov-report=html
```

### 测试要求

- 核心模块覆盖率 ≥ 80%
- 风控引擎覆盖率 ≥ 95%
- 每个策略需包含：锚定测试、无未来函数测试、空数据测试、成本测试
- 异步测试使用 `pytest-asyncio`（`asyncio_mode = "auto"`）

### 测试文件命名

```
tests/
├── test_api.py              # API 路由测试
├── test_risk_engine.py      # 风控引擎测试
├── test_strategies.py       # 策略测试
├── test_oms.py              # OMS 测试
├── test_ems.py              # EMS 测试
├── test_exchange.py         # 交易所适配器测试
└── ...
```

---

## 部署

### Docker Compose（推荐）

```bash
cd deploy/docker
docker compose up -d
```

### 单独构建应用镜像

```bash
cd deploy/docker
docker build -t one-quant:latest -f Dockerfile ../../server
```

### 环境变量

参考 `server/.env.example` 和 `deploy/docker/.env.docker` 配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | — |
| `TIMESCALE_URL` | TimescaleDB 连接串 | — |
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `CLICKHOUSE_URL` | ClickHouse 地址 | `http://localhost:8123` |
| `API_HOST` | API 监听地址 | `0.0.0.0` |
| `API_PORT` | API 监听端口 | `8000` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

---

## 文档链接

| 文档 | 说明 |
|------|------|
| [完整开发文档](docs/ONE量化_开发文档_v2.0_完整版.md) | 系统架构、模块设计、接口规范等完整技术文档 |
| [开发工单 Backlog](docs/ONE量化_开发工单_Backlog.md) | 阶段一~六开发任务拆解与进度跟踪 |
| [贡献指南](CONTRIBUTING.md) | 开发流程、代码规范、测试要求 |
| [变更日志](CHANGELOG.md) | 版本变更记录 |

---

## 许可证

MIT License
