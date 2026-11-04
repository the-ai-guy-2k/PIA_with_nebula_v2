"""Start the existing FastAPI app locally or in a managed Replit service."""

import os
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )