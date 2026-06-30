# ONE量化

ONE量化是一个全栈量化交易平台，提供数据采集、策略回测、实盘交易和监控一体化解决方案。

## 🚀 快速启动

### 前置要求

- Docker & Docker Compose
- Python 3.12+
- Git

### 本地开发

```bash
# 克隆项目
git clone <repo-url>
cd one-quant

# 复制环境变量
cp server/.env.example server/.env

# 启动所有服务
cd deploy/docker
docker compose up -d

# 查看服务状态
docker compose ps
```

服务启动后：

| 服务 | 地址 | 说明 |
|------|------|------|
| API 服务 | http://localhost:8000 | FastAPI 主服务 |
| PostgreSQL | localhost:5432 | 主数据库 |
| TimescaleDB | localhost:5433 | 时序数据库 |
| Redis | localhost:6379 | 缓存 |
| ClickHouse | localhost:8123 | 分析数据库 |
| MinIO | http://localhost:9001 | 对象存储 |
| Prometheus | http://localhost:9090 | 监控指标 |
| Grafana | http://localhost:3000 | 监控面板 |

### 仅启动基础设施

```bash
docker compose up -d postgres timescaledb redis clickhouse minio
```

## 📁 目录结构

```
one-quant/
├── server/                    # 后端服务
│   ├── src/                   # 源代码
│   │   └── one_quant/
│   │       ├── api/           # API 服务
│   │       ├── runner/        # 策略执行引擎
│   │       ├── data/          # 数据采集与处理
│   │       ├── models/        # 数据模型
│   │       ├── strategies/    # 策略实现
│   │       └── tests/         # 测试
│   ├── pyproject.toml         # 项目配置
│   └── .env.example           # 环境变量模板
├── deploy/
│   └── docker/                # Docker 部署配置
│       ├── docker-compose.yml # 开发环境编排
│       ├── Dockerfile         # 应用镜像
│       └── prometheus.yml     # 监控配置
├── .github/
│   └── workflows/
│       └── ci.yml             # CI 流水线
├── .gitignore
└── README.md
```

## 🛠️ 开发

```bash
cd server

# 安装依赖
pip install -e ".[dev]"

# 代码检查
ruff check src/
ruff format --check src/

# 类型检查
mypy src/one_quant/

# 运行测试
pytest src/one_quant/tests/ --cov=one_quant
```

## 📄 License

MIT
