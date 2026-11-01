"""Opt-in real Redis/RabbitMQ tests. Run against disposable infrastructure.
RUN_INFRA_TESTS=true python -m pytest tests/test_live_infrastructure.py
Never point these tests at a production broker: they publish test events.
"""
import asyncio
import os
import time
import aio_pika
import pytest
import redis.asyncio as redis
from common.db import Store,uid
from common.events import run_bus

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('RUN_INFRA_TESTS')!='true',reason='Opt-in real infrastructure test')]


async def test_real_redis_cache_and_atomic_rate_script():
    client=redis.from_url(os.getenv('REDIS_URL','redis://localhost:6379/0'))
    key='test:'+uid()
    try:
        await client.set(key,'catalog-value',ex=10)
        assert await client.get(key)==b'catalog-value'
        await client.delete(key)
        script="local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
        values=await asyncio.gather(*(client.eval(script,1,key,60) for _ in range(20)))
        assert sorted(values)==list(range(1,21))
        assert await client.ttl(key)>0
    finally:
        await client.delete(key);await client.aclose()


async def test_real_rabbit_retry_dedup_and_dead_letter(tmp_path,monkeypatch):
    monkeypatch.setenv('EVENT_MAX_ATTEMPTS','2')
    db=Store('notifications',tmp_path)
    db.name='test_'+uid()
    run_id=uid();seen=[];completed=asyncio.Event()
    async def handler(event):
        if event['payload'].get('run')!=run_id:return
        seen.append(event['event_id'])
        if event['type']=='test.poison':raise ValueError('Deliberate consumer failure')
        completed.set()
    task=asyncio.create_task(run_bus(db,handler))
    connection=await aio_pika.connect_robust(os.getenv('RABBITMQ_URL','amqp://inventory:inventory_local_dev@localhost/'))
    try:
        channel=await connection.channel(publisher_confirms=True)
        # Outbox publisher declares subscriptions and waits for broker confirmation.
        with db.tx() as c:
            good=db.emit(c,'test.valid',{'run':run_id})
            poison=db.emit(c,'test.poison',{'run':run_id})
        await asyncio.wait_for(completed.wait(),20)
        deadline=time.monotonic()+25
        dead=[]
        while time.monotonic()<deadline:
            try:
                queue=await channel.get_queue(db.name+'.dead')
                message=await queue.get(fail=False)
                if message:
                    import json
                    event=json.loads(message.body)
                    await message.ack()
                    dead.append(event)
                    if event['event_id']==poison['event_id']:break
            except aio_pika.exceptions.ChannelNotFoundEntity:
                pass
            await asyncio.sleep(.2)
        assert any(e['event_id']==poison['event_id'] for e in dead)
        assert seen.count(poison['event_id'])==2
        exchange=await channel.get_exchange('business')
        import json
        await exchange.publish(aio_pika.Message(json.dumps(good).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key='')
        await asyncio.sleep(.6)
        assert seen.count(good['event_id'])==1
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        try:
            await channel.queue_delete(db.name+'.events')
            await channel.queue_delete(db.name+'.dead')
        finally:
            await connection.close()
