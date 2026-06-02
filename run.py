# uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

import uvicorn
import warnings
from requests.exceptions import RequestsDependencyWarning
from dotenv import load_dotenv
import os

load_dotenv()

warnings.filterwarnings("ignore", category=RequestsDependencyWarning)

if __name__ == "__main__":
    print("Starting PM2 Dashboard...")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=os.getenv("PORT", 8000),
        log_level="warning",
        access_log=True,
        timeout_keep_alive=86400,
    )
