from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from common.runtime import make_app, call
from common.security import current_user, internal

app,db=make_app('cart')


class CartItem(BaseModel):
    product_id: str=Field(min_length=1,max_length=100)
    quantity: int=Field(gt=0,le=10000,strict=True)


class Quantity(BaseModel):
    quantity: int=Field(gt=0,le=10000,strict=True)


async def validate(product_id,quantity):
    p=await call('products','GET',f'/internal/products/{product_id}')
    s=await call('inventory','GET',f'/internal/stock/{product_id}')
    if quantity>s['available']:
        raise HTTPException(409,'Requested quantity is unavailable')
    return dict(p,available=s['available'])


async def cart_for(user_id):
    rows=[i for i in db.all('cart_items') if i['user_id']==user_id]
    items=[]
    for row in rows:
        try:
            p=await call('products','GET',f"/internal/products/{row['product_id']}")
            s=await call('inventory','GET',f"/internal/stock/{row['product_id']}")
            items.append(dict(row,product=p,available=s['available'],line_total=p['price']*row['quantity']))
        except HTTPException as exc:
            if exc.status_code!=404:
                raise
            items.append(dict(row,product={'name':'Product removed','price':0,'image':'/placeholder.svg'},available=0,line_total=0))
    return {'items':items,'subtotal':sum(i['line_total'] for i in items)}


@app.get('/cart')
async def cart(user=Depends(current_user)):
    return await cart_for(user['sub'])


@app.post('/cart/items',status_code=201)
async def add(body: CartItem,user=Depends(current_user)):
    id=user['sub']+':'+body.product_id
    # Availability is advisory here; checkout reservation is authoritative.
    product=await validate(body.product_id,body.quantity)
    with db.tx() as c:
        prior=db.get('cart_items',id,c)
        quantity=body.quantity+(prior['quantity'] if prior else 0)
        if quantity>product['available']:
            raise HTTPException(409,'Requested combined quantity is unavailable')
        if quantity>10000:
            raise HTTPException(422,'Quantity exceeds limit')
        db.put(c,'carts',user['sub'],{'user_id':user['sub']})
        return db.put(c,'cart_items',id,{'user_id':user['sub'],'product_id':body.product_id,'quantity':quantity})


@app.patch('/cart/items/{id}')
async def update(id: str,body: Quantity,user=Depends(current_user)):
    r=db.get('cart_items',id)
    if not r or r['user_id']!=user['sub']:
        raise HTTPException(404,'Cart item not found')
    await validate(r['product_id'],body.quantity)
    with db.tx() as c:
        return db.put(c,'cart_items',id,dict(r,quantity=body.quantity))


@app.delete('/cart/items/{id}',status_code=204)
def remove(id: str,user=Depends(current_user)):
    with db.tx() as c:
        r=db.get('cart_items',id,c)
        if not r or r['user_id']!=user['sub']:
            raise HTTPException(404,'Cart item not found')
        db.delete(c,'cart_items',id)


class Wish(BaseModel):
    product_id: str=Field(min_length=1,max_length=100)


@app.get('/wishlist')
async def wishlist(user=Depends(current_user)):
    result=[]
    for r in db.all('wishlists'):
        if r['user_id']==user['sub']:
            try:
                p=await call('products','GET',f"/internal/products/{r['product_id']}")
                result.append(dict(r,product=p))
            except HTTPException as exc:
                if exc.status_code!=404:
                    raise
    return result


@app.post('/wishlist/items',status_code=201)
async def wish(body: Wish,user=Depends(current_user)):
    await call('products','GET',f'/internal/products/{body.product_id}')
    with db.tx() as c:
        return db.put(c,'wishlists',user['sub']+':'+body.product_id,{'user_id':user['sub'],'product_id':body.product_id})


@app.delete('/wishlist/items/{id}',status_code=204)
def unwish(id: str,user=Depends(current_user)):
    with db.tx() as c:
        r=db.get('wishlists',id,c)
        if not r or r['user_id']!=user['sub']:
            raise HTTPException(404,'Wishlist item not found')
        db.delete(c,'wishlists',id)


@app.get('/internal/cart/{user_id}',dependencies=[Depends(internal)])
async def internal_cart(user_id: str):
    return await cart_for(user_id)


class Clear(BaseModel):
    operation_id: str
    items: list[CartItem]


@app.post('/internal/cart/{user_id}/clear',dependencies=[Depends(internal)])
def clear(user_id: str,body: Clear):
    # Subtract purchased snapshot; items added after checkout remain in the cart.
    with db.tx() as c:
        if db.get('inbox','clear:'+body.operation_id,c):
            return {'cleared':True}
        db.put(c,'inbox','clear:'+body.operation_id,{'operation_id':body.operation_id})
        for item in body.items:
            id=user_id+':'+item.product_id
            r=db.get('cart_items',id,c)
            if r:
                left=r['quantity']-item.quantity
                if left>0:
                    db.put(c,'cart_items',id,dict(r,quantity=left))
                else:
                    db.delete(c,'cart_items',id)
    return {'cleared':True}
