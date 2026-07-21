import os
import random
import time

from fastapi import FastAPI


app = FastAPI(title="Inventory Dependency")
MIN_DELAY = int(os.getenv("LATENCY_MIN_MS", "50"))
MAX_DELAY = int(os.getenv("LATENCY_MAX_MS", "180"))


@app.get("/inventory/{product_id}")
def inventory(product_id: str) -> dict[str, object]:
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY) / 1000)
    return {"product_id": product_id, "available": True}

