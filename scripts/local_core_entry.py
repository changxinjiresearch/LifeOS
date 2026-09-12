from __future__ import annotations

import os

import uvicorn

from mcp_server.local_core_v4 import app


def main() -> None:
    port = int(os.getenv("NEXTPLAN_LOCAL_PORT", "47123"))
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False, access_log=False)


if __name__ == "__main__":
    main()
