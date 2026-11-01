import importlib
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['JWT_SECRET']='test-jwt-secret-with-more-than-32-characters'
os.environ['SERVICE_SECRET']='test-internal-secret-with-more-than-32-characters'
os.environ['WORKERS_ENABLED']='false'
os.environ['REQUIRE_INFRA']='false'
import tempfile
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='inventory-tests-bootstrap-')
import httpx
import pytest
import pytest_asyncio
from common.db import Store,uid
from common import runtime
from common.events import process_event
from common.security import hash_password,token


class Network(httpx.AsyncBaseTransport):
    def __init__(self,modules):
        self.modules=modules
        self.failed=set()
    async def handle_async_request(self,request):
        port=request.url.port
        name=next((n for n,p in runtime.PORTS.items() if p==port),None)
        if not name:
            name=request.url.host.split('.')[0]
        if name in self.failed:
            raise httpx.ConnectError('Injected service failure',request=request)
        module=self.modules.get(name)
        if module is None:
            raise httpx.ConnectError('Unknown service',request=request)
        return await httpx.ASGITransport(app=module.app).handle_async_request(request)


class NoRedis:
    async def get(self,*a,**kw):raise ConnectionError()
    async def incr(self,*a,**kw):raise ConnectionError()
    async def eval(self,*a,**kw):raise ConnectionError()


@pytest.fixture
def system(tmp_path,monkeypatch):
    modules={n:importlib.import_module('services.'+n) for n in runtime.SERVICES}
    for name,m in modules.items():
        m.db=Store(name,tmp_path)
        m.app.state.store=m.db
        if hasattr(m,'locks'):m.locks.clear()
    network=Network(modules)
    monkeypatch.setattr(runtime,'TEST_TRANSPORT',network)
    monkeypatch.setattr(runtime.limiter,'redis',NoRedis())
    runtime.limiter.local={}
    users={}
    with modules['auth'].db.tx() as c:
        for name,role in [('admin','Administrator'),('manager','Inventory Manager'),('alice','Customer'),('bob','Customer')]:
            u=modules['auth'].db.put(c,'users',uid(),{'email':name+'@example.com','password_hash':hash_password('StrongPass123!'),'name':name.title(),'role':role})
            users[name]=dict(u,token=token(u))
    return System(modules,network,users)


class System:
    def __init__(self,modules,network,users):self.modules=modules;self.network=network;self.users=users
    async def request(self,service,method,path,body=None,user='alice',headers=None,**kwargs):
        h={'Authorization':'Bearer '+self.users[user]['token']} if user else {}
        h.update(headers or {})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.modules[service].app),base_url='http://test') as c:
            return await c.request(method,path,json=body,headers=h,**kwargs)
    async def internal(self,service,method,path,body=None):
        return await self.request(service,method,path,body,user=None,headers={'X-Service-Key':os.environ['SERVICE_SECRET']})
    async def pump(self):
        for _ in range(12):
            events=[e for m in self.modules.values() for e in m.db.all('outbox')]
            changed=False
            for event in events:
                for m in self.modules.values():
                    changed=await process_event(m.db,event,getattr(m,'events',None)) or changed
            if not changed:return
        raise AssertionError('Event pump failed to settle')
    async def product(self,quantity=10,price=10000):
        r=await self.request('products','POST','/products',{'name':'Test Camera','description':'Reliable test camera for travel','category':'Photography','brand':'Vista','price':price},'admin')
        assert r.status_code==201,r.text
        p=r.json()
        r=await self.request('inventory','PATCH',f"/inventory/{p['id']}/stock",{'delta':quantity,'reason':'Test initial stock'},'admin')
        assert r.status_code==200,r.text
        return p
    async def order(self,p,quantity=1,user='alice',coupon=''):
        r=await self.request('cart','POST','/cart/items',{'product_id':p['id'],'quantity':quantity},user)
        assert r.status_code==201,r.text
        r=await self.request('orders','POST','/orders',{'address':'123 Test Street, Hyderabad 500001','coupon':coupon},user,headers={'Idempotency-Key':uid()})
        assert r.status_code==201,r.text
        return r.json()
    async def pay(self,o,outcome='success',user='alice'):
        r=await self.request('payments','POST','/payments',{'order_id':o['id'],'outcome':outcome},user,headers={'Idempotency-Key':uid()})
        assert r.status_code==201,r.text
        await self.pump()
        return r.json()
    async def deliver(self,o):
        for status in ['Processing','Shipped','Delivered']:
            r=await self.request('orders','PATCH',f"/orders/{o['id']}/status",{'status':status,'tracking_number':'TRACK-123'},'admin')
            assert r.status_code==200,r.text
        await self.pump()
