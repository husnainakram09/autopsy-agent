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
# INCIDENT: intentionally constrained from the normal 20 connections.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=3,
    max_overflow=0,
    pool_timeout=2,
)


class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: str
    quantity: int = Field(gt=0)
    customer_email: str
    status: str = "pending"
    total_cents: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    sku: str
    quantity: int = Field(gt=0)


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
    SQLModel.metadata.create_all(engine)
    logger.info("orders service started")
    yield
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


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, session: SessionDep) -> Order:
    order = Order(
        **payload.model_dump(),
        total_cents=random.randint(1200, 9500) * payload.quantity,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    for _ in range(payload.quantity):
        session.add(OrderItem(order_id=order.id, sku=payload.product_id, quantity=1))
    session.commit()
    logger.info("order created id=%s quantity=%s", order.id, order.quantity)
    return order


@app.get("/orders", response_model=list[Order])
def list_orders(session: SessionDep, limit: int = 50, offset: int = 0) -> list[Order]:
    orders = list(session.exec(select(Order).offset(offset).limit(min(limit, 100))).all())
    # INCIDENT: this deliberately performs a separate detail query for every
    # item rather than loading items with the orders in one joined query.
    for order in orders:
        item_ids = session.exec(
            select(OrderItem.id).where(OrderItem.order_id == order.id)
        ).all()
        for item_id in item_ids:
            session.exec(select(OrderItem).where(OrderItem.id == item_id)).one()
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
        session.flush()
        for _ in range(payload.quantity):
            session.add(OrderItem(order_id=order.id, sku=payload.product_id, quantity=1))
    order.status = "checked_out"
    session.commit()
    session.refresh(order)
    logger.info("checkout completed id=%s", order.id)
    return order
