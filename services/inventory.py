import time
from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from common.db import uid
from common.runtime import make_app, staff, call
from common.security import internal


async def events(event):
    p=event['payload']
    if event['type']=='product.created':
        with db.tx() as c:
            if not db.get('inventory',p['id'],c):
                db.put(c,'inventory',p['id'],{'quantity':0,'reserved':0,'threshold':5})
    elif event['type']=='order.created':
        # Checkout has a synchronous reservation before publishing. The event
        # verifies the idempotent boundary and permits replay/recovery.
        if any(r['order_id']==p['id'] for r in db.all('reservations')):
            return
        reserve_local(Reservation(order_id=p['id'],items=[StockItem(product_id=i['product_id'],quantity=i['quantity']) for i in p['items']]), 'orders')


def release_expired():
    with db.tx() as c:
        for r in db.all('reservations',c):
            if r['status']=='active' and r['expires_at']<time.time():
                release_local(c,r,'expired')
                db.emit(c,'reservation.expired',{'order_id':r['order_id']})


async def maintenance():
    release_expired()


app, db=make_app('inventory',events,maintenance)


class StockItem(BaseModel):
    product_id: str=Field(min_length=1,max_length=100)
    quantity: int=Field(gt=0,le=10000,strict=True)


class Reservation(BaseModel):
    order_id: str=Field(min_length=1,max_length=100)
    items: list[StockItem]=Field(min_length=1,max_length=100)


class Adjustment(BaseModel):
    delta: int=Field(ge=-1000000,le=1000000,strict=True)
    reason: str=Field(min_length=3,max_length=500)
    threshold: int|None=Field(default=None,ge=0,le=1000000)


def stock(id,c=None):
    p=db.get('inventory',id,c) or {'id':id,'quantity':0,'reserved':0,'threshold':5}
    return dict(p,available=p['quantity']-p['reserved'])


def move(c,id,delta,reserved_delta,reason,actor,operation):
    if db.get('transactions',operation,c):
        return stock(id,c)
    s=stock(id,c)
    s['quantity']+=delta
    s['reserved']+=reserved_delta
    if s['quantity']<0 or s['reserved']<0 or s['quantity']<s['reserved']:
        raise HTTPException(409,'Insufficient available stock')
    s.pop('available',None)
    s=db.put(c,'inventory',id,s)
    db.put(c,'transactions',operation,{'product_id':id,'delta':delta,'reserved_delta':reserved_delta,
                                      'reason':reason,'actor':actor,'balance':s['quantity']})
    if s['quantity']-s['reserved']<=s['threshold']:
        db.emit(c,'stock.low',dict(s,available=s['quantity']-s['reserved']))
    return s


def reserve_local(body,actor):
    if len({i.product_id for i in body.items})!=len(body.items):
        raise HTTPException(422,'Duplicate product lines are not allowed')
    release_expired()
    with db.tx() as c:
        r=next((r for r in db.all('reservations',c) if r['order_id']==body.order_id),None)
        if r:
            expected=[i.model_dump() for i in body.items]
            if r['items']!=expected:
                raise HTTPException(409,'Reservation key reused with different items')
            if r['status'] in ['expired','released']:
                raise HTTPException(409,'Reservation is no longer active')
            return r
        id=uid()
        for item in body.items:
            move(c,item.product_id,0,item.quantity,'checkout reservation',actor,f'{id}:reserve:{item.product_id}')
        return db.put(c,'reservations',id,{'order_id':body.order_id,'items':[i.model_dump() for i in body.items],
            'status':'active','expires_at':time.time()+int(__import__('os').getenv('RESERVATION_SECONDS','900'))})


def release_local(c,r,status='released'):
    if r['status']!='active':
        return r
    for item in r['items']:
        move(c,item['product_id'],0,-item['quantity'],status,'system',f"{r['id']}:release:{item['product_id']}")
    return db.put(c,'reservations',r['id'],dict(r,status=status))


@app.get('/inventory')
def listing(user=Depends(staff)):
    release_expired()
    return [stock(r['id']) for r in db.all('inventory')]


@app.get('/inventory/{id}')
def item(id: str,user=Depends(staff)):
    release_expired()
    return stock(id)


@app.patch('/inventory/{id}/stock')
async def adjust(id: str,body: Adjustment,user=Depends(staff)):
    await call('products','GET',f'/internal/products/{id}')
    with db.tx() as c:
        if body.threshold is not None:
            db.put(c,'inventory',id,dict(stock(id,c),threshold=body.threshold))
        s=move(c,id,body.delta,0,body.reason,user['sub'],uid())
        db.audit(c,user['sub'],'stock_adjusted',id)
        return dict(s,available=s['quantity']-s['reserved'])


@app.get('/inventory/{id}/transactions')
def history(id: str,user=Depends(staff)):
    return [t for t in db.all('transactions') if t['product_id']==id]


@app.post('/inventory/reservations',dependencies=[Depends(internal)],status_code=201)
def reserve(body: Reservation):
    return reserve_local(body,'orders')


@app.post('/inventory/reservations/{id}/release',dependencies=[Depends(internal)])
def release(id: str):
    with db.tx() as c:
        r=db.get('reservations',id,c)
        if not r:
            raise HTTPException(404,'Reservation not found')
        return release_local(c,r)


@app.post('/internal/reservations/{id}/commit',dependencies=[Depends(internal)])
def commit(id: str):
    release_expired()
    with db.tx() as c:
        r=db.get('reservations',id,c)
        if not r:
            raise HTTPException(404,'Reservation not found')
        if r['status']=='committed':
            return r
        if r['status']!='active':
            raise HTTPException(409,'Reservation expired or released')
        for item in r['items']:
            move(c,item['product_id'],-item['quantity'],-item['quantity'],'order paid','payments',f"{id}:commit:{item['product_id']}")
        return db.put(c,'reservations',id,dict(r,status='committed'))


class Restore(BaseModel):
    operation_id: str=Field(min_length=1,max_length=200)
    items: list[StockItem]=Field(min_length=1,max_length=100)
    reason: str=Field(min_length=3,max_length=500)


@app.post('/internal/restore',dependencies=[Depends(internal)])
def restore(body: Restore):
    with db.tx() as c:
        for i in body.items:
            move(c,i.product_id,i.quantity,0,body.reason,'system',f'{body.operation_id}:{i.product_id}')
    return {'restored':True}


@app.get('/internal/stock',dependencies=[Depends(internal)])
def stocks():
    release_expired()
    return {r['id']:stock(r['id']) for r in db.all('inventory')}


@app.get('/internal/stock/{id}',dependencies=[Depends(internal)])
def one_stock(id: str):
    release_expired()
    return stock(id)

@app.post('/internal/reservations/order/{order_id}/release',dependencies=[Depends(internal)])
def release_order(order_id: str):
    with db.tx() as c:
        r=next((r for r in db.all('reservations',c) if r['order_id']==order_id),None)
        return release_local(c,r) if r else {'released':True}
