import hashlib
import os
import secrets
import time
from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from common.db import uid
from common.runtime import make_app, admin, limiter
from common.security import Credentials, Registration, current_user, hash_password, check_password, token, internal

app, db = make_app('auth')


def public(user):
    return {k:v for k,v in user.items() if k != 'password_hash'}


def issue(c, user, response):
    refresh = secrets.token_urlsafe(48)
    digest = hashlib.sha256(refresh.encode()).hexdigest()
    db.put(c, 'refresh_tokens', digest, {'digest':digest,'user_id':user['id'],
        'expires_at':time.time()+int(os.getenv('REFRESH_TOKEN_SECONDS','604800')),'revoked':False})
    response.set_cookie('refresh_token', refresh, httponly=True, secure=os.getenv('COOKIE_SECURE','false')=='true',
                        samesite='lax', max_age=int(os.getenv('REFRESH_TOKEN_SECONDS','604800')), path='/')
    return {'access_token':token(user),'token_type':'bearer','user':public(user)}


@app.post('/auth/register', status_code=201)
def register(body: Registration):
    with db.tx() as c:
        email = body.email.lower().strip()
        if any(u['email']==email for u in db.all('users',c)):
            raise HTTPException(409,'Email already registered')
        user = db.put(c,'users',uid(), {'email':email,'name':body.name.strip(),'role':'Customer',
                                      'password_hash':hash_password(body.password)})
        db.audit(c,user['id'],'registered',user['id'])
        return public(user)


@app.post('/auth/login')
async def login(body: Credentials, request: Request, response: Response):
    await limiter.check('login:'+request.client.host,10)
    await limiter.check('account:'+body.email.lower(),10)
    user = next((u for u in db.all('users') if u['email']==body.email.lower().strip()),None)
    if not user or not check_password(body.password,user['password_hash']):
        raise HTTPException(401,'Incorrect email or password')
    with db.tx() as c:
        db.audit(c,user['id'],'login',user['id'])
        return issue(c,user,response)


@app.post('/auth/refresh')
def refresh(request: Request, response: Response):
    raw = request.cookies.get('refresh_token','')
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with db.tx() as c:
        r = db.get('refresh_tokens',digest,c)
        if not r or r['revoked'] or r['expires_at'] < time.time():
            raise HTTPException(401,'Refresh token expired or revoked')
        db.put(c,'refresh_tokens',digest,dict(r,revoked=True))
        return issue(c,db.get('users',r['user_id'],c),response)


@app.post('/auth/logout')
def logout(request: Request,response: Response):
    digest = hashlib.sha256(request.cookies.get('refresh_token','').encode()).hexdigest()
    with db.tx() as c:
        r = db.get('refresh_tokens',digest,c)
        if r:
            db.put(c,'refresh_tokens',digest,dict(r,revoked=True))
    response.delete_cookie('refresh_token',path='/')
    return {'message':'Signed out'}


@app.get('/auth/me')
def me(user=Depends(current_user)):
    record = db.get('users',user['sub'])
    if not record:
        raise HTTPException(401,'Account no longer exists')
    return public(record)


class Profile(BaseModel):
    name: str = Field(min_length=2,max_length=100)


@app.patch('/auth/me')
def profile(body: Profile,user=Depends(current_user)):
    with db.tx() as c:
        return public(db.put(c,'users',user['sub'],dict(db.get('users',user['sub'],c),name=body.name)))


class Password(BaseModel):
    current_password: str = Field(min_length=8,max_length=128)
    new_password: str = Field(min_length=8,max_length=128)


@app.post('/auth/password')
def password(body: Password,user=Depends(current_user)):
    with db.tx() as c:
        row = db.get('users',user['sub'],c)
        if not check_password(body.current_password,row['password_hash']):
            raise HTTPException(400,'Current password incorrect')
        db.put(c,'users',row['id'],dict(row,password_hash=hash_password(body.new_password)))
        for r in db.all('refresh_tokens',c):
            if r['user_id']==row['id']:
                db.put(c,'refresh_tokens',r['id'],dict(r,revoked=True))
        db.audit(c,row['id'],'password_changed',row['id'])
    return {'message':'Password changed; sign in again'}


@app.get('/auth/users')
def users(user=Depends(admin)):
    return [public(u) for u in db.all('users')]


class Role(BaseModel):
    role: str = Field(pattern='^(Customer|Administrator|Inventory Manager)$')


@app.patch('/auth/users/{id}/role')
def role(id: str,body: Role,user=Depends(admin)):
    with db.tx() as c:
        record = db.get('users',id,c)
        if not record:
            raise HTTPException(404,'User not found')
        if id==user['sub']:
            raise HTTPException(400,'Cannot change your own administrative role')
        result = db.put(c,'users',id,dict(record,role=body.role))
        db.audit(c,user['sub'],'role_changed',id)
        return public(result)


@app.get('/internal/users/{id}',dependencies=[Depends(internal)])
def internal_user(id: str):
    u = db.get('users',id)
    if not u:
        raise HTTPException(404,'User not found')
    return public(u)
