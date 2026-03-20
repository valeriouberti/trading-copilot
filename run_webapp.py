"""Web app entry point — starts the Trading Copilot dashboard."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
