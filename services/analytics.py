import csv
import io
from datetime import datetime, timezone
from fastapi import Depends, Query
from fastapi.responses import Response
from common.runtime import make_app, call, admin


async def events(event):
    if event['type'].startswith('order.'):
        p=event['payload']
        with db.tx() as c:
            old=db.get('projections',p['id'],c)
            if not old or p.get('updated_at',0)>=old.get('updated_at',0):
                db.put(c,'projections',p['id'],p)


app,db=make_app('analytics',events)


async def data(start,end):
    # Source APIs are authoritative; projections support eventual analytics without
    # violating database ownership. Reports reconcile with current source state.
    orders=await call('orders','GET','/internal/orders')
    return [o for o in orders if (start is None or o['created_at']>=start) and (end is None or o['created_at']<=end)]


def paid_value(o):
    if o['status'] not in ['Confirmed','Processing','Shipped','Delivered']:
        return 0
    return o['total']-sum(i['paid_amount']*i['cancelled_quantity']//i['quantity'] for i in o['items'])


@app.get('/analytics/sales')
async def sales(start: float|None=None,end: float|None=None,period: str=Query('daily',pattern='^(daily|weekly|monthly)$'),user=Depends(admin)):
    rows=await data(start,end)
    returns=await call('returns','GET','/internal/returns')
    refunds={}
    for r in returns:
        if r['status']=='Refunded':
            refunds[r['order_id']]=refunds.get(r['order_id'],0)+r['refund_amount']
    series={}
    for o in rows:
        d=datetime.fromtimestamp(o['created_at'],timezone.utc)
        key=d.strftime({'daily':'%Y-%m-%d','weekly':'%G-W%V','monthly':'%Y-%m'}[period])
        series[key]=series.get(key,0)+max(0,paid_value(o)-refunds.get(o['id'],0))
    cancelled=sum(o['status']=='Cancelled' for o in rows)
    returned=len({r['order_id'] for r in returns if r['status']!='Rejected' and r['order_id'] in {o['id'] for o in rows}})
    return {'total_orders':len(rows),'revenue':sum(series.values()),'cancelled_orders':cancelled,'returned_orders':returned,
            'cancellation_rate':cancelled/len(rows) if rows else 0,'return_rate':returned/len(rows) if rows else 0,
            'series':[{'period':k,'revenue':v} for k,v in sorted(series.items())]}


@app.get('/analytics/orders')
async def orders(start: float|None=None,end: float|None=None,user=Depends(admin)):
    rows=await data(start,end)
    statuses={}
    for o in rows:
        statuses[o['status']]=statuses.get(o['status'],0)+1
    return {'total_orders':len(rows),'statuses':statuses}


@app.get('/analytics/inventory')
async def inventory(user=Depends(admin)):
    stocks=await call('inventory','GET','/internal/stock')
    return {'low_stock':[s for s in stocks.values() if s['available']<=s['threshold']],
            'out_of_stock':[s for s in stocks.values() if s['available']==0],'total_units':sum(s['quantity'] for s in stocks.values())}


@app.get('/analytics/top-products')
async def popular(start: float|None=None,end: float|None=None,user=Depends(admin)):
    rows=await data(start,end)
    returns=await call('returns','GET','/internal/returns')
    returned={}
    for r in returns:
        if r['status']=='Refunded':
            for i in r['items']:
                k=(r['order_id'],i['product_id'])
                returned[k]=returned.get(k,0)+i['quantity']
    products={};categories={}
    for o in rows:
        if not paid_value(o):
            continue
        for i in o['items']:
            units=max(0,i['quantity']-i['cancelled_quantity']-returned.get((o['id'],i['product_id']),0))
            p=products.setdefault(i['product_id'],{'product_id':i['product_id'],'name':i['name'],'units':0})
            p['units']+=units
            categories[i['category']]=categories.get(i['category'],0)+units
    return {'products':sorted(products.values(),key=lambda p:p['units'],reverse=True)[:10],
            'categories':[{'category':k,'units':v} for k,v in sorted(categories.items(),key=lambda kv:kv[1],reverse=True)]}


@app.get('/analytics/export')
async def export(start: float|None=None,end: float|None=None,user=Depends(admin)):
    rows=await data(start,end)
    buf=io.StringIO();writer=csv.writer(buf)
    writer.writerow(['order_number','date_utc','status','subtotal_paise','discount_paise','tax_paise','shipping_paise','total_paise','paid_less_cancellations_paise'])
    for o in rows:
        writer.writerow([o['number'],datetime.fromtimestamp(o['created_at'],timezone.utc).isoformat(),o['status'],o['subtotal'],o['discount'],o['tax'],o['shipping'],o['total'],paid_value(o)])
    return Response(buf.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=sales.csv'})
