"""
ONE量化 - 主入口

启动 API 服务器和策略运行引擎。
"""

import uvicorn

from one_quant.api.app import create_app


def main() -> None:
    """启动 ONE量化 API 服务。"""
    app = create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    main()
