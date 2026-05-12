"""Command line entrypoint for the local sd2video HTTP service."""

from __future__ import annotations

import argparse
import sys

from .config import ServerConfig


def main(argv: list[str] | None = None) -> int:
    config = ServerConfig.from_env()
    default_host, default_port = config.bind_host_port()
    parser = argparse.ArgumentParser(description="Run the sd2video local backend service.")
    parser.add_argument("--host", default=default_host)
    parser.add_argument("--port", default=default_port, type=int)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is required to run the service. Install with: pip install uvicorn",
            file=sys.stderr,
        )
        return 2

    uvicorn.run(
        "sd2video.server.app:create_app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        factory=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
