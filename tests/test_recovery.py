import os
import time
import httpx
import pytest
from common.db import uid

pytestmark=pytest.mark.asyncio


async def test_duplicate_refund_and_rejected_return_rounding(system):
    s=system;p=await s.product(10,10001);o=await s.order(p,3);payment=await s.pay(o);await s.deliver(o)
    async def request_return():
        r=await s.request('returns','POST','/returns',{'order_id':o['id'],'reason':'Damaged item received','items':[{'product_id':p['id'],'quantity':1}]},headers={'Idempotency-Key':uid()});assert r.status_code==201,r.text
        return r.json()
    r1=await request_return();r2=await request_return()
    r=await s.request('returns','PATCH','/returns/'+r1['id']+'/status',{'status':'Rejected','note':'Item was not damaged'},'admin');assert r.status_code==200
    r3=await request_return();r4=await request_return()
    for ret in [r2,r3,r4]:
        for status in ['Approved','Accepted']:
            r=await s.request('returns','PATCH','/returns/'+ret['id']+'/status',{'status':status,'note':'Physically inspected item'},'admin');assert r.status_code==200,r.text
        r=await s.request('returns','PATCH','/returns/'+ret['id']+'/status',{'status':'Accepted','note':'Physically inspected item'},'admin');assert r.status_code==200
    assert (await s.request('payments','GET','/payments/'+payment['id'])).json()['refunded']==o['total']
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==10


async def test_cart_clear_replay_preserves_later_additions(system):
    s=system;p=await s.product();o=await s.order(p);await s.pay(o)
    await s.request('cart','POST','/cart/items',{'product_id':p['id'],'quantity':1})
    await s.internal('cart','POST','/internal/cart/'+s.users['alice']['id']+'/clear',{'operation_id':o['id'],'items':[{'product_id':p['id'],'quantity':1}]})
    assert (await s.request('cart','GET','/cart')).json()['items'][0]['quantity']==1


async def test_late_payment_after_expiry_is_refunded(system):
    s=system;p=await s.product(2);o=await s.order(p)
    r=await s.request('payments','POST','/payments',{'order_id':o['id'],'outcome':'success'},headers={'Idempotency-Key':uid()});payment=r.json()
    db=s.modules['inventory'].db
    with db.tx() as c:
        reservation=db.get('reservations',o['reservation_id'],c);db.put(c,'reservations',reservation['id'],dict(reservation,expires_at=time.time()-1))
    await s.pump()
    assert (await s.request('orders','GET','/orders/'+o['id'])).json()['status']=='Cancelled'
    assert (await s.request('payments','GET','/payments/'+payment['id'])).json()['refunded']==o['total']
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==2


async def test_confirmed_stock_commit_replay_is_idempotent(system):
    s=system;p=await s.product(3);o=await s.order(p);await s.pay(o)
    for _ in range(3):
        r=await s.internal('inventory','POST','/internal/reservations/'+o['reservation_id']+'/commit');assert r.status_code==200
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==2


async def test_return_recovery_after_inventory_restore_before_refund(system):
    s=system;p=await s.product(3);o=await s.order(p);await s.pay(o);await s.deliver(o)
    r=await s.request('returns','POST','/returns',{'order_id':o['id'],'reason':'Wrong product size','items':[{'product_id':p['id'],'quantity':1}]},headers={'Idempotency-Key':uid()});ret=r.json()
    await s.request('returns','PATCH','/returns/'+ret['id']+'/status',{'status':'Approved','note':'Return label issued'},'admin')
    s.network.failed.add('payments')
    r=await s.request('returns','PATCH','/returns/'+ret['id']+'/status',{'status':'Accepted','note':'Physically accepted item'},'admin');assert r.status_code==503
    assert s.modules['returns'].db.get('returns',ret['id'])['status']=='Accepted'
    s.network.failed.clear();await s.modules['returns'].maintenance()
    assert s.modules['returns'].db.get('returns',ret['id'])['status']=='Refunded'
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==3


async def test_gateway_timeout_and_redis_fail_closed(system,monkeypatch):
    import services.gateway as gateway
    class Timeout(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):raise httpx.ReadTimeout('Injected timeout',request=request)
    monkeypatch.setattr(gateway,'TRANSPORT',Timeout())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as c:
        r=await c.get('/products');assert r.status_code==504
        monkeypatch.setenv('REQUIRE_INFRA','true')
        r=await c.get('/products');assert r.status_code==503
