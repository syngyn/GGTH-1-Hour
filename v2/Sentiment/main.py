"""Entry point. Run:  python main.py"""
import asyncio
import logging
import os

from config import CONFIG
from forex_sentiment import run_once
from sentiment_writer import write_atomic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("forex_sentiment")


async def loop():
    out_path = os.path.join(CONFIG.mt5_files_path, CONFIG.output_filename)
    while True:
        try:
            payload = await run_once()
            write_atomic(payload, out_path)
            n_pairs = len(payload.get("pairs", []))
            n_ccy = len(payload.get("currencies", {}))
            log.info("Wrote %d pairs / %d currencies to %s",
                     n_pairs, n_ccy, out_path)
        except Exception as e:
            log.exception("cycle failed: %s", e)
        await asyncio.sleep(CONFIG.update_interval_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(loop())
    except KeyboardInterrupt:
        pass