# 贡献指南

感谢你对 ONE量化 项目的关注！本文档将帮助你快速上手开发流程。

---

## 目录

- [开发流程](#开发流程)
- [分支管理](#分支管理)
- [代码规范](#代码规范)
- [测试要求](#测试要求)
- [提交规范](#提交规范)
- [代码审查](#代码审查)
- [文档要求](#文档要求)

---

## 开发流程

### 1. 环境准备

```bash
# 克隆仓库
git clone <repo-url>
cd one-quant

# 配置环境变量
cp server/.env.example server/.env

# 启动基础设施
cd deploy/docker
docker compose up -d postgres timescaledb redis clickhouse minio

# 安装后端依赖
cd ../../server
pip install uv
uv pip install -e ".[dev]"

# 安装前端依赖
cd ../web
npm install
```

### 2. 日常开发循环

```
1. 从 develop 创建功能分支 → git checkout -b feat/xxx develop
2. 编写代码 + 测试
3. 本地检查通过 → ruff / mypy / pytest
4. 提交代码 → 遵循提交规范
5. 推送并创建 PR → 目标分支 develop
6. 代码审查通过 → 合并
```

### 3. 本地检查清单

提交前请确保以下检查全部通过：

```bash
cd server

# 代码风格检查
ruff check src/
ruff format --check src/

# 类型检查
mypy src/one_quant/

# 全量测试
pytest src/one_quant/tests/ --cov=one_quant --cov-fail-under=80
```

```bash
cd web

# 前端检查
npm run lint
npm run type-check
```

---

## 分支管理

### 分支模型

| 分支 | 用途 | 保护策略 |
|------|------|----------|
| `main` | 生产分支 | 强制 PR + 审查 + CI 通过 |
| `develop` | 开发集成分支 | 强制 PR + CI 通过 |
| `feat/*` | 功能分支 | 无 |
| `fix/*` | 修复分支 | 无 |
| `hotfix/*` | 紧急修复 | 从 main 拉出，合回 main + develop |

### 分支命名

```
feat/模块名-简短描述      例: feat/risk-circuit-breaker
fix/模块名-简短描述       例: fix/exchange-reconnect
hotfix/简短描述           例: hotfix/order-idempotent
docs/简短描述             例: docs/api-spec
refactor/模块名-简短描述   例: refactor/eventbus-interface
```

---

## 代码规范

### Python 规范

#### 代码风格

- 使用 **Ruff** 进行格式化与检查
- 行宽上限：**100 字符**
- 目标版本：**Python 3.12**
- 启用规则：`E`（错误）、`F`（Pyflakes）、`I`（导入排序）、`N`（命名）、`W`（警告）、`UP`（升级建议）

#### 类型标注

- **mypy strict 模式** — 所有函数必须有完整类型标注
- 禁止 `Any` 类型滥用，确需使用时添加注释说明原因
- 使用 `TypedDict` 或 `Pydantic BaseModel` 替代原始 `dict`

#### 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 包/模块 | `snake_case` | `risk_engine.py` |
| 类 | `PascalCase` | `CircuitBreaker` |
| 函数/方法 | `snake_case` | `check_order()` |
| 常量 | `UPPER_SNAKE_CASE` | `MAX_LEVERAGE = 10` |
| 私有成员 | `_前缀` | `_internal_state` |
| 类型变量 | `PascalCase` | `T_co` |

#### 文件组织

- 单文件 200–400 行为宜，上限 800 行
- 每个模块一个职责，遵循高内聚原则
- 接口契约定义在 `contracts.py` 或 `protocols.py`
- 注册表使用 `@register_*` 装饰器

#### 异常处理

- **禁止** `except: pass` 或裸 `except`
- 风控代码异常必须触发 ERROR 日志 + 熔断
- 使用具体异常类型，记录上下文信息

#### 日志

- 使用结构化日志（JSON 格式 + 中文摘要）
- 敏感信息通过 `log_mask` 脱敏
- 日志级别：`DEBUG`（调试）→ `INFO`（业务）→ `WARNING`（异常）→ `ERROR`（故障）→ `CRITICAL`（熔断）

### TypeScript / React 规范

#### 代码风格

- **ESLint** + **Prettier** 格式化
- 使用 TypeScript strict 模式
- 组件使用函数式组件 + Hooks

#### 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 组件 | `PascalCase` | `SignalCard.tsx` |
| Hooks | `use` 前缀 | `useWebSocket.ts` |
| 工具函数 | `camelCase` | `formatPrice()` |
| 常量 | `UPPER_SNAKE_CASE` | `API_BASE_URL` |
| 类型/接口 | `PascalCase` + `I`/`T` 前缀可选 | `ISignalData` |

#### 组件规范

- 单一职责，一个文件一个组件
- Props 使用 `interface` 定义
- 使用 Zustand 进行状态管理
- API 请求统一通过 `services/` 层封装

---

## 测试要求

### 测试覆盖率

| 模块 | 最低覆盖率 |
|------|-----------|
| 风控引擎 (`risk/`) | ≥ 95% |
| 执行引擎 (`execution/`) | ≥ 85% |
| 策略模块 (`strategy/`) | ≥ 80% |
| API 路由 (`api/`) | ≥ 80% |
| 其他模块 | ≥ 70% |

### 测试类型

#### 单元测试

每个策略必须包含以下四类测试：

| 测试类型 | 说明 | 示例 |
|----------|------|------|
| 锚定测试 | 固定输入验证确定性输出 | 给定行情序列，验证信号不随运行变化 |
| 无未来函数测试 | 确认不使用未来数据 | 逐 tick 注入，验证只用已见数据 |
| 空数据测试 | 边界条件处理 | 空行情 / 缺字段 / 零值 |
| 成本测试 | 手续费/滑点正确计入 | 验证盈亏计算包含交易成本 |

#### 集成测试

- EventBus 发布/订阅端到端测试
- 风控引擎四层链式测试
- OMS 订单生命周期测试

#### 混沌工程测试

- 订单洪流场景
- 价格跳空场景
- 交易所断连场景
- 风控异常触发熔断场景

### 运行测试

```bash
# 全量测试
pytest src/one_quant/tests/ -v

# 指定文件
pytest src/one_quant/tests/test_risk_engine.py -v

# 指定用例
pytest src/one_quant/tests/test_risk_engine.py::TestCircuitBreaker::test_open_state -v

# 覆盖率报告
pytest src/one_quant/tests/ --cov=one_quant --cov-report=html

# 并行测试（需安装 pytest-xdist）
pytest src/one_quant/tests/ -n auto
```

### 测试文件命名

- 测试文件：`test_<模块名>.py`
- 测试类：`Test<功能名>`
- 测试方法：`test_<场景描述>`
- 使用中文注释描述测试场景

---

## 提交规范

### 提交格式

```
<类型>(<范围>): <描述>

[可选正文]

[可选脚注]
```

### 类型说明

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(risk): 新增 L4 熔断器半开态探测` |
| `fix` | 修复 | `fix(exchange): 修复币安 WS 断线未重连` |
| `refactor` | 重构 | `refactor(eventbus): 抽象化消息信封接口` |
| `test` | 测试 | `test(strategy): 补充 EMA 交叉策略边界用例` |
| `docs` | 文档 | `docs(readme): 补充架构概览` |
| `perf` | 性能 | `perf(marketgw): 行情解析零拷贝优化` |
| `chore` | 杂项 | `chore(deps): 升级 FastAPI 至 0.115` |

### 提交粒度

- 一个提交 = 一个逻辑变更
- 避免「大杂烩」提交（混合多个不相关改动）
- 确保每个提交可独立编译、测试通过

---

## 代码审查

### 审查要点

1. **正确性** — 逻辑是否正确，边界条件是否处理
2. **安全性** — 风控是否绕过、密钥是否泄露、注入风险
3. **性能** — 热路径延迟是否达标、是否有不必要的开销
4. **可读性** — 命名是否清晰、注释是否充分、结构是否合理
5. **测试** — 覆盖率是否达标、关键场景是否覆盖
6. **规范** — 是否遵循代码规范和项目约定

### 审查流程

1. 作者提交 PR，填写变更说明
2. CI 自动运行（lint → 类型检查 → 测试）
3. 至少一位审查者 Approve
4. 合并到目标分支

### PR 描述模板

```markdown
## 变更内容
- 简述本次变更

## 变更类型
- [ ] 新功能
- [ ] 修复
- [ ] 重构
- [ ] 文档
- [ ] 测试

## 测试情况
- [ ] 新增/更新单元测试
- [ ] 本地全量测试通过
- [ ] 覆盖率满足要求

## 关联工单
- ONE-X.X.X

## 截图（如适用）
```

---

## 文档要求

### 代码文档

- 所有公开类/函数必须有 docstring（中文）
- 复杂算法需添加实现说明
- 接口契约需明确参数/返回值/异常说明

### 变更文档

- 新增/修改模块需更新 `README.md` 模块清单
- 重大变需更新 `CHANGELOG.md`
- 架构调整需更新开发文档

### 示例

```python
class CircuitBreaker:
    """L4 熔断器 — 三态（关闭/打开/半开）保护机制。
    
    当连续失败次数超过阈值时，熔断器进入打开状态，
    拒绝所有请求。超时后进入半开状态，允许少量探测请求。
    探测成功则恢复关闭状态，失败则重新打开。
    
    注意：熔断器阈值为硬编码常量，不从配置读取。
    """
    
    def check(self) -> RiskDecision:
        """检查当前是否允许通过。
        
        Returns:
            RiskDecision: APPROVE（允许）或 REJECT（熔断中）
            
        Raises:
            CircuitBreakerError: 熔断器内部异常（触发 ERROR 日志）
        """
        ...
```

---

## 获取帮助

- 阅读 [完整开发文档](docs/ONE量化_开发文档_v2.0_完整版.md) 了解系统架构
- 查看 [开发工单](docs/ONE量化_开发工单_Backlog.md) 了解当前任务
- 提交 Issue 讨论设计方案
- 联系项目维护者获取支持
