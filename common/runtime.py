"""Shared transport and operational behavior, without shared business databases."""
import asyncio
import contextvars
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from common.db import Store
from common.security import current_user, internal, secret

SERVICES = ['auth', 'products', 'inventory', 'cart', 'orders', 'payments', 'notifications', 'reviews', 'coupons', 'returns', 'analytics']
PORTS = {n: 8001+i for i, n in enumerate(SERVICES)}
correlation = contextvars.ContextVar('correlation', default='background')
log = logging.getLogger('inventory')
logging.basicConfig(level=logging.INFO, format='%(message)s')
TEST_TRANSPORT = None


def base_url(name):
    return os.getenv(f'{name.upper()}_URL', f'http://127.0.0.1:{PORTS[name]}')


async def call(name, method, path, body=None, user=None):
    headers = {'X-Service-Key': os.getenv('SERVICE_SECRET', ''), 'X-Correlation-ID': correlation.get()}
    if user:
        headers['Authorization'] = user if isinstance(user, str) else 'Bearer ' + user
    async with httpx.AsyncClient(trust_env=False,transport=TEST_TRANSPORT, timeout=float(os.getenv('SERVICE_TIMEOUT_SECONDS', '12'))) as client:
        try:
            r = await client.request(method, base_url(name)+path, json=body, headers=headers)
        except httpx.RequestError:
            raise HTTPException(503, f'{name} service unavailable; retry using the same request key')
    if r.status_code >= 400:
        try:
            detail = r.json().get('detail', r.json().get('error', {}).get('message', r.text))
        except ValueError:
            detail = 'Downstream request failed'
        raise HTTPException(r.status_code if r.status_code < 500 else 503, detail)
    return r.json() if r.content else None


async def staff(user=Depends(current_user)):
    record = await call('auth', 'GET', f"/internal/users/{user['sub']}")
    if record['role'] not in ['Administrator', 'Inventory Manager']:
        raise HTTPException(403, 'Staff permission required')
    return dict(user, role=record['role'])


async def admin(user=Depends(staff)):
    if user['role'] != 'Administrator':
        raise HTTPException(403, 'Administrator permission required')
    return user


def own(record, user):
    if not record:
        raise HTTPException(404, 'Record not found')
    if record['user_id'] != user['sub']:
        raise HTTPException(403, 'This record belongs to another customer')
    return record


class Limiter:
    def __init__(self):
        self.local = {}
        self.redis = None

    async def client(self):
        if self.redis is None:
            import redis.asyncio as redis
            self.redis = redis.from_url(os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0'), socket_connect_timeout=1, socket_timeout=1)
        return self.redis

    async def check(self, key, limit=120, seconds=60):
        window = int(time.time()) // seconds
        try:
            r = await self.client()
            # INCR and EXPIRE in a single Lua operation, including concurrent first hits.
            count = await r.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", 1, f'rate:{key}:{window}', seconds)
        except Exception:
            if os.getenv('REQUIRE_INFRA', 'false').lower() == 'true':
                raise HTTPException(503, 'Rate limiting temporarily unavailable')
            k = (key, window)
            self.local = {x:y for x,y in self.local.items() if x[1] >= window-1}
            self.local[k] = self.local.get(k, 0)+1
            count = self.local[k]
        if count > limit:
            raise HTTPException(429, 'Too many requests; wait one minute')


limiter = Limiter()


def make_app(name, handler=None, maintenance=None):
    store = Store(name)

    @asynccontextmanager
    async def lifespan(app):
        secret()
        tasks = []
        if os.getenv('WORKERS_ENABLED', 'true').lower() == 'true':
            from common.events import run_bus
            tasks.append(asyncio.create_task(run_bus(store, handler)))
            if maintenance:
                async def maintain():
                    while True:
                        try:
                            await maintenance()
                        except Exception as e:
                            log.warning(json.dumps({'service':name, 'maintenance_error':type(e).__name__}))
                        await asyncio.sleep(5)
                tasks.append(asyncio.create_task(maintain()))
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title=f'Inventory · {name}', version='1.0.0', lifespan=lifespan)
    app.state.store = store

    @app.middleware('http')
    async def trace(request, next):
        cid = request.headers.get('X-Correlation-ID', '')[:128] or str(uuid.uuid4())
        handle = correlation.set(cid)
        started = time.monotonic()
        try:
            response = await next(request)
            response.headers['X-Correlation-ID'] = cid
            log.info(json.dumps({'service':name, 'method':request.method,'path':request.url.path,
                                 'status':response.status_code,'ms':round((time.monotonic()-started)*1000), 'correlation_id':cid}))
            return response
        finally:
            correlation.reset(handle)

    @app.exception_handler(StarletteHTTPException)
    async def errors(request, exc):
        return JSONResponse({'error': {'message': exc.detail, 'code': exc.status_code}, 'detail': exc.detail,
                             'correlation_id': correlation.get()}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        issues = [{'field':'.'.join(map(str,e['loc'])), 'message':e['msg']} for e in exc.errors()]
        return JSONResponse({'error': {'message':'Invalid input', 'issues':issues}, 'detail':issues,
                             'correlation_id':correlation.get()}, status_code=422)

    @app.get('/health', tags=['operations'])
    def health():
        with store.connect() as c:
            c.execute('SELECT 1')
        return {'status':'ok', 'service':name}

    @app.get('/internal/audit', dependencies=[Depends(internal)])
    def audit():
        return store.all('audit_logs')

    return app, store
