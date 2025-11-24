from __future__ import annotations

import logging
import sys

LOGGER_NAME = "aubus.gui"

logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)
