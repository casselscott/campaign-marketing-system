import logging
import os
from logging.handlers import RotatingFileHandler

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        RotatingFileHandler(
            "logs/mailer.log", maxBytes=5 * 1024 * 1024, backupCount=5
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("mcs")
