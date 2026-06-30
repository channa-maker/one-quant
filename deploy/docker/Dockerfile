FROM python:3.12-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 复制依赖文件
COPY pyproject.toml ./

# 安装依赖
RUN uv pip install --system -e ".[dev]"

# 复制源码
COPY src/ ./src/

# 非 root 用户
RUN useradd -m onequant
USER onequant

CMD ["python", "-m", "one_quant.api.main"]
