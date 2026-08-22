import logging
import sys
from typing import Optional

from config.settings import settings


# Log format for development (human-readable)
DEV_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"

# Log format for production (structured/JSON)
PROD_FORMAT = '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'


def setup_logging(log_level: Optional[str] = None) -> None:
    """
    Configure logging for the application.

    Args:
        log_level: Override log level (default: DEBUG for dev, INFO for prod)
    """
    # Determine log level
    if log_level:
        level = getattr(logging, log_level.upper(), logging.INFO)
    else:
        level = logging.DEBUG if settings.app_env == "development" else logging.INFO

    # Choose format based on environment
    if settings.app_env == "production":
        log_format = PROD_FORMAT
    else:
        log_format = DEV_FORMAT

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # Remove existing handlers
    )

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)

    # Message queue and worker logs
    logging.getLogger("pika").setLevel(logging.ERROR)
    logging.getLogger("amqp").setLevel(logging.ERROR)
    logging.getLogger("kombu").setLevel(logging.ERROR)
    logging.getLogger("celery").setLevel(logging.WARNING)
    logging.getLogger("celery.worker").setLevel(logging.WARNING)
    logging.getLogger("celery.task").setLevel(logging.INFO)
    logging.getLogger("pika.adapters.utils").setLevel(logging.ERROR)
    logging.getLogger("pika.adapters").setLevel(logging.ERROR)

    # Docling and ML processing
    logging.getLogger("docling").setLevel(logging.WARNING)
    logging.getLogger("docling_core").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("torch").setLevel(logging.ERROR)
    logging.getLogger("tensorflow").setLevel(logging.ERROR)

    # Vector database
    logging.getLogger("qdrant_client").setLevel(logging.WARNING)

    # Network/HTTP
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    # Log startup
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured - Level: {logging.getLevelName(level)}, Environment: {settings.app_env}"
    )
