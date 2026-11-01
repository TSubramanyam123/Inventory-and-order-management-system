"""Generate a reproducible ordered Postman workflow with success/failure assertions."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
items=[]
def req(name,method,path,body=None,status=200,role='customer',save=None,script=None):
    r={'method':method,'header':[],'url':'{{base_url}}'+path}
    if role:r['auth']={'type':'bearer','bearer':[{'key':'token','value':'{{'+role+'_token}}','type':'string'}]}
    else:r['auth']={'type':'noauth'}
    if body is not None:
        r['header'].append({'key':'Content-Type','value':'application/json'})
        r['body']={'mode':'raw','raw':json.dumps(body,indent=2)}
    if method=='POST' and path in ['/orders','/payments','/returns']:
        variable={'/orders':'checkout','/payments':'payment','/returns':'return'}[path]
        r['header'].append({'key':'Idempotency-Key','value':'{{run_id}}-'+variable})
    tests=[f"pm.test('HTTP {status}', () => pm.response.to.have.status({status}));"]
    if save:tests.append(f"if (pm.response.code < 300) pm.collectionVariables.set('{save}', pm.response.json().{ 'access_token' if save.endswith('_token') else 'id' });")
    if script:tests.extend(script.splitlines())
    item={'name':name,'request':r,'event':[{'listen':'test','script':{'type':'text/javascript','exec':tests}}]}
    items.append(item)

req('01 Admin login','POST','/auth/login',{'email':'{{admin_email}}','password':'{{admin_password}}'},role=None,save='admin_token')
items[-1]['event'].insert(0,{'listen':'prerequest','script':{'type':'text/javascript','exec':["pm.collectionVariables.set('run_id', Date.now().toString());","pm.collectionVariables.set('expiry', Math.floor(Date.now()/1000)+86400);","pm.collectionVariables.set('polls', '0');"]}})
req('02 Create product','POST','/products',{'name':'Runner Camera','description':'Integration-test travel camera','category':'Photography','brand':'Northstar','price':10000,'specifications':{'Sensor':'24 MP'}},201,'admin','product_id')
req('03 Create comparison product','POST','/products',{'name':'Runner Tripod','description':'Integration-test lightweight tripod','category':'Photography','brand':'Northstar','price':5000},201,'admin','second_product_id')
req('04 Add stock','PATCH','/inventory/{{product_id}}/stock',{'delta':10,'reason':'Postman initial stock','threshold':2},role='admin')
req('05 Inventory list','GET','/inventory',role='admin')
req('06 Inventory product','GET','/inventory/{{product_id}}',role='admin')
req('07 Inventory history','GET','/inventory/{{product_id}}/transactions',role='admin')
req('08 Create coupon','POST','/coupons',{'code':'RUN{{run_id}}','kind':'percentage','value':10,'expires_at':'{{expiry}}','usage_limit':2,'minimum_purchase':10000},201,'admin')
req('09 Register customer','POST','/auth/register',{'name':'Postman Customer','email':'runner{{run_id}}@example.com','password':'RunnerStrong123!'},201,None)
req('10 Customer login','POST','/auth/login',{'email':'runner{{run_id}}@example.com','password':'RunnerStrong123!'},role=None,save='customer_token')
req('11 Current user','GET','/auth/me')
req('12 Refresh access cookie','POST','/auth/refresh',role=None,save='customer_token')
req('13 Catalog search filters','GET','/products?q=Runner&sort=price_asc&page=1&page_size=10&in_stock=true',role=None)
req('14 Product detail','GET','/products/{{product_id}}',role=None)
req('15 Product comparison','GET','/products/compare?ids={{product_id}},{{second_product_id}}',role=None)
req('16 Recently viewed','POST','/products/{{product_id}}/view')
req('17 Add to wishlist','POST','/wishlist/items',{'product_id':'{{product_id}}'},201,save='wishlist_id')
req('18 Wishlist','GET','/wishlist')
req('19 Add cart item','POST','/cart/items',{'product_id':'{{product_id}}','quantity':2},201,save='cart_item_id')
req('20 Update cart item','PATCH','/cart/items/{{cart_item_id}}',{'quantity':3})
req('21 Cart totals','GET','/cart')
req('22 Validate coupon','POST','/coupons/validate',{'code':'RUN{{run_id}}','subtotal':30000})
req('23 Create order','POST','/orders',{'address':'Postman Customer, 123 Example Road, Hyderabad 500001','coupon':'RUN{{run_id}}'},201,save='order_id')
req('24 Retry identical checkout','POST','/orders',{'address':'Postman Customer, 123 Example Road, Hyderabad 500001','coupon':'RUN{{run_id}}'},201,script="pm.test('Same order on retry',()=>pm.expect(pm.response.json().id).to.eql(pm.collectionVariables.get('order_id')));")
req('25 Simulate successful payment','POST','/payments',{'order_id':'{{order_id}}','outcome':'success'},201,save='payment_id')
req('26 Wait for confirmation','GET','/orders/{{order_id}}',script="""const d=pm.response.json();
let count=Number(pm.collectionVariables.get('polls')||0)+1;
pm.collectionVariables.set('polls',count.toString());
if(d.status!=='Confirmed' && count<30) pm.execution.setNextRequest(pm.info.requestName);
else pm.test('Order confirmed asynchronously',()=>pm.expect(d.status).to.eql('Confirmed'));""")
req('27 Payment detail','GET','/payments/{{payment_id}}')
req('28 Order history','GET','/orders/my-orders')
req('29 Admin order list','GET','/orders',role='admin')
for n,status in enumerate(['Processing','Shipped','Delivered'],30):
    req(f'{n} Mark {status}','PATCH','/orders/{{order_id}}/status',{'status':status,'tracking_number':'POSTMAN-TRACK'},role='admin')
req('33 Create verified review','POST','/reviews',{'product_id':'{{product_id}}','order_id':'{{order_id}}','rating':5,'text':'Excellent verified travel camera.'},201,save='review_id')
req('34 Edit own review','PUT','/reviews/{{review_id}}',{'rating':4,'text':'Updated verified camera review.'})
req('35 Product reviews','GET','/products/{{product_id}}/reviews',role=None)
req('36 Moderate review','PATCH','/reviews/{{review_id}}/moderate',{'visible':False},role='admin')
req('37 Submit return','POST','/returns',{'order_id':'{{order_id}}','reason':'Wrong colour received','items':[{'product_id':'{{product_id}}','quantity':1}]},201,save='return_id')
req('38 My returns','GET','/returns/my-returns')
req('39 Return detail','GET','/returns/{{return_id}}')
req('40 Approve return','PATCH','/returns/{{return_id}}/status',{'status':'Approved','note':'Return label issued'},role='admin')
req('41 Physically accept and refund','PATCH','/returns/{{return_id}}/status',{'status':'Accepted','note':'Item physically received and inspected'},role='admin',script="pm.test('Refund completed',()=>pm.expect(pm.response.json().status).to.eql('Refunded'));")
req('42 Notifications','GET','/notifications',script="const a=pm.response.json(); if(a.length) pm.collectionVariables.set('notification_id',a[0].id);")
req('43 Mark notification read','PATCH','/notifications/{{notification_id}}/read')
for name,path in [('Sales','sales'),('Orders','orders'),('Inventory','inventory'),('Popular products','top-products'),('Download CSV','export')]:
    req('Report: '+name,'GET','/analytics/'+path,role='admin')
req('44 Coupons list','GET','/coupons',role='admin')
req('45 User management list','GET','/auth/users',role='admin')
req('46 Review moderation list','GET','/reviews/moderation',role='admin')
req('47 Admin notification history','GET','/notifications/admin/history',role='admin')
req('48 Invalid quantity rejected','POST','/cart/items',{'product_id':'{{product_id}}','quantity':0},422)
req('49 Customer cannot manage inventory','PATCH','/inventory/{{product_id}}/stock',{'delta':1,'reason':'Unauthorised change'},403)
req('50 Invalid coupon rejected','POST','/coupons/validate',{'code':'DOES_NOT_EXIST','subtotal':10000},400)
req('51 Repeated coupon redemption rejected','POST','/coupons/validate',{'code':'RUN{{run_id}}','subtotal':10000},409)
req('52 Cannot cancel delivered order','POST','/orders/{{order_id}}/cancel',{'reason':'Too late to cancel'},409)
req('53 No token on private endpoint','GET','/orders/my-orders',status=401,role=None)
req('54 Invalid login rejected','POST','/auth/login',{'email':'runner{{run_id}}@example.com','password':'WrongPass123!'},401,None)
req('55 Card credentials rejected','POST','/payments',{'order_id':'{{order_id}}','card_number':'4242'},422)
req('56 Delete own review','DELETE','/reviews/{{review_id}}',status=204)
req('57 Remove wishlist item','DELETE','/wishlist/items/{{wishlist_id}}',status=204)
req('58 Logout','POST','/auth/logout',role=None)
collection={'info':{'name':'Northstar · Complete workflow and failure cases','schema':'https://schema.getpostman.com/json/collection/v2.1.0/collection.json','description':'Run all requests in order, one iteration, 500 ms delay. Seed demo accounts first. Set admin_email/admin_password in environment. Internal reservation APIs are restricted to service credentials and covered by Pytest.'},'variable':[{'key':'run_id','value':''}], 'item':items}
(root/'postman/Inventory.postman_collection.json').write_text(json.dumps(collection,indent=2))
env={'name':'Northstar Local','values':[{'key':k,'value':v,'enabled':True,'type':'secret' if 'password' in k else 'default'} for k,v in [('base_url','http://localhost:8000'),('admin_email','admin@example.com'),('admin_password','COPY_ADMIN_PASSWORD_FROM_YOUR_ENV')]],'_postman_variable_scope':'environment'}
(root/'postman/Local.postman_environment.json').write_text(json.dumps(env,indent=2))
print(f'Generated {len(items)} ordered requests.')
