"""AMQP transport for the planning worker."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, Protocol

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from trip_agent.worker.contracts import PlanningCreateCommand
from trip_agent.worker.processor import (
    DemoPlanningProvider,
    PlanningProvider,
    process_planning_create,
)

COMMAND_EXCHANGE = "trip.command.exchange"
EVENT_EXCHANGE = "trip.event.exchange"
DEAD_LETTER_EXCHANGE = "trip.dead-letter.exchange"
CREATE_QUEUE = "planning.create.queue"
DEAD_LETTER_QUEUE = "planning.dead-letter.queue"
CREATE_ROUTING_KEY = "planning.create"
COMPLETED_ROUTING_KEY = "planning.completed"
DEAD_LETTER_ROUTING_KEY = "planning.create.dead"

logger = logging.getLogger("trip_agent.worker")


class IncomingDelivery(Protocol):
    body: bytes

    def ack(self) -> Awaitable[None]: ...

    def reject(self, *, requeue: bool) -> Awaitable[None]: ...

    def nack(self, *, requeue: bool) -> Awaitable[None]: ...


class EventExchange(Protocol):
    def publish(
        self,
        message: aio_pika.Message,
        *,
        routing_key: str,
        mandatory: bool,
    ) -> Awaitable[Any]: ...


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", frozen=True)

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "trip_pilot"
    rabbitmq_password: str = "replace-with-local-password"
    demo_mode: bool = True


async def handle_delivery(
    message: IncomingDelivery,
    event_exchange: EventExchange,
    provider: PlanningProvider | None = None,
) -> None:
    try:
        command = PlanningCreateCommand.model_validate_json(message.body)
    except (ValidationError, TypeError, ValueError) as exception:
        error_count = exception.error_count() if isinstance(exception, ValidationError) else 1
        logger.warning("rejecting invalid planning command: %s", error_count)
        await message.reject(requeue=False)
        return

    try:
        completed = process_planning_create(command, provider or DemoPlanningProvider())
        outgoing = aio_pika.Message(
            body=completed.model_dump_json(by_alias=True).encode(),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(completed.event_id),
            correlation_id=str(completed.trace_id),
            type=completed.event_type,
            headers={
                "traceId": str(completed.trace_id),
                "taskId": str(completed.task_id),
                "tripId": str(completed.trip_id),
                "runId": str(completed.run_id),
            },
        )
        await event_exchange.publish(
            outgoing,
            routing_key=COMPLETED_ROUTING_KEY,
            mandatory=True,
        )
    except Exception:
        logger.exception("planning command failed before completion event was confirmed")
        await message.nack(requeue=True)
        return

    await message.ack()


async def run_worker(settings: WorkerSettings) -> None:
    if not settings.demo_mode:
        raise ValueError("Only DEMO_MODE=true is supported by the current worker slice")

    connection = await aio_pika.connect_robust(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        login=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
    )
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        await channel.set_qos(prefetch_count=1)
        command_exchange = await channel.declare_exchange(
            COMMAND_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        event_exchange = await channel.declare_exchange(
            EVENT_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        dead_letter_exchange = await channel.declare_exchange(
            DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        command_queue = await channel.declare_queue(
            CREATE_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": DEAD_LETTER_ROUTING_KEY,
            },
        )
        dead_letter_queue = await channel.declare_queue(DEAD_LETTER_QUEUE, durable=True)
        await command_queue.bind(command_exchange, routing_key=CREATE_ROUTING_KEY)
        await dead_letter_queue.bind(dead_letter_exchange, routing_key="planning.#")
        callback: Callable[[AbstractIncomingMessage], Awaitable[None]] = partial(
            _handle_incoming,
            event_exchange=event_exchange,
        )
        await command_queue.consume(callback)
        logger.info("planning worker consuming queue=%s", CREATE_QUEUE)
        await asyncio.Future()


async def _handle_incoming(
    message: AbstractIncomingMessage,
    *,
    event_exchange: AbstractExchange,
) -> None:
    await handle_delivery(message, event_exchange)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(WorkerSettings()))


if __name__ == "__main__":
    main()
