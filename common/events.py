"""Transactional outbox, publisher confirms, durable queues, bounded retries + DLQ.
An inbox event is marked processed only AFTER its handler succeeds. Handlers that
call other services use stable operation IDs so a crash before inbox commit is safe.
"""
import asyncio
import json
import logging
import os
import time
import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

log = logging.getLogger('inventory.events')


async def process_event(store, event, handler):
    if store.get('inbox', event['event_id']):
        return False
    if handler:
        await handler(event)
    with store.tx() as c:
        store.put(c, 'inbox', event['event_id'], {'processed_at':time.time()})
    return True


async def run_bus(store, handler):
    while True:
        try:
            connection = await aio_pika.connect_robust(os.getenv('RABBITMQ_URL', 'amqp://guest:guest@127.0.0.1/'))
            async with connection:
                channel = await connection.channel(publisher_confirms=True)
                await channel.set_qos(prefetch_count=1)
                exchange = await channel.declare_exchange('business', ExchangeType.FANOUT, durable=True)
                dead = await channel.declare_exchange('dead', ExchangeType.DIRECT, durable=True)
                from common.runtime import SERVICES
                for subscriber in SERVICES:
                    subscriber_dlq = await channel.declare_queue(f'{subscriber}.dead', durable=True)
                    await subscriber_dlq.bind(dead, routing_key=subscriber)
                    subscriber_queue = await channel.declare_queue(f'{subscriber}.events', durable=True, arguments={'x-dead-letter-exchange':'dead','x-dead-letter-routing-key':subscriber})
                    await subscriber_queue.bind(exchange)
                dlq = await channel.declare_queue(f'{store.name}.dead', durable=True)
                await dlq.bind(dead, routing_key=store.name)
                queue = await channel.declare_queue(f'{store.name}.events', durable=True,
                    arguments={'x-dead-letter-exchange':'dead','x-dead-letter-routing-key':store.name})
                await queue.bind(exchange)

                async def consume(message):
                    try:
                        event = json.loads(message.body)
                        await process_event(store, event, handler)
                        await message.ack()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        attempt = int((message.headers or {}).get('attempt', 0))+1
                        log.warning(json.dumps({'service':store.name,'event_error':type(exc).__name__,'attempt':attempt}))
                        if attempt >= int(os.getenv('EVENT_MAX_ATTEMPTS','5')):
                            await message.reject(requeue=False)
                        else:
                            await asyncio.sleep(min(2**attempt, 30))
                            # Confirm republish before acknowledging original delivery.
                            await channel.default_exchange.publish(Message(message.body, delivery_mode=DeliveryMode.PERSISTENT,
                                headers={'attempt':attempt}), routing_key=queue.name, mandatory=True)
                            await message.ack()

                await queue.consume(consume)
                while not connection.is_closed:
                    for event in store.all('outbox'):
                        if event.get('published'):
                            continue
                        await exchange.publish(Message(json.dumps(event).encode(), delivery_mode=DeliveryMode.PERSISTENT,
                            message_id=event['event_id'], content_type='application/json'), routing_key='')
                        with store.tx() as c:
                            current = store.get('outbox', event['event_id'], c)
                            store.put(c,'outbox',event['event_id'],dict(current,published=True))
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(json.dumps({'service':store.name,'broker_error':type(exc).__name__,'retry_seconds':5}))
            await asyncio.sleep(5)
