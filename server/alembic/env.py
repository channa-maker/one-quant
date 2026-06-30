"""Alembic 迁移环境配置 — ONE量化

支持 SQLAlchemy 2.0 async 引擎，自动发现 ORM 模型。
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 将项目源码加入 Python 路径，确保能导入 ORM 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from one_quant.core.models import Base  # noqa: E402

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Alembic Config 对象
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

config = context.config

# 配置日志（从 alembic.ini 读取）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置目标元数据（autogenerate 用）
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式迁移 — 生成 SQL 脚本，不需要数据库连接。

    通过 URL 字符串生成迁移 SQL，适用于无法直连数据库的场景。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在给定连接上执行迁移。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线异步模式迁移 — 使用 asyncpg 驱动连接数据库。

    创建异步引擎 → 获取连接 → 执行迁移 → 关闭引擎。
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式迁移入口 — 启动异步事件循环。"""
    asyncio.run(run_async_migrations())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 根据模式执行迁移
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
