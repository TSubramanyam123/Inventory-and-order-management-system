import asyncio
import json
import os
import re
import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from common.runtime import SERVICES, base_url, limiter
from common.security import decode

TRANSPORT=None

app=FastAPI(title='Inventory & Order Management · API Gateway',version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000').split(','),
                  allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'],
                  allow_headers=['Authorization','Content-Type','Idempotency-Key','X-Correlation-ID'],
                  expose_headers=['X-Correlation-ID','Content-Disposition'])


def route(path):
    first=path.strip('/').split('/')[0]
    if re.fullmatch(r'/products/[^/]+/reviews',path):
        return 'reviews'
    return {'auth':'auth','products':'products','inventory':'inventory','cart':'cart','wishlist':'cart',
            'orders':'orders','payments':'payments','notifications':'notifications','reviews':'reviews',
            'coupons':'coupons','returns':'returns','analytics':'analytics'}.get(first)


def public(path,method):
    return path in ['/auth/register','/auth/login','/auth/refresh','/auth/logout'] or (
        method=='GET' and path.startswith('/products') and path!='/products/recently-viewed')


@app.get('/health')
def health():
    return {'status':'ok','service':'gateway'}


@app.get('/health/dependencies')
async def dependencies():
    async with httpx.AsyncClient(trust_env=False,transport=TRANSPORT,timeout=3) as client:
        async def check(name):
            try:
                r=await client.get(base_url(name)+'/health')
                return name,r.status_code==200
            except httpx.RequestError:
                return name,False
        result=dict(await asyncio.gather(*(check(n) for n in SERVICES)))
    return JSONResponse({'services':result},status_code=200 if all(result.values()) else 503)


@app.get('/api/openapi.json',include_in_schema=False)
async def openapi():
    result={'openapi':'3.1.0','info':{'title':app.title,'version':'1.0.0'},'paths':{},'components':{'schemas':{},'securitySchemes':{'BearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'JWT'}}}}
    async with httpx.AsyncClient(trust_env=False,transport=TRANSPORT,timeout=5) as client:
        for name in SERVICES:
            try:
                doc=(await client.get(base_url(name)+'/openapi.json')).json()
            except (httpx.RequestError,ValueError):
                raise HTTPException(503,f'{name} OpenAPI unavailable')
            # Namespace schema refs to avoid collisions between service model names.
            text=json.dumps(doc)
            for schema in doc.get('components',{}).get('schemas',{}):
                text=text.replace('#/components/schemas/'+schema+'"','#/components/schemas/'+name+'_'+schema+'"')
            doc=json.loads(text)
            for schema,value in doc.get('components',{}).get('schemas',{}).items():
                result['components']['schemas'][name+'_'+schema]=value
            for path,methods in doc['paths'].items():
                if path.startswith('/internal') or path=='/health':
                    continue
                for method,operation in methods.items():
                    if isinstance(operation,dict):
                        operation['tags']=[name]
                        if not public(path,method.upper()):
                            operation['security']=[{'BearerAuth':[]}]
                result['paths'][path]=methods
    return result


@app.get('/api/docs',include_in_schema=False)
def docs():
    from fastapi.openapi.docs import get_swagger_ui_html
    return get_swagger_ui_html(openapi_url='/api/openapi.json',title=app.title)


@app.api_route('/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE'])
async def proxy(path: str,request: Request):
    path='/'+path
    service=route(path)
    cid=request.headers.get('X-Correlation-ID','')[:128] or str(uuid.uuid4())
    def error(code,message):
        return JSONResponse({'error':{'code':code,'message':message},'detail':message,'correlation_id':cid},status_code=code,headers={'X-Correlation-ID':cid})
    if not service:
        return error(404,'Route not found')
    try:
        await limiter.check('gateway:'+request.client.host,int(os.getenv('RATE_LIMIT_PER_MINUTE','240')))
        if not public(path,request.method):
            auth=request.headers.get('Authorization','')
            if not auth.startswith('Bearer '):
                return error(401,'Authentication required')
            decode(auth[7:])
    except HTTPException as exc:
        return error(exc.status_code,exc.detail)
    body=await request.body()
    if len(body)>2_100_000:
        return error(413,'Request too large')
    headers={k:v for k,v in request.headers.items() if k.lower() in ['authorization','content-type','idempotency-key','cookie']}
    headers['X-Correlation-ID']=cid
    try:
        async with httpx.AsyncClient(trust_env=False,transport=TRANSPORT,timeout=float(os.getenv('SERVICE_TIMEOUT_SECONDS','12')),follow_redirects=False) as client:
            upstream=await client.request(request.method,base_url(service)+path,params=request.query_params,content=body,headers=headers)
    except httpx.TimeoutException:
        return error(504,'Service timed out; retry with the same Idempotency-Key')
    except httpx.RequestError:
        return error(503,f'{service} service unavailable')
    keep={k:v for k,v in upstream.headers.items() if k.lower() in ['content-type','content-disposition','set-cookie']}
    keep['X-Correlation-ID']=cid
    return Response(upstream.content,status_code=upstream.status_code,headers=keep)
