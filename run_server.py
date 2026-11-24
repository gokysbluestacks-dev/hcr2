"""
Hill Climb Racing 2 - Private Server Launcher
Usage:
    python run_server.py [--host 0.0.0.0] [--port 22994]
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from server import HCR2PrivateServer



def main():
    parser = argparse.ArgumentParser(description="HCR2 private game server")
    parser.add_argument("--host", default=os.environ.get("HCR2_HOST", "0.0.0.0"),
                        help="Interface to bind (default: HCR2_HOST or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None,
                        help="Single TCP port (default: HCR2_PORT, then PORT, then 22994)")
    parser.add_argument("--log-file", default=os.environ.get("HCR2_LOG_FILE", "server.log"),
                        help="Log file (default: server.log; set HCR2_LOG_FILE empty to disable)")
    parser.add_argument("--log-level", default=os.environ.get("HCR2_LOG_LEVEL", "INFO"),
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
                        help="Log verbosity")
    args = parser.parse_args()

    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        log_path = Path(args.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        ))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )

    port = args.port if args.port is not None else int(
        os.environ.get("HCR2_PORT", os.environ.get("PORT", "22994"))
    )
    server = HCR2PrivateServer(args.host, port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logging.getLogger("hcr2").info("Server stopped")

if __name__ == "__main__":
    main()
