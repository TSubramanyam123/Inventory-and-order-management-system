from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from common.db import uid
from common.runtime import make_app, call, own, limiter
from common.security import current_user, internal

app,db=make_app('payments')


class Payment(BaseModel):
    model_config=ConfigDict(extra='forbid')  # Never accept card data.
    order_id: str=Field(min_length=1,max_length=100)
    outcome: str=Field(default='success',pattern='^(success|failure|cancel)$')


@app.post('/payments',status_code=201)
async def pay(body: Payment,idempotency_key: str=Header(min_length=8,max_length=100),user=Depends(current_user)):
    await limiter.check('payments:'+user['sub'],30)
    o=await call('orders','GET',f'/internal/orders/{body.order_id}')
    own(o,user)
    with db.tx() as c:
        previous=next((p for p in db.all('payments',c) if p['order_id']==body.order_id),None)
        if previous:
            if previous['outcome']!=body.outcome or previous['idempotency_key']!=idempotency_key:
                raise HTTPException(409,'Order already has a payment attempt; use the original request key, or create a new order after failure')
            return previous
        if o['status']!='Pending' or o['phase']!='ready':
            raise HTTPException(409,'Order is not awaiting payment')
        status={'success':'succeeded','failure':'failed','cancel':'cancelled'}[body.outcome]
        p=db.put(c,'payments',uid(),{'order_id':o['id'],'user_id':user['sub'],'amount':o['total'],
            'outcome':body.outcome,'status':status,'refunded':0,'reference':'SIM-'+uid()[:16],
            'idempotency_key':idempotency_key})
        db.emit(c,'payment.'+status,p)
        db.audit(c,user['sub'],'payment:'+status,p['id'])
        return p


@app.get('/payments/{id}')
def get(id: str,user=Depends(current_user)):
    return own(db.get('payments',id),user)


@app.post('/payments/{id}/cancel')
def cancel(id: str,user=Depends(current_user)):
    with db.tx() as c:
        p=own(db.get('payments',id,c),user)
        if p['status']=='succeeded':
            raise HTTPException(409,'Settled payments can only be refunded through cancellation or returns')
        if p['status']=='cancelled':
            return p
        p=db.put(c,'payments',id,dict(p,status='cancelled'))
        db.emit(c,'payment.cancelled',p)
        return p


class Refund(BaseModel):
    operation_id: str=Field(min_length=1,max_length=250)
    payment_id: str
    amount: int=Field(ge=0,strict=True)
    reason: str=Field(min_length=3,max_length=500)


@app.post('/internal/refunds',dependencies=[Depends(internal)])
def refund(body: Refund):
    with db.tx() as c:
        prior=db.get('refunds',body.operation_id,c)
        if prior:
            if prior['payment_id']!=body.payment_id or prior['amount']!=body.amount:
                raise HTTPException(409,'Refund operation key conflict')
            return prior
        p=db.get('payments',body.payment_id,c)
        if not p or p['status']!='succeeded':
            raise HTTPException(409,'A successful payment is required for refunds')
        if p['refunded']+body.amount>p['amount']:
            raise HTTPException(409,'Refund exceeds remaining paid amount')
        r=db.put(c,'refunds',body.operation_id,dict(body.model_dump(),status='completed',reference='REF-'+uid()[:16],order_id=p['order_id'],user_id=p['user_id']))
        db.put(c,'payments',p['id'],dict(p,refunded=p['refunded']+body.amount))
        db.emit(c,'refund.completed',r)
        db.audit(c,'system','refund_completed',body.operation_id)
        return r


@app.get('/internal/orders/{order_id}/payment',dependencies=[Depends(internal)])
def for_order(order_id: str):
    return next((p for p in db.all('payments') if p['order_id']==order_id),None)
