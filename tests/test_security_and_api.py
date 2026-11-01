import importlib
import os
import time
import httpx
import jwt
import pytest
from common import runtime
from common.db import uid
from common.security import token

pytestmark=pytest.mark.asyncio


async def test_registration_role_escalation_and_login(system):
    s=system
    r=await s.request('auth','POST','/auth/register',{'name':'New Customer','email':'new@example.com','password':'SecurePass123!','role':'Administrator'},user=None)
    assert r.status_code==201 and r.json()['role']=='Customer' and 'password_hash' not in r.json()
    r=await s.request('auth','POST','/auth/register',{'name':'New Customer','email':'NEW@example.com','password':'SecurePass123!'},user=None);assert r.status_code==409
    r=await s.request('auth','POST','/auth/login',{'email':'new@example.com','password':'wrongpass'},user=None);assert r.status_code==401


async def test_refresh_rotation_logout_and_expiration(system):
    app=system.modules['auth'].app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        r=await c.post('/auth/login',json={'email':'alice@example.com','password':'StrongPass123!'});assert r.status_code==200
        old=c.cookies.get('refresh_token');assert 'HttpOnly' in r.headers['set-cookie']
        r=await c.post('/auth/refresh');assert r.status_code==200 and c.cookies.get('refresh_token')!=old
        current=c.cookies.get('refresh_token')
        c.cookies.clear();c.cookies.set('refresh_token',old)
        assert (await c.post('/auth/refresh')).status_code==401
        c.cookies.clear();c.cookies.set('refresh_token',current)
        await c.post('/auth/logout');assert (await c.post('/auth/refresh')).status_code==401
    payload={'sub':'alice','role':'Customer','exp':time.time()-100,'iss':'inventory-auth','aud':'inventory-api'}
    expired=jwt.encode(payload,os.environ['JWT_SECRET'],algorithm='HS256')
    r=await system.request('auth','GET','/auth/me',headers={'Authorization':'Bearer '+expired});assert r.status_code==401


async def test_private_records_and_role_boundaries(system):
    s=system;p=await s.product();o=await s.order(p);payment=await s.pay(o)
    r=await s.request('orders','GET','/orders/'+o['id'],user='bob');assert r.status_code==403
    r=await s.request('payments','GET','/payments/'+payment['id'],user='bob');assert r.status_code==403
    assert (await s.request('inventory','GET','/inventory')).status_code==403
    assert (await s.request('analytics','GET','/analytics/sales',user='manager')).status_code==403
    assert (await s.request('inventory','GET','/inventory',user='manager')).status_code==200
    assert (await s.request('inventory','POST','/inventory/reservations',{'order_id':'bad','items':[]})).status_code in [403,422]
    await s.pump();n=(await s.request('notifications','GET','/notifications')).json()[0]
    assert (await s.request('notifications','PATCH','/notifications/'+n['id']+'/read',user='bob')).status_code==403
    assert (await s.request('notifications','PATCH','/notifications/'+n['id']+'/read')).status_code==200


async def test_live_role_revocation(system):
    s=system
    r=await s.request('auth','PATCH','/auth/users/'+s.users['manager']['id']+'/role',{'role':'Customer'},'admin');assert r.status_code==200
    assert (await s.request('inventory','GET','/inventory',user='manager')).status_code==403


async def test_invalid_inputs_and_negative_inventory(system):
    s=system;p=await s.product(1)
    assert (await s.request('cart','POST','/cart/items',{'product_id':p['id'],'quantity':0})).status_code==422
    assert (await s.request('cart','POST','/cart/items',{'product_id':p['id'],'quantity':2})).status_code==409
    assert (await s.request('inventory','PATCH','/inventory/'+p['id']+'/stock',{'delta':-2,'reason':'Testing deduction'},'admin')).status_code==409
    for price in [-1,0,1.2]:
        r=await s.request('products','POST','/products',{'name':'Test','description':'Description','category':'Test','brand':'Test','price':price},'admin');assert r.status_code==422
    assert (await s.request('payments','POST','/payments',{'order_id':'none','card_number':'1234'},headers={'Idempotency-Key':uid()})).status_code==422


async def test_product_filters_comparison_views_and_csv(system):
    s=system;p=await s.product(3,10000);p2=await s.product(0,30000)
    r=await s.request('products','GET','/products?q=camera&in_stock=true&sort=price_desc&max_price=20000',user=None)
    assert r.status_code==200 and r.json()['total']==1
    assert (await s.request('products','GET','/products/compare?ids='+p['id']+','+p2['id'],user=None)).status_code==200
    await s.request('products','POST','/products/'+p['id']+'/view')
    assert (await s.request('products','GET','/products/recently-viewed')).json()[0]['id']==p['id']
    app=s.modules['products'].app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer '+s.users['admin']['token']}) as c:
        r=await c.post('/products/bulk-import',files={'file':('products.csv','name,description,category,brand,price\nNew Tripod,Strong metal tripod,Photo,Vista,5000\n','text/csv')});assert r.status_code==201,r.text
        r=await c.post('/products/bulk-import',files={'file':('products.csv','name,price\nIncomplete,-1\n','text/csv')});assert r.status_code==422


async def test_wishlist_persistence_and_cart_ownership(system):
    s=system;p=await s.product()
    r=await s.request('cart','POST','/wishlist/items',{'product_id':p['id']});assert r.status_code==201
    item=r.json();assert len((await s.request('cart','GET','/wishlist')).json())==1
    assert (await s.request('cart','DELETE','/wishlist/items/'+item['id'],user='bob')).status_code==404
    assert (await s.request('cart','DELETE','/wishlist/items/'+item['id'])).status_code==204
    r=await s.request('cart','POST','/cart/items',{'product_id':p['id'],'quantity':1});id=r.json()['id']
    assert (await s.request('cart','PATCH','/cart/items/'+id,{'quantity':2},'bob')).status_code==404
    assert (await s.request('cart','DELETE','/cart/items/'+id)).status_code==204


async def test_unpurchased_review_and_moderation(system):
    s=system;p=await s.product();o=await s.order(p)
    body={'order_id':o['id'],'product_id':p['id'],'rating':4,'text':'Lovely product'}
    assert (await s.request('reviews','POST','/reviews',body)).status_code==403
    await s.pay(o);await s.deliver(o)
    r=await s.request('reviews','POST','/reviews',body);id=r.json()['id']
    assert (await s.request('reviews','PUT','/reviews/'+id,{'rating':5,'text':'Updated review'},'bob')).status_code==403
    assert (await s.request('reviews','PATCH','/reviews/'+id+'/moderate',{'visible':False},'admin')).status_code==200
    assert (await s.request('reviews','GET','/products/'+p['id']+'/reviews',user=None)).json()['count']==0
    await s.request('reviews','PUT','/reviews/'+id,{'rating':5,'text':'Updated review'})
    assert (await s.request('reviews','GET','/products/'+p['id']+'/reviews',user=None)).json()['count']==0
    assert (await s.request('reviews','DELETE','/reviews/'+id)).status_code==204


async def test_gateway_auth_routing_errors_and_timeout(system,monkeypatch):
    gateway=importlib.import_module('services.gateway')
    monkeypatch.setattr(gateway,'TRANSPORT',system.network,raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://gateway') as c:
        r=await c.get('/orders');assert r.status_code==401 and r.json()['correlation_id']
        r=await c.get('/internal/orders');assert r.status_code==404
        r=await c.get('/products',headers={'X-Correlation-ID':'gateway-test-123'});assert r.status_code==200 and r.headers['X-Correlation-ID']=='gateway-test-123'
        system.network.failed.add('products')
        r=await c.get('/products');assert r.status_code==503 and 'unavailable' in r.json()['detail']
        system.network.failed.clear()
        r=await c.get('/api/openapi.json');assert r.status_code==200 and '/auth/login' in r.json()['paths']
        assert not any(p.startswith('/internal') for p in r.json()['paths'])


async def test_login_rate_limit(system):
    for _ in range(10):
        r=await system.request('auth','POST','/auth/login',{'email':'none@example.com','password':'wrongpass'},user=None)
        assert r.status_code==401
    r=await system.request('auth','POST','/auth/login',{'email':'none@example.com','password':'wrongpass'},user=None)
    assert r.status_code==429
