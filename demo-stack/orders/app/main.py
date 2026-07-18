import json
import logging
import logging.config
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
import httpx
from prometheus_fastapi_instrumentator import Instrumentator
from sqlmodel import Field, Session, SQLModel, create_engine, select


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonFormatter}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
            }
        },
        "root": {"handlers": ["stdout"], "level": os.getenv("LOG_LEVEL", "INFO")},
    }
)
logger = logging.getLogger("orders")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://orders:orders@localhost:5432/orders"
)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=0,
    pool_timeout=2,
)
DOWNSTREAM_URL = os.getenv("DOWNSTREAM_URL", "http://inventory:8000")
downstream_client: httpx.Client | None = None


class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: str
    quantity: int = Field(gt=0)
    customer_email: str
    status: str = "pending"
    total_cents: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderCreate(SQLModel):
    product_id: str
    quantity: int = Field(gt=0, le=20)
    customer_email: str


class CheckoutRequest(SQLModel):
    order_id: int | None = None
    product_id: str = "demo-widget"
    quantity: int = Field(default=1, gt=0, le=20)
    customer_email: str = "customer@example.com"


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    global downstream_client
    SQLModel.metadata.create_all(engine)
    # INCIDENT: this is intentionally shorter than normal dependency variance.
    downstream_client = httpx.Client(base_url=DOWNSTREAM_URL, timeout=0.1)
    logger.info("orders service started")
    yield
    if downstream_client is not None:
        downstream_client.close()
    logger.info("orders service stopped")


app = FastAPI(title="Orders API", version="1.0.0", lifespan=lifespan)
Instrumentator().instrument(app).expose(app, include_in_schema=False)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "request completed method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def check_inventory(product_id: str) -> None:
    if downstream_client is None:
        return
    try:
        response = downstream_client.get(f"/inventory/{product_id}")
        response.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("inventory dependency failed product_id=%s error=%s", product_id, exc)
        raise HTTPException(status_code=502, detail="Inventory dependency unavailable") from exc


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, session: SessionDep) -> Order:
    order = Order(
        **payload.model_dump(),
        total_cents=random.randint(1200, 9500) * payload.quantity,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    logger.info("order created id=%s quantity=%s", order.id, order.quantity)
    return order


@app.get("/orders", response_model=list[Order])
def list_orders(session: SessionDep, limit: int = 50, offset: int = 0) -> list[Order]:
    orders = list(session.exec(select(Order).offset(offset).limit(min(limit, 100))).all())
    if orders:
        check_inventory(orders[0].product_id)
    return orders


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: int, session: SessionDep) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        logger.warning("order not found id=%s", order_id)
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@app.post("/checkout", response_model=Order)
def checkout(payload: CheckoutRequest, session: SessionDep) -> Order:
    order = session.get(Order, payload.order_id) if payload.order_id else None
    if payload.order_id and order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order is None:
        order = Order(
            product_id=payload.product_id,
            quantity=payload.quantity,
            customer_email=payload.customer_email,
            total_cents=random.randint(1200, 9500) * payload.quantity,
        )
        session.add(order)
    order.status = "checked_out"
    session.commit()
    session.refresh(order)
    logger.info("checkout completed id=%s", order.id)
    return order
