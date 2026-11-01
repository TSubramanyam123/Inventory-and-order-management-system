from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from common.db import uid
from common.runtime import make_app, call, own, admin
from common.security import current_user, internal

app,db=make_app('reviews')


class Review(BaseModel):
    product_id: str
    order_id: str
    rating: int=Field(ge=1,le=5,strict=True)
    text: str=Field(min_length=3,max_length=3000)


class Edit(BaseModel):
    rating: int=Field(ge=1,le=5,strict=True)
    text: str=Field(min_length=3,max_length=3000)


@app.post('/reviews',status_code=201)
async def create(body: Review,user=Depends(current_user)):
    o=await call('orders','GET',f'/internal/orders/{body.order_id}')
    own(o,user)
    if o['status']!='Delivered' or not any(i['product_id']==body.product_id and i['quantity']>i['cancelled_quantity'] for i in o['items']):
        raise HTTPException(403,'Reviews require a delivered purchase of this product')
    with db.tx() as c:
        if any(r['product_id']==body.product_id and r['user_id']==user['sub'] for r in db.all('reviews',c)):
            raise HTTPException(409,'You have already reviewed this product')
        return db.put(c,'reviews',uid(),dict(body.model_dump(),user_id=user['sub'],name=user['name'],visible=True))


@app.get('/products/{product_id}/reviews')
def listing(product_id: str):
    reviews=[r for r in db.all('reviews') if r['product_id']==product_id and r['visible']]
    return {'items':reviews,'rating':round(sum(r['rating'] for r in reviews)/len(reviews),2) if reviews else 0,'count':len(reviews)}


@app.put('/reviews/{id}')
def edit(id: str,body: Edit,user=Depends(current_user)):
    with db.tx() as c:
        r=own(db.get('reviews',id,c),user)
        # Editing never restores a review hidden by a moderator.
        return db.put(c,'reviews',id,dict(r,**body.model_dump()))


@app.delete('/reviews/{id}',status_code=204)
def remove(id: str,user=Depends(current_user)):
    with db.tx() as c:
        own(db.get('reviews',id,c),user)
        db.delete(c,'reviews',id)


@app.get('/reviews/moderation')
def moderation(user=Depends(admin)):
    return db.all('reviews')


class Moderate(BaseModel):
    visible: bool


@app.patch('/reviews/{id}/moderate')
def moderate(id: str,body: Moderate,user=Depends(admin)):
    with db.tx() as c:
        r=db.get('reviews',id,c)
        if not r:
            raise HTTPException(404,'Review not found')
        db.audit(c,user['sub'],'review_moderated',id)
        return db.put(c,'reviews',id,dict(r,visible=body.visible))


@app.get('/internal/ratings',dependencies=[Depends(internal)])
def ratings():
    grouped={}
    for r in db.all('reviews'):
        if r['visible']:
            grouped.setdefault(r['product_id'],[]).append(r['rating'])
    return {id:{'rating':round(sum(v)/len(v),2),'review_count':len(v)} for id,v in grouped.items()}
