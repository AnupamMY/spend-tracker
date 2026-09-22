import os

import uvicorn


if __name__ == "__main__":
    port = int(os.getenv("PORT", "4000"))
    uvicorn.run("app.main:create_app", host="0.0.0.0", port=port, factory=True)
