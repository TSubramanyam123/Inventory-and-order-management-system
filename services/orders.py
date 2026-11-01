import asyncio
import hashlib
import io
import json
import os
import time
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from fastapi import Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from reportlab.pdfgen import canvas
from common.db import uid
from common.runtime import make_app, call, own, admin
from common.security import current_user, internal

locks=defaultdict(asyncio.Lock)


def money_tax(amount):
    return int((Decimal(amount)*Decimal(os.getenv('TAX_RATE','0.18'))).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def totals(subtotal,discount):
    tax=money_tax(subtotal-discount)
    shipping=0 if subtotal>=int(os.getenv('FREE_SHIPPING_MINIMUM','200000')) else int(os.getenv('SHIPPING_CHARGE','5000'))
    return {'subtotal':subtotal,'discount':discount,'tax':tax,'shipping':shipping,'total':subtotal-discount+tax+shipping}


def allocate(items,total):
    subtotal=sum(i['price']*i['quantity'] for i in items)
    left=total
    for n,i in enumerate(items):
        value=total*i['price']*i['quantity']//subtotal if n<len(items)-1 else left
        i['paid_amount']=value
        left-=value
    return items


def save(c,o):
    o=db.put(c,'orders',o['id'],o)
    for item in o['items']:
        db.put(c,'order_items',o['id']+':'+item['product_id'],dict(item,order_id=o['id']))
    return o


def transition(c,o,status,reason=''):
    o=dict(o,status=status,timeline=o['timeline']+[{'status':status,'timestamp':time.time(),'reason':reason}])
    return save(c,o)


async def prepare(id):
    o=db.get('orders',id)
    if o['phase']!='preparing' or o['status']!='Pending':
        return o
    try:
        discount=0
        if o['coupon']:
            result=await call('coupons','POST','/internal/redeem',{'code':o['coupon'],'subtotal':o['subtotal'],'user_id':o['user_id'],'order_id':id})
            discount=result['discount']
        reservation=await call('inventory','POST','/inventory/reservations',{'order_id':id,'items':[{'product_id':i['product_id'],'quantity':i['quantity']} for i in o['items']]})
        with db.tx() as c:
            o=db.get('orders',id,c)
            o.update(totals(o['subtotal'],discount))
            o.update(reservation_id=reservation['id'],phase='ready',items=allocate(o['items'],o['total']))
            o=save(c,o)
            db.emit(c,'order.created',o)
            # Clearing is handled using a stable operation in cart service.
        return o
    except HTTPException as exc:
        if exc.status_code<500:
            with db.tx() as c:
                o=transition(c,db.get('orders',id,c),'Cancelled',str(exc.detail))
                o=save(c,dict(o,phase='cancel_cleanup',failure=str(exc.detail)))
                db.emit(c,'order.cancelled',o)
            await cleanup_cancel(id)
        raise


async def cleanup_cancel(id):
    o=db.get('orders',id)
    await call('inventory','POST',f'/internal/reservations/order/{id}/release')
    if o['coupon']:
        await call('coupons','POST',f'/internal/redemptions/{id}/release')
    if o.get('payment_id'):
        await call('payments','POST','/internal/refunds',{'payment_id':o['payment_id'],'operation_id':'cancel:'+id,
            'amount':o.get('cancellation_refund',o['total']),'reason':'Order cancelled'})
    with db.tx() as c:
        o=db.get('orders',id,c)
        save(c,dict(o,phase='cancelled'))


async def events(event):
    p=event['payload']
    id=p.get('order_id',p.get('id'))
    if event['type'] not in ['payment.succeeded','payment.failed','payment.cancelled','reservation.expired']:
        return
    async with locks[id]:
        o=db.get('orders',id)
        if not o:
            raise HTTPException(404,'Order not yet available')
        if event['type']=='payment.succeeded':
            if o.get('payment_id')==p['id'] and o['status'] in ['Confirmed','Processing','Shipped','Delivered']:
                return
            if p['amount']!=o['total']:
                raise HTTPException(409,'Payment amount mismatch')
            if o['status']=='Cancelled':
                await call('payments','POST','/internal/refunds',{'payment_id':p['id'],'operation_id':'cancel:'+id,'amount':o.get('cancellation_refund',p['amount']),'reason':'Late payment on cancelled order'})
                return
            try:
                await call('inventory','POST',f"/internal/reservations/{o['reservation_id']}/commit")
            except HTTPException as exc:
                if exc.status_code>=500:
                    raise
                with db.tx() as c:
                    o=save(c,dict(o,payment_id=p['id']))
                    o=transition(c,o,'Cancelled','Stock reservation expired before payment confirmation')
                    save(c,dict(o,phase='cancel_cleanup'))
                    db.emit(c,'order.cancelled',o)
                await cleanup_cancel(id)
                return
            with db.tx() as c:
                o=save(c,dict(db.get('orders',id,c),payment_id=p['id'],phase='paid'))
                o=transition(c,o,'Confirmed')
                db.emit(c,'order.confirmed',o)
            await clear_cart(o)
        elif o['status']=='Pending':
            await cancel_full(id,'Payment unsuccessful or stock reservation expired')


async def clear_cart(o):
    await call('cart','POST',f"/internal/cart/{o['user_id']}/clear",{'operation_id':o['id'],
        'items':[{'product_id':i['product_id'],'quantity':i['quantity']} for i in o['items']]})
    with db.tx() as c:
        current=db.get('orders',o['id'],c)
        save(c,dict(current,cart_cleared=True))


async def cancel_full(id,reason):
    o=db.get('orders',id)
    if o['status']=='Cancelled':
        if o['phase']=='cancel_cleanup':
            await cleanup_cancel(id)
        return db.get('orders',id)
    if o['status'] not in ['Pending','Confirmed','Processing']:
        raise HTTPException(409,'Shipped or delivered orders cannot be cancelled')
    # If a payment was recorded but its event has not arrived, do not race commit.
    payment=await call('payments','GET',f'/internal/orders/{id}/payment')
    if payment and payment['status']=='succeeded' and not o.get('payment_id'):
        raise HTTPException(409,'Payment confirmation is in progress; retry cancellation shortly')
    was_paid=bool(o.get('payment_id'))
    if was_paid:
        await recover_partials(o)
    cancellation_refund=o['total']-sum(i.get('paid_amount',0)*i['cancelled_quantity']//i['quantity'] for i in o['items'])
    # Write cancellation intent first. Background maintenance completes compensation.
    with db.tx() as c:
        o=transition(c,o,'Cancelled',reason)
        o=save(c,dict(o,phase='cancel_cleanup',was_paid=was_paid,cancellation_refund=cancellation_refund))
        db.emit(c,'order.cancelled',o)
        db.audit(c,o['user_id'],'order_cancelled',id)
    if was_paid:
        await call('inventory','POST','/internal/restore',{'operation_id':'cancel:'+id,'reason':reason,
            'items':[{'product_id':i['product_id'],'quantity':i['quantity']-i['cancelled_quantity']} for i in o['items'] if i['quantity']>i['cancelled_quantity']]})
    await cleanup_cancel(id)
    return db.get('orders',id)


async def maintenance():
    for row in db.all('orders'):
        async with locks[row['id']]:
            o=db.get('orders',row['id'])
            try:
                if o['phase']=='preparing':
                    await prepare(o['id'])
                elif o['phase']=='cancel_cleanup':
                    if o.get('was_paid'):
                        items=[{'product_id':i['product_id'],'quantity':i['quantity']-i['cancelled_quantity']} for i in o['items'] if i['quantity']>i['cancelled_quantity']]
                        if items:
                            await call('inventory','POST','/internal/restore',{'operation_id':'cancel:'+o['id'],'reason':'Order cancellation','items':items})
                    await cleanup_cancel(o['id'])
                elif o.get('payment_id') and not o.get('cart_cleared'):
                    await clear_cart(o)
                await recover_partials(o)
            except HTTPException:
                pass


app,db=make_app('orders',events,maintenance)


class Checkout(BaseModel):
    coupon: str=Field(default='',max_length=30)
    address: str=Field(min_length=10,max_length=1000)


@app.post('/orders',status_code=201)
async def create(body: Checkout,idempotency_key: str=Header(min_length=8,max_length=100),user=Depends(current_user)):
    key=user['sub']+':'+idempotency_key
    async with locks[key]:
        prior=next((o for o in db.all('orders') if o['user_id']==user['sub'] and o['idempotency_key']==idempotency_key),None)
        if prior:
            if prior['address']!=body.address or prior['coupon']!=body.coupon.upper():
                raise HTTPException(409,'Idempotency key reused with different checkout details')
            async with locks[prior['id']]:
                return await prepare(prior['id'])
        cart=await call('cart','GET',f"/internal/cart/{user['sub']}")
        if not cart['items']:
            raise HTTPException(400,'Cart is empty')
        if any(i['available']<i['quantity'] for i in cart['items']):
            raise HTTPException(409,'Some cart items are unavailable')
        items=[{'product_id':i['product_id'],'name':i['product']['name'],'category':i['product']['category'],
                'price':i['product']['price'],'quantity':i['quantity'],'cancelled_quantity':0} for i in cart['items']]
        id=uid()
        with db.tx() as c:
            o=save(c,dict(id=id,number='ORD-'+time.strftime('%Y%m%d')+'-'+id[:8].upper(),
                user_id=user['sub'],idempotency_key=idempotency_key,address=body.address,coupon=body.coupon.upper(),
                items=items,status='Pending',phase='preparing',**totals(cart['subtotal'],0),
                timeline=[{'status':'Pending','timestamp':time.time(),'reason':'Awaiting payment'}]))
        async with locks[id]:
            return await prepare(id)


@app.get('/orders/my-orders')
def mine(user=Depends(current_user)):
    return [o for o in db.all('orders') if o['user_id']==user['sub']]


@app.get('/orders')
def listing(user=Depends(admin)):
    return db.all('orders')


@app.get('/orders/{id}')
def get(id: str,user=Depends(current_user)):
    return own(db.get('orders',id),user)


class Status(BaseModel):
    status: str=Field(pattern='^(Processing|Shipped|Delivered)$')
    tracking_number: str=Field(default='',max_length=100)


@app.patch('/orders/{id}/status')
async def status(id: str,body: Status,user=Depends(admin)):
    async with locks[id]:
        with db.tx() as c:
            o=db.get('orders',id,c)
            if not o:
                raise HTTPException(404,'Order not found')
            if o['status']==body.status:
                return o
            if {'Confirmed':'Processing','Processing':'Shipped','Shipped':'Delivered'}.get(o['status'])!=body.status:
                raise HTTPException(409,'Invalid order status transition')
            o=transition(c,o,body.status)
            if body.tracking_number:
                o=save(c,dict(o,tracking_number=body.tracking_number))
            if body.status=='Delivered':
                o=save(c,dict(o,delivered_at=time.time()))
            db.emit(c,'order.'+body.status.lower(),o)
            db.audit(c,user['sub'],'order_status:'+body.status,id)
            return o


class Cancel(BaseModel):
    reason: str=Field(default='Customer cancellation',min_length=3,max_length=500)
    product_id: str|None=None
    quantity: int|None=Field(default=None,gt=0,le=10000,strict=True)


async def recover_partials(o):
    for op in db.all('operations'):
        if op.get('order_id')!=o['id'] or op.get('status')=='complete':
            continue
        await call('inventory','POST','/internal/restore',{'operation_id':op['id'],'items':op['items'],'reason':op['reason']})
        await call('payments','POST','/internal/refunds',{'operation_id':op['id'],'payment_id':o['payment_id'],'amount':op['amount'],'reason':op['reason']})
        with db.tx() as c:
            db.put(c,'operations',op['id'],dict(op,status='complete'))


@app.post('/orders/{id}/cancel')
async def cancel(id: str,body: Cancel,idempotency_key: str=Header(default='',max_length=100),user=Depends(current_user)):
    async with locks[id]:
        o=own(db.get('orders',id),user)
        if not body.product_id:
            return await cancel_full(id,body.reason)
        if o['status'] not in ['Confirmed','Processing'] or not body.quantity:
            raise HTTPException(409,'Partial cancellation requires a paid, unshipped order and quantity')
        if len(idempotency_key)<8:
            raise HTTPException(422,'Partial cancellation requires Idempotency-Key of at least 8 characters')
        op_id='partial:'+id+':'+idempotency_key
        prior=db.get('operations',op_id)
        if prior:
            if prior['items']!=[{'product_id':body.product_id,'quantity':body.quantity}]:
                raise HTTPException(409,'Cancellation key reused with different items')
            await recover_partials(o)
            return db.get('orders',id)
        item=next((i for i in o['items'] if i['product_id']==body.product_id),None)
        if not item or body.quantity>item['quantity']-item['cancelled_quantity']:
            raise HTTPException(422,'Invalid cancellation quantity')
        if sum(i['quantity']-i['cancelled_quantity'] for i in o['items'])==body.quantity:
            return await cancel_full(id,body.reason)
        old=item['cancelled_quantity']
        item['cancelled_quantity']+=body.quantity
        refund=item['paid_amount']*item['cancelled_quantity']//item['quantity']-item['paid_amount']*old//item['quantity']
        with db.tx() as c:
            save(c,o)
            db.put(c,'operations',op_id,{'order_id':id,'items':[{'product_id':body.product_id,'quantity':body.quantity}],
                'amount':refund,'reason':body.reason,'status':'pending'})
            db.audit(c,user['sub'],'partial_cancellation',id)
        await recover_partials(o)
        return db.get('orders',id)


@app.get('/orders/{id}/invoice')
def invoice(id: str,user=Depends(current_user)):
    o=own(db.get('orders',id),user)
    buffer=io.BytesIO()
    pdf=canvas.Canvas(buffer)
    pdf.setTitle('Invoice '+o['number'])
    pdf.setFont('Helvetica-Bold',18)
    pdf.drawString(50,790,'NORTHSTAR | Order invoice')
    pdf.setFont('Helvetica',11)
    lines=[o['number'],f"Status: {o['status']}",f"Ship to: {o['address']}",'']
    lines += [f"{i['name']} x {i['quantity']}  INR {i['price']*i['quantity']/100:.2f}" for i in o['items']]
    lines += ['',*[f'{k.title()}: INR {o[k]/100:.2f}' for k in ['subtotal','discount','tax','shipping','total']]]
    y=755
    import textwrap
    for line in lines:
        for part in textwrap.wrap(line,88) or ['']:
            if y<60:
                pdf.showPage();pdf.setFont('Helvetica',11);y=790
            pdf.drawString(50,y,part);y-=19
    pdf.save()
    return Response(buffer.getvalue(),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename={o["number"]}.pdf'})


@app.get('/internal/orders/{id}',dependencies=[Depends(internal)])
def internal_order(id: str):
    o=db.get('orders',id)
    if not o:
        raise HTTPException(404,'Order not found')
    return o


@app.get('/internal/orders',dependencies=[Depends(internal)])
def internal_orders():
    return db.all('orders')

@app.post('/orders/{id}/admin-cancel')
async def admin_cancel(id: str,body: Cancel,user=Depends(admin)):
    async with locks[id]:
        if not db.get('orders',id):
            raise HTTPException(404,'Order not found')
        return await cancel_full(id,body.reason)
