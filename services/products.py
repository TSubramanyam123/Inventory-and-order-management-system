import csv
import io
import json
from fastapi import Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field, ConfigDict
from common.db import uid
from common.runtime import make_app, staff, call, limiter
from common.security import current_user, internal

app, db = make_app('products')


class Product(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2,max_length=150)
    description: str = Field(min_length=5,max_length=5000)
    category: str = Field(min_length=2,max_length=100)
    brand: str = Field(min_length=1,max_length=100)
    price: int = Field(gt=0,le=100000000,strict=True,description='Price in paise (INR × 100)')
    image: str = Field(default='/placeholder.svg',max_length=2000,pattern=r'^(https://|/)[^\s]*$')
    specifications: dict[str,str] = Field(default_factory=dict)


async def changed(c,p,kind='product.updated'):
    db.put(c,'categories',p['category'].casefold(),{'name':p['category']})
    db.emit(c,kind,p)
    try:
        r = await limiter.client()
        await r.incr('catalog:version')
    except Exception:
        pass  # Short TTL also bounds staleness if cache invalidation is unavailable.


@app.post('/products/bulk-import',status_code=201)
async def bulk(file: UploadFile=File(...),user=Depends(staff)):
    raw = await file.read(2_000_001)
    if len(raw)>2_000_000:
        raise HTTPException(413,'CSV exceeds 2 MB')
    try:
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        if not rows or len(rows)>1000:
            raise ValueError('Provide between 1 and 1000 products')
        products=[]
        for row in rows:
            row['price']=int(row['price'])
            if row.get('specifications'):
                row['specifications']=json.loads(row['specifications'])
            elif 'specifications' in row:
                del row['specifications']
            products.append(Product(**row))
    except Exception as e:
        raise HTTPException(422,f'Invalid CSV: {str(e)[:300]}')
    with db.tx() as c:
        result=[]
        for item in products:
            p=db.put(c,'products',uid(),dict(item.model_dump(),active=True))
            await changed(c,p,'product.created')
            result.append(p)
        db.audit(c,user['sub'],'bulk_import',len(result))
    return {'imported':len(result),'products':result}


@app.get('/products/compare')
async def compare(ids: str=Query(max_length=300)):
    selected=list(dict.fromkeys(ids.split(',')))
    if not 2<=len(selected)<=4:
        raise HTTPException(422,'Compare between 2 and 4 products')
    return [await detail(id) for id in selected]


@app.get('/products/recently-viewed')
async def recent(user=Depends(current_user)):
    r=db.get('recent_views',user['sub']) or {'products':[]}
    return [p for id in r['products'] if (p:=db.get('products',id)) and p.get('active')]


@app.get('/products/categories')
def categories():
    return sorted({p['category'] for p in db.all('products') if p['active']})


@app.post('/products',status_code=201)
async def create(body: Product,user=Depends(staff)):
    with db.tx() as c:
        p=db.put(c,'products',uid(),dict(body.model_dump(),active=True))
        await changed(c,p,'product.created')
        db.audit(c,user['sub'],'product_created',p['id'])
        return p


@app.get('/products')
async def catalog(q: str=Query('',max_length=200),category: str='',brand: str='',
                  min_price: int=Query(0,ge=0),max_price: int=Query(100000000,ge=0),
                  min_rating: float=Query(0,ge=0,le=5),in_stock: bool=False,
                  sort: str=Query('newest',pattern='^(newest|price_asc|price_desc|name|rating)$'),
                  page: int=Query(1,ge=1),page_size: int=Query(12,ge=1,le=100)):
    cache=None
    # Cache ONLY local catalog documents; stock and reviews are fetched live.
    try:
        cache=await limiter.client()
        version=await cache.get('catalog:version') or b'0'
        key=f'catalog:all:{version.decode()}'
        raw=await cache.get(key)
        rows=json.loads(raw) if raw else db.all('products')
        if not raw:
            await cache.set(key,json.dumps(rows),ex=15)
    except Exception:
        rows=db.all('products')
    inventory=await call('inventory','GET','/internal/stock')
    ratings=await call('reviews','GET','/internal/ratings')
    items=[]
    for p in rows:
        if not p['active'] or (q and q.casefold() not in (p['name']+' '+p['description']+' '+p['brand']).casefold()):
            continue
        p=dict(p,**ratings.get(p['id'],{'rating':0,'review_count':0}),available=inventory.get(p['id'],{}).get('available',0))
        if (category and p['category']!=category) or (brand and p['brand']!=brand) or not min_price<=p['price']<=max_price or p['rating']<min_rating or (in_stock and p['available']<1):
            continue
        items.append(p)
    field={'price_asc':'price','price_desc':'price','name':'name','rating':'rating','newest':'created_at'}[sort]
    items.sort(key=lambda p:p[field],reverse=sort in ['price_desc','rating','newest'])
    return {'items':items[(page-1)*page_size:page*page_size],'total':len(items),'page':page,'page_size':page_size}


@app.get('/products/{id}')
async def detail(id: str):
    p=db.get('products',id)
    if not p or not p['active']:
        raise HTTPException(404,'Product not found')
    stock=await call('inventory','GET',f'/internal/stock/{id}')
    ratings=await call('reviews','GET','/internal/ratings')
    return dict(p,available=stock['available'],**ratings.get(id,{'rating':0,'review_count':0}))


@app.post('/products/{id}/view')
def view(id: str,user=Depends(current_user)):
    if not db.get('products',id):
        raise HTTPException(404,'Product not found')
    with db.tx() as c:
        r=db.get('recent_views',user['sub'],c) or {'products':[]}
        return db.put(c,'recent_views',user['sub'],{'products':([id]+[x for x in r['products'] if x!=id])[:12]})


@app.put('/products/{id}')
async def update(id: str,body: Product,user=Depends(staff)):
    with db.tx() as c:
        existing=db.get('products',id,c)
        if not existing:
            raise HTTPException(404,'Product not found')
        p=db.put(c,'products',id,dict(existing,**body.model_dump()))
        await changed(c,p)
        db.audit(c,user['sub'],'product_updated',id)
        return p


@app.delete('/products/{id}',status_code=204)
async def delete(id: str,user=Depends(staff)):
    with db.tx() as c:
        p=db.get('products',id,c)
        if not p:
            raise HTTPException(404,'Product not found')
        p=db.put(c,'products',id,dict(p,active=False))
        await changed(c,p,'product.deleted')
        db.audit(c,user['sub'],'product_deleted',id)


@app.get('/internal/products/{id}',dependencies=[Depends(internal)])
def internal_product(id: str):
    p=db.get('products',id)
    if not p or not p['active']:
        raise HTTPException(404,'Product not found')
    return p
