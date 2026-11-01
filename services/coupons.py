import time
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from common.runtime import make_app, admin
from common.security import current_user, internal

app,db=make_app('coupons')


class Coupon(BaseModel):
    code: str=Field(min_length=3,max_length=30,pattern=r'^[A-Za-z0-9_-]+$')
    kind: str=Field(pattern='^(percentage|fixed)$')
    value: int=Field(gt=0,le=10000000,strict=True)
    expires_at: float=Field(gt=0,allow_inf_nan=False,description='UTC Unix timestamp')
    usage_limit: int=Field(default=100,gt=0,le=1000000)
    minimum_purchase: int=Field(default=0,ge=0,strict=True)
    active: bool=True

    @model_validator(mode='after')
    def percentage(self):
        if self.kind=='percentage' and self.value>100:
            raise ValueError('Percentage must be 1 to 100')
        return self


class Validate(BaseModel):
    code: str=Field(min_length=3,max_length=30)
    subtotal: int=Field(gt=0,strict=True)


class Redeem(Validate):
    user_id: str
    order_id: str


def validate_coupon(code,subtotal,user_id,c=None,order_id=None):
    coupon=db.get('coupons',code.upper(),c)
    if not coupon or not coupon['active']:
        raise HTTPException(400,'Invalid coupon')
    redemptions=[r for r in db.all('redemptions',c) if r['code']==code.upper() and r['status']!='released' and r['order_id']!=order_id]
    if coupon['expires_at']<=time.time():
        raise HTTPException(400,'Coupon has expired')
    if len(redemptions)>=coupon['usage_limit']:
        raise HTTPException(409,'Coupon usage limit reached')
    if any(r['user_id']==user_id for r in redemptions):
        raise HTTPException(409,'You have already used this coupon')
    if subtotal<coupon['minimum_purchase']:
        raise HTTPException(400,'Minimum purchase requirement not met')
    discount=min(subtotal,subtotal*coupon['value']//100 if coupon['kind']=='percentage' else coupon['value'])
    return {'code':code.upper(),'discount':discount}


@app.post('/coupons',status_code=201)
def create(body: Coupon,user=Depends(admin)):
    with db.tx() as c:
        id=body.code.upper()
        if db.get('coupons',id,c):
            raise HTTPException(409,'Coupon code already exists')
        if body.expires_at<=time.time():
            raise HTTPException(422,'Expiry must be in the future')
        db.audit(c,user['sub'],'coupon_created',id)
        return db.put(c,'coupons',id,dict(body.model_dump(),code=id))


@app.get('/coupons')
def listing(user=Depends(admin)):
    return db.all('coupons')


@app.put('/coupons/{code}')
def update(code: str,body: Coupon,user=Depends(admin)):
    if code.upper()!=body.code.upper():
        raise HTTPException(422,'Coupon code cannot be renamed')
    with db.tx() as c:
        prior=db.get('coupons',code.upper(),c)
        if not prior:
            raise HTTPException(404,'Coupon not found')
        db.audit(c,user['sub'],'coupon_updated',code)
        return db.put(c,'coupons',code.upper(),dict(prior,**body.model_dump()))


@app.post('/coupons/validate')
def validate(body: Validate,user=Depends(current_user)):
    return validate_coupon(body.code,body.subtotal,user['sub'])


@app.post('/internal/redeem',dependencies=[Depends(internal)])
def redeem(body: Redeem):
    with db.tx() as c:
        prior=db.get('redemptions',body.order_id,c)
        if prior:
            if prior['code']!=body.code.upper() or prior['user_id']!=body.user_id or prior['subtotal']!=body.subtotal:
                raise HTTPException(409,'Coupon operation key conflict')
            if prior['status']=='released':
                raise HTTPException(409,'Coupon reservation was released')
            return prior
        result=validate_coupon(body.code,body.subtotal,body.user_id,c,body.order_id)
        return db.put(c,'redemptions',body.order_id,dict(result,user_id=body.user_id,order_id=body.order_id,subtotal=body.subtotal,status='redeemed'))


@app.post('/internal/redemptions/{order_id}/release',dependencies=[Depends(internal)])
def release(order_id: str):
    with db.tx() as c:
        r=db.get('redemptions',order_id,c)
        if r:
            db.put(c,'redemptions',order_id,dict(r,status='released'))
    return {'released':True}
