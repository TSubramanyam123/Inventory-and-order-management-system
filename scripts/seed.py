"""Provision demo users in auth's own process, then seed products/stock via APIs.
Safe to rerun. Never opens another service's database from a service process.
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));load_dotenv(root/'.env')
from common.db import Store,uid
from common.security import hash_password


def provision_users():
    db=Store('auth')
    with db.tx() as c:
        for prefix,role,name in [('ADMIN','Administrator','Demo Administrator'),('MANAGER','Inventory Manager','Inventory Manager'),('CUSTOMER','Customer','Demo Customer')]:
            email=os.getenv(prefix+'_EMAIL','').lower();password=os.getenv(prefix+'_PASSWORD','')
            if not email or len(password)<8:
                raise SystemExit('Run python scripts/setup_env.py first; demo passwords must have at least 8 characters')
            if not any(u['email']==email for u in db.all('users',c)):
                db.put(c,'users',uid(),{'email':email,'name':name,'role':role,'password_hash':hash_password(password)})
    print('Demo accounts ready; read credentials from your .env file.')


async def main():
    import httpx
    if '--api-only' not in sys.argv:
        provision_users()
    async with httpx.AsyncClient(trust_env=False,base_url='http://127.0.0.1:8000',timeout=30) as client:
        r=await client.post('/auth/login',json={'email':os.environ['ADMIN_EMAIL'],'password':os.environ['ADMIN_PASSWORD']});r.raise_for_status()
        headers={'Authorization':'Bearer '+r.json()['access_token']}
        existing=await client.get('/products',params={'page_size':100});existing.raise_for_status()
        if existing.json()['total']:
            print('Catalog already contains products; skipping catalog seed.');return
        samples=[('Studio Headphones','Audio',899900,'SoundArc','Warm sound, comfortable listening, and 40 hours of battery life.'),
                 ('Everyday Backpack','Travel',249900,'Fieldwork','A durable everyday companion with a padded laptop compartment.'),
                 ('Compact Camera','Photography',4299900,'Vista','Capture travel stories with a lightweight 24-megapixel camera.'),
                 ('Desk Lamp','Workspace',179900,'Forma','Adjustable warm light with a minimal aluminium design.'),
                 ('Trail Bottle','Travel',89900,'Fieldwork','A 750 ml insulated stainless steel bottle for every adventure.'),
                 ('Wireless Keyboard','Workspace',349900,'Forma','Quiet mechanical keys and a compact wireless layout.'),
                 ('Portable Speaker','Audio',499900,'SoundArc','Rich portable sound in a weather-resistant enclosure.'),
                 ('Travel Tripod','Photography',599900,'Vista','Stable shots from a compact, lightweight travel tripod.')]
        for n,(name,category,price,brand,desc) in enumerate(samples):
            p=await client.post('/products',headers=headers,json={'name':name,'description':desc,'category':category,'brand':brand,'price':price,'image':f'/assets/product-{n}.svg','specifications':{'Warranty':'1 year','Brand':brand,'Category':category}});p.raise_for_status()
            r=await client.patch('/inventory/'+p.json()['id']+'/stock',headers=headers,json={'delta':20 if n!=4 else 4,'reason':'Initial demo stock','threshold':5});r.raise_for_status()
        r=await client.post('/coupons',headers=headers,json={'code':'WELCOME10','kind':'percentage','value':10,'expires_at':time.time()+365*86400,'usage_limit':1000,'minimum_purchase':10000});r.raise_for_status()
        print('Created eight products and WELCOME10 coupon.')


if __name__=='__main__':
    if '--users-only' in sys.argv:
        provision_users()
    else:
        asyncio.run(main())
