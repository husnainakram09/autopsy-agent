import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timezone

import httpx


logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(message)s")
BASE_URL = os.getenv("ORDERS_URL", "http://localhost:8001")
DELAY = float(os.getenv("REQUEST_DELAY_SECONDS", "0.35"))
PRODUCTS = ["demo-widget", "pro-widget", "support-plan", "starter-kit"]


async def send(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> None:
    try:
        response = await client.request(method, path, **kwargs)
        logging.info("%s %s -> %s", method, path, response.status_code)
    except httpx.HTTPError as exc:
        logging.warning("request failed: %s", exc)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=5) as client:
        while True:
            action = random.choices(["list", "create", "checkout", "not_found"], weights=[35, 35, 25, 5])[0]
            if action == "list":
                await send(client, "GET", "/orders")
            elif action == "create":
                await send(
                    client,
                    "POST",
                    "/orders",
                    json={
                        "product_id": random.choice(PRODUCTS),
                        "quantity": random.randint(1, 3),
                        "customer_email": f"customer-{random.randint(1, 100)}@example.com",
                    },
                )
            elif action == "checkout":
                await send(
                    client,
                    "POST",
                    "/checkout",
                    json={"product_id": random.choice(PRODUCTS), "quantity": 1},
                )
            else:
                await send(client, "GET", f"/orders/{random.randint(90000, 99999)}")
            await asyncio.sleep(DELAY)


if __name__ == "__main__":
    asyncio.run(main())

