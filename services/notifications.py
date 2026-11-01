from fastapi import Depends, HTTPException
from common.runtime import make_app, own, admin
from common.security import current_user

MESSAGES={'order.confirmed':'Your order is confirmed. Thank you for shopping with us!',
          'order.shipped':'Your order has shipped. Tracking is available in your orders.',
          'order.delivered':'Your order was delivered. You can now review your products.',
          'order.cancelled':'Your order was cancelled. Any eligible refund is being processed.',
          'refund.completed':'Your simulated refund is complete.',
          'return.updated':'Your return request has a new status.'}


async def events(event):
    p=event['payload'];kind=event['type']
    if kind not in MESSAGES and kind!='stock.low':
        return
    id=event['event_id']
    with db.tx() as c:
        # Unique event key makes writes idempotent even before inbox acknowledgement.
        if not db.get('notifications',id,c):
            db.put(c,'notifications',id,{'user_id':p.get('user_id','__staff__') if kind!='stock.low' else '__staff__',
                'type':kind,'title':kind.replace('.',' ').title(),
                'message':MESSAGES.get(kind,f"Stock alert: product {p.get('id')} has {p.get('available',0)} available."),
                'order_id':p.get('order_id',p.get('id')) if kind!='stock.low' else None,'read_by':[]})


app,db=make_app('notifications',events)


@app.get('/notifications')
def listing(user=Depends(current_user)):
    return [dict(n,read=user['sub'] in n['read_by']) for n in db.all('notifications') if n['user_id']==user['sub']]


@app.get('/notifications/admin/history')
def history(user=Depends(admin)):
    return [dict(n,read=user['sub'] in n['read_by']) for n in db.all('notifications')]


@app.patch('/notifications/{id}/read')
def read(id: str,user=Depends(current_user)):
    with db.tx() as c:
        n=db.get('notifications',id,c)
        if not n:
            raise HTTPException(404,'Notification not found')
        if n['user_id']!=user['sub']:
            # Staff alerts are marked by administrators through a separate endpoint.
            raise HTTPException(403,'Notification belongs to another user')
        n=db.put(c,'notifications',id,dict(n,read_by=list(set(n['read_by']+[user['sub']]))))
        return dict(n,read=True)


@app.patch('/notifications/admin/{id}/read')
def staff_read(id: str,user=Depends(admin)):
    with db.tx() as c:
        n=db.get('notifications',id,c)
        if not n:
            raise HTTPException(404,'Notification not found')
        return db.put(c,'notifications',id,dict(n,read_by=list(set(n['read_by']+[user['sub']]))))
