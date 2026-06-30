"""ONE量化 API 主入口 — 可直接 uvicorn 运行"""

import uvicorn

from one_quant.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "one_quant.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
