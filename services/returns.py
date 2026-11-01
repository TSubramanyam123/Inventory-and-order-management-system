import asyncio
import os
import time
from collections import defaultdict
from fastapi import Depends, HTTPException, Header
from pydantic import BaseModel, Field
from common.db import uid
from common.runtime import make_app, call, own, admin
from common.security import current_user, internal

locks=defaultdict(asyncio.Lock)


class ReturnItem(BaseModel):
    product_id: str
    quantity: int=Field(gt=0,le=10000,strict=True)


class ReturnRequest(BaseModel):
    order_id: str
    reason: str=Field(min_length=5,max_length=1000)
    items: list[ReturnItem]=Field(min_length=1,max_length=100)


async def accept(id):
    r=db.get('returns',id)
    if r['status'] not in ['Accepted','Refunded']:
        return r
    if r['status']=='Refunded':
        return r
    # ONLY physical acceptance restocks; approval never changes inventory.
    await call('inventory','POST','/internal/restore',{'operation_id':'return:'+id,'items':[{'product_id':i['product_id'],'quantity':i['quantity']} for i in r['items']],'reason':'Physically accepted return'})
    refund=await call('payments','POST','/internal/refunds',{'operation_id':'return:'+id,'payment_id':r['payment_id'],
        'amount':r['refund_amount'],'reason':r['reason']})
    with db.tx() as c:
        r=db.get('returns',id,c)
        db.put(c,'refund_records',id,refund)
        r=db.put(c,'returns',id,dict(r,status='Refunded',refund=refund,history=r['history']+[{'status':'Refunded','timestamp':time.time(),'actor':'system'}]))
        db.emit(c,'return.updated',r)
    return r


async def maintenance():
    for r in db.all('returns'):
        if r['status']=='Accepted':
            async with locks[r['id']]:
                await accept(r['id'])


async def events(event):
    if event['type']=='return.accepted':
        async with locks[event['payload']['id']]:
            await accept(event['payload']['id'])


app,db=make_app('returns',events,maintenance)


@app.post('/returns',status_code=201)
async def create(body: ReturnRequest,idempotency_key: str=Header(min_length=8,max_length=100),user=Depends(current_user)):
    o=await call('orders','GET',f'/internal/orders/{body.order_id}')
    own(o,user)
    if o['status']!='Delivered' or time.time()-o['delivered_at']>int(os.getenv('RETURN_WINDOW_DAYS','30'))*86400:
        raise HTTPException(409,'Order is outside the delivered return window')
    if len({i.product_id for i in body.items})!=len(body.items):
        raise HTTPException(422,'Duplicate product lines are not allowed')
    with db.tx() as c:
        all_returns=[r for r in db.all('returns',c) if r['order_id']==body.order_id]
        prior=next((r for r in all_returns if r['idempotency_key']==idempotency_key),None)
        if prior:
            if [{'product_id':i['product_id'],'quantity':i['quantity']} for i in prior['items']]!=[i.model_dump() for i in body.items] or prior['reason']!=body.reason:
                raise HTTPException(409,'Return request key conflict')
            return prior
        refund=0
        allocations={}
        for item in body.items:
            line=next((i for i in o['items'] if i['product_id']==item.product_id),None)
            used=sum(i['quantity'] for r in all_returns if r['status']!='Rejected' for i in r['items'] if i['product_id']==item.product_id)
            if not line or item.quantity+used>line['quantity']-line['cancelled_quantity']:
                raise HTTPException(422,'Requested return exceeds eligible quantity')
            occupied={slot for r in all_returns if r['status']!='Rejected' for ri in r['items'] if ri['product_id']==item.product_id for slot in ri.get('unit_slots',[])}
            slots=[n for n in range(line['cancelled_quantity'],line['quantity']) if n not in occupied][:item.quantity]
            if len(slots)!=item.quantity:
                raise HTTPException(422,'Not enough returnable units')
            refund+=sum(line['paid_amount']*(n+1)//line['quantity']-line['paid_amount']*n//line['quantity'] for n in slots)
            allocations[item.product_id]=slots
        items=[dict(i.model_dump(),unit_slots=allocations[i.product_id]) for i in body.items]
        r=db.put(c,'returns',uid(),dict(body.model_dump(),items=items,user_id=user['sub'],idempotency_key=idempotency_key,
            status='Requested',payment_id=o['payment_id'],refund_amount=refund,
            history=[{'status':'Requested','timestamp':time.time(),'actor':user['sub']}]))
        db.audit(c,user['sub'],'return_requested',r['id'])
        return r


@app.get('/returns/my-returns')
def mine(user=Depends(current_user)):
    return [r for r in db.all('returns') if r['user_id']==user['sub']]


@app.get('/returns')
def listing(user=Depends(admin)):
    return db.all('returns')


@app.get('/returns/{id}')
def get(id: str,user=Depends(current_user)):
    return own(db.get('returns',id),user)


class Status(BaseModel):
    status: str=Field(pattern='^(Approved|Rejected|Accepted)$')
    note: str=Field(min_length=3,max_length=500)


@app.patch('/returns/{id}/status')
async def status(id: str,body: Status,user=Depends(admin)):
    async with locks[id]:
        with db.tx() as c:
            r=db.get('returns',id,c)
            if not r:
                raise HTTPException(404,'Return not found')
            if r['status']==body.status or (r['status']=='Refunded' and body.status=='Accepted'):
                return r
            if body.status not in {'Requested':['Approved','Rejected'],'Approved':['Accepted','Rejected']}.get(r['status'],[]):
                raise HTTPException(409,'Invalid return status transition')
            r=db.put(c,'returns',id,dict(r,status=body.status,history=r['history']+[
                {'status':body.status,'timestamp':time.time(),'actor':user['sub'],'note':body.note}]))
            db.emit(c,'return.updated',r)
            if body.status=='Accepted':
                db.emit(c,'return.accepted',r)
            db.audit(c,user['sub'],'return:'+body.status,id)
        return await accept(id) if body.status=='Accepted' else r


@app.get('/internal/returns',dependencies=[Depends(internal)])
def internal_returns():
    return db.all('returns')
