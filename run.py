# uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

import uvicorn
import warnings
import logging
from requests.exceptions import RequestsDependencyWarning
from dotenv import load_dotenv
import os
from app.logging_config import configure_logging, show_startup_banner

load_dotenv()

warnings.filterwarnings("ignore", category=RequestsDependencyWarning)

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    environment = os.getenv("APP_ENV", "production")
    configure_logging(log_level)

    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        port = 8000
        logging.getLogger(__name__).warning(
            "PORT 값이 올바르지 않아 기본 포트 %s를 사용합니다.", port
        )

    show_startup_banner(
        host=host,
        port=port,
        log_level=log_level,
        environment=environment,
    )
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level=log_level,
        log_config=None,
        access_log=True,
        timeout_keep_alive=86400,
    )
