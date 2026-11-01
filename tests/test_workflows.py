import asyncio
import time
import pytest
from common.db import uid
from common.events import process_event
from common.security import hash_password,check_password
from common import runtime

pytestmark=pytest.mark.asyncio


async def test_end_to_end_coupon_payment_delivery_review_return(system):
    s=system;p=await s.product(quantity=5)
    r=await s.request('coupons','POST','/coupons',{'code':'SAVE10','kind':'percentage','value':10,'expires_at':time.time()+3600,'usage_limit':5,'minimum_purchase':10000},'admin')
    assert r.status_code==201
    o=await s.order(p,2,coupon='SAVE10');assert o['discount']==2000
    payment=await s.pay(o)
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==3
    assert (await s.request('cart','GET','/cart')).json()['items']==[]
    assert (await s.request('orders','GET','/orders/'+o['id'])).json()['status']=='Confirmed'
    await s.deliver(o)
    r=await s.request('reviews','POST','/reviews',{'product_id':p['id'],'order_id':o['id'],'rating':5,'text':'Excellent camera for everyday travel.'})
    assert r.status_code==201,r.text
    assert (await s.request('reviews','GET','/products/'+p['id']+'/reviews',user=None)).json()['rating']==5
    r=await s.request('returns','POST','/returns',{'order_id':o['id'],'reason':'Arrived with a damaged surface','items':[{'product_id':p['id'],'quantity':1}]},headers={'Idempotency-Key':uid()})
    assert r.status_code==201,r.text
    ret=r.json()
    r=await s.request('returns','PATCH','/returns/'+ret['id']+'/status',{'status':'Approved','note':'Please return the item'},'admin');assert r.status_code==200
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==3
    r=await s.request('returns','PATCH','/returns/'+ret['id']+'/status',{'status':'Accepted','note':'Item physically received and inspected'},'admin')
    assert r.status_code==200,r.text
    assert r.json()['status']=='Refunded'
    await s.pump()
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==4
    assert (await s.request('payments','GET','/payments/'+payment['id'])).json()['refunded']==ret['refund_amount']
    assert len((await s.request('notifications','GET','/notifications')).json())>=4
    assert (await s.request('analytics','GET','/analytics/sales',user='admin')).json()['revenue']==o['total']-ret['refund_amount']
    assert (await s.request('analytics','GET','/analytics/export',user='admin')).headers['content-type'].startswith('text/csv')
    assert (await s.request('orders','GET','/orders/'+o['id']+'/invoice')).content.startswith(b'%PDF')


@pytest.mark.parametrize('outcome',['failure','cancel'])
async def test_failed_payment_releases_reservation(system,outcome):
    s=system;p=await s.product(3);o=await s.order(p,2);await s.pay(o,outcome)
    assert (await s.request('orders','GET','/orders/'+o['id'])).json()['status']=='Cancelled'
    stock=(await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()
    assert stock['quantity']==3 and stock['reserved']==0


async def test_partial_then_full_cancellation_has_exact_stock_and_refund(system):
    s=system;p=await s.product(5);o=await s.order(p,3);payment=await s.pay(o)
    h={'Idempotency-Key':'cancel-once-123'}
    body={'product_id':p['id'],'quantity':1,'reason':'Need fewer items'}
    for _ in range(2):
        r=await s.request('orders','POST','/orders/'+o['id']+'/cancel',body,headers=h);assert r.status_code==200,r.text
    r=await s.request('orders','POST','/orders/'+o['id']+'/cancel',{'reason':'Cancel remaining items'})
    assert r.status_code==200,r.text
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==5
    assert (await s.request('payments','GET','/payments/'+payment['id'])).json()['refunded']==payment['amount']


async def test_order_and_payment_idempotency(system):
    s=system;p=await s.product();await s.request('cart','POST','/cart/items',{'product_id':p['id'],'quantity':1})
    h={'Idempotency-Key':'checkout-once-123'};body={'address':'123 Test Street, Hyderabad'}
    r1=await s.request('orders','POST','/orders',body,headers=h);r2=await s.request('orders','POST','/orders',body,headers=h)
    assert r1.json()['id']==r2.json()['id']
    assert len(s.modules['inventory'].db.all('reservations'))==1
    body={'order_id':r1.json()['id'],'outcome':'success'};h={'Idempotency-Key':'payment-once-123'}
    r1=await s.request('payments','POST','/payments',body,headers=h);r2=await s.request('payments','POST','/payments',body,headers=h)
    assert r1.json()['id']==r2.json()['id']
    await s.pump()
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['quantity']==9


async def test_concurrent_reservations_never_oversell(system):
    s=system;p=await s.product(1)
    async def reserve(n):
        return await s.internal('inventory','POST','/inventory/reservations',{'order_id':'concurrent-'+str(n),'items':[{'product_id':p['id'],'quantity':1}]})
    results=await asyncio.gather(*(reserve(n) for n in range(10)))
    assert sum(r.status_code==201 for r in results)==1
    assert sum(r.status_code==409 for r in results)==9
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['available']==0


async def test_reservation_expiry_and_duplicate_commit(system):
    s=system;p=await s.product(2)
    r=(await s.internal('inventory','POST','/inventory/reservations',{'order_id':'expiring','items':[{'product_id':p['id'],'quantity':2}]})).json()
    db=s.modules['inventory'].db
    with db.tx() as c:db.put(c,'reservations',r['id'],dict(r,expires_at=time.time()-1))
    await s.modules['inventory'].maintenance()
    assert (await s.internal('inventory','GET','/internal/stock/'+p['id'])).json()['reserved']==0
    assert (await s.internal('inventory','POST','/internal/reservations/'+r['id']+'/commit')).status_code==409


async def test_event_replay_and_handler_failure_retries(system):
    s=system;db=s.modules['notifications'].db
    event={'event_id':uid(),'type':'order.confirmed','payload':{'id':'order1','user_id':s.users['alice']['id']}}
    await process_event(db,event,s.modules['notifications'].events)
    await process_event(db,event,s.modules['notifications'].events)
    assert len(db.all('notifications'))==1
    event=dict(event,event_id=uid());calls=[]
    async def flaky(e):
        calls.append(e)
        if len(calls)==1:raise RuntimeError('Temporary failure')
    with pytest.raises(RuntimeError):await process_event(db,event,flaky)
    assert not db.get('inbox',event['event_id'])
    await process_event(db,event,flaky)
    assert len(calls)==2 and db.get('inbox',event['event_id'])


async def test_service_failure_during_checkout_recovers_same_key(system):
    s=system;p=await s.product();await s.request('cart','POST','/cart/items',{'product_id':p['id'],'quantity':1})
    s.network.failed.add('coupons')
    # Coupon outage after local order intent was committed.
    h={'Idempotency-Key':'recover-checkout-key'};body={'address':'123 Recovery Street, Hyderabad','coupon':'MISSING'}
    r=await s.request('orders','POST','/orders',body,headers=h);assert r.status_code==503
    assert len(s.modules['orders'].db.all('orders'))==1
    s.network.failed.clear()
    r=await s.request('orders','POST','/orders',body,headers=h);assert r.status_code==400
    assert len(s.modules['orders'].db.all('orders'))==1
    assert s.modules['orders'].db.all('orders')[0]['status']=='Cancelled'


async def test_coupon_expiry_limit_and_repeat_redemption(system):
    s=system;p=await s.product()
    r=await s.request('coupons','POST','/coupons',{'code':'ONCE','kind':'fixed','value':1000,'expires_at':time.time()+3600,'usage_limit':1},'admin');assert r.status_code==201
    o=await s.order(p,coupon='ONCE');await s.pay(o)
    assert (await s.request('coupons','POST','/coupons/validate',{'code':'ONCE','subtotal':10000})).status_code==409
    assert (await s.request('coupons','POST','/coupons/validate',{'code':'ONCE','subtotal':10000},'bob')).status_code==409
    db=s.modules['coupons'].db
    with db.tx() as c:
        coupon=db.get('coupons','ONCE',c);db.put(c,'coupons','ONCE',dict(coupon,expires_at=time.time()-1))
    assert (await s.request('coupons','POST','/coupons/validate',{'code':'ONCE','subtotal':10000},'bob')).status_code==400


async def test_no_return_before_delivery_no_over_return(system):
    s=system;p=await s.product();o=await s.order(p);await s.pay(o)
    body={'order_id':o['id'],'reason':'Wrong item received','items':[{'product_id':p['id'],'quantity':1}]}
    r=await s.request('returns','POST','/returns',body,headers={'Idempotency-Key':uid()});assert r.status_code==409
    await s.deliver(o)
    r=await s.request('returns','POST','/returns',body,headers={'Idempotency-Key':uid()});assert r.status_code==201
    r=await s.request('returns','POST','/returns',body,headers={'Idempotency-Key':uid()});assert r.status_code==422


async def test_all_services_health(system):
    for name in runtime.SERVICES:
        r=await system.request(name,'GET','/health',user=None)
        assert r.status_code==200 and r.json()['service']==name


async def test_password_hash_salts():
    a=hash_password('SecurePassword!');b=hash_password('SecurePassword!')
    assert a!=b and check_password('SecurePassword!',a) and not check_password('wrong',a)


async def test_money_uses_integer_half_up():
    from services.orders import totals
    assert totals(10001,1)['tax']==1800
    assert totals(10001,1)['total']==16800
