import asyncio
import copy
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from backend.app.config import Settings
from backend.app.domain import nutrition, target_for, validate_plan
from backend.app.main import create_app
from backend.app.recognition import clean_image, recognize
from backend.app.store import digest, packed

KEY = "test-development-key-not-real"
TARGET = dict(kcal_min=100, kcal_max=2000, protein_min=1, protein_max=200,
              carbs_min=1, carbs_max=400, fat_min=1, fat_max=150)


class FixtureProvider:
    """Test-only deterministic provider. Never import this module in application code."""
    def __init__(self):
        self.calls = []
        self.bad = False

    async def complete(self, role, system, data, **kwargs):
        self.calls.append((role, system, data))
        if role == "recognition":
            return {"items": [{"ingredient_id": "tomato", "name": "Tomato", "grams": None,
                               "confidence": .5, "reference_ratio": 2, "reference_grams": 50}], "paid_cents": None}
        if "required_json_schema" in data:
            req = data["context"]["request"]
            start = date.fromisoformat(req["start_date"])
            days = [{"date": (start+timedelta(days=n)).isoformat(), "dishes": [{"name": "Test-only rice meal", "ingredients": [
                {"ingredient_id": "rice", "grams": 100}, {"ingredient_id": "chicken_breast", "grams": 150},
                {"ingredient_id": "carrot", "grams": 100}, {"ingredient_id": "olive_oil", "grams": 10}],
                "steps": ["Cook the listed ingredients thoroughly."], "suitable_for": []}]} for n in range(req["days"])]
            result = {"variants": [{"mode": mode, "title": "Test fixture " + mode, "tradeoffs": ["Fixture only"], "days": copy.deepcopy(days)} for mode in ("balanced", "health")]}
            if self.bad:
                result["variants"][0]["days"][0]["dishes"][0]["ingredients"][0]["ingredient_id"] = "made_up_food"
            return result
        return {"notes": ["Test fixture advice"]}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.provider = FixtureProvider()
        self.settings = Settings(db_path=str(Path(self.tmp.name)/"test.sqlite3"), allow_dev_login=True, dev_key=KEY, worker_enabled=False)
        self.app = create_app(self.settings, self.provider)
        self.client = TestClient(self.app)
        self.client.__enter__()
        r = self.client.post('/api/auth/dev', json={"name": "Alice", "key": KEY})
        self.assertEqual(r.status_code, 200, r.text)
        self.user = r.json()["user_id"]
        self.headers = {"Authorization": "Bearer " + r.json()["token"]}
        r = self.req('POST', '/groups', {"name": "Test dorm"})
        self.group, self.invite = r.json()["id"], r.json()["invite_code"]
        self.g = '/groups/' + self.group
        self.req('PUT', '/me/profile', {"meal_target": TARGET})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def req(self, method, path, data=None, headers=None):
        return self.client.request(method, '/api'+path, json=data, headers=headers or self.headers)

    def inventory(self, fid='rice', grams=1000, days=10):
        r=self.req('POST',self.g+'/inventory',dict(ingredient_id=fid,grams=grams,expires_on=(date.today()+timedelta(days=days)).isoformat()))
        self.assertEqual(r.status_code,201,r.text)
        return r.json()

    def stock(self):
        return [self.inventory(fid,10000) for fid in ('rice','chicken_breast','carrot','olive_oil')]

    def request_plan(self, request_id='plan-request-1'):
        return self.req('POST',self.g+'/plans',dict(prompt='Plan dinners',days=2,start_date=date.today().isoformat(),
                        diners=[self.user],budget_cents=5000,request_id=request_id))

    def run_job(self, key):
        with self.app.state.store.tx() as db:
            job=self.app.state.store.get(db,key,'job')
        asyncio.run(self.app.state.orchestrator.run(job))
        return self.req('GET','/plans/'+key).json()

    def bob(self, join=True):
        r=self.client.post('/api/auth/dev',json={'name':'Bob','key':KEY}).json()
        h={'Authorization':'Bearer '+r['token']}
        if join:self.req('POST','/groups/join',{'code':self.invite},h)
        return r['user_id'],h

    def test_auth_required(self):
        self.assertEqual(self.client.get('/api/groups').status_code,401)

    def test_dev_key_rejected(self):
        self.assertEqual(self.client.post('/api/auth/dev',json={'name':'Eve','key':'wrong-key-000000000000'}).status_code,401)

    def test_no_openid_exposed(self):
        self.assertNotIn('openid',self.req('GET','/me').json())

    def test_cross_group_access_blocked(self):
        _,headers=self.bob(False)
        self.assertEqual(self.req('GET',self.g+'/inventory',headers=headers).status_code,403)

    def test_member_cannot_edit_budget_or_add_inventory(self):
        _,h=self.bob()
        self.assertEqual(self.req('PUT',self.g+'/settings',dict(budget_cents=100,budget_mode='total'),h).status_code,403)
        self.assertEqual(self.req('POST',self.g+'/inventory',dict(ingredient_id='rice',grams=100,expires_on=date.today().isoformat()),h).status_code,403)

    def test_invite_rotation_invalidates_previous_code(self):
        self.req('POST',self.g+'/invite',{})
        _,h=self.bob(False)
        self.assertEqual(self.req('POST','/groups/join',{'code':self.invite},h).status_code,404)

    def test_optimistic_lock(self):
        row=self.inventory()
        body=dict(ingredient_id='rice',grams=800,expires_on=row['expires_on'],version=row['version'])
        self.assertEqual(self.req('PUT',self.g+'/inventory/'+row['id'],body).status_code,200)
        self.assertEqual(self.req('PUT',self.g+'/inventory/'+row['id'],body).status_code,409)

    def test_consumption_is_atomic_and_duplicate_safe(self):
        a,b=self.inventory('rice',100),self.inventory('carrot',50)
        bad={'request_id':'consume-unique1','items':[{'inventory_id':a['id'],'grams':20},{'inventory_id':b['id'],'grams':90}]}
        self.assertEqual(self.req('POST',self.g+'/consume',bad).status_code,409)
        amounts={i['id']:i['grams'] for i in self.req('GET',self.g+'/inventory').json()}
        self.assertEqual(amounts[a['id']],100)
        good={'request_id':'consume-unique2','items':[{'inventory_id':a['id'],'grams':20}]}
        self.assertEqual(self.req('POST',self.g+'/consume',good).status_code,200)
        self.assertEqual(self.req('POST',self.g+'/consume',good).status_code,200)
        self.assertEqual({i['id']:i['grams'] for i in self.req('GET',self.g+'/inventory').json()}[a['id']],80)

    def test_duplicate_lines_cannot_overdraw_stock(self):
        row=self.inventory(grams=100)
        body={'request_id':'consume-dupes1','items':[{'inventory_id':row['id'],'grams':60}]*2}
        self.assertEqual(self.req('POST',self.g+'/consume',body).status_code,409)

    def test_spoiled_inventory_cannot_be_consumed(self):
        row=self.inventory()
        body={k:row[k] for k in ('ingredient_id','grams','purchased_on','expires_on','version')};body['freshness']='not_fresh'
        self.req('PUT',self.g+'/inventory/'+row['id'],body)
        self.assertEqual(self.req('POST',self.g+'/consume',{'request_id':'spoiled-consume','items':[{'inventory_id':row['id'],'grams':10}]}).status_code,422)

    def test_receipt_ledger_and_discount_allocation(self):
        body={'request_id':'receipt-unique','paid_cents':899,'actual_payment_confirmed':True,'items':[
            {'ingredient_id':'rice','grams':1000,'line_cents':600,'expires_on':date.today().isoformat()},
            {'ingredient_id':'carrot','grams':500,'line_cents':400,'expires_on':date.today().isoformat()}]}
        r=self.req('POST',self.g+'/receipts',body)
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(sum(i['allocated_paid_cents'] for i in r.json()['items']),899)
        self.assertEqual(self.req('POST',self.g+'/receipts',body).json()['id'],r.json()['id'])
        self.assertEqual(len(self.req('GET',self.g+'/inventory').json()),2)
        self.assertEqual(self.req('GET',self.g+'/reports').json()['paid_cents'],899)
        self.assertIn(self.req('PUT',self.g+'/receipts/'+r.json()['id'],body).status_code,(404,405))

    def test_idempotency_collision_rejected(self):
        body={'request_id':'collision-req','paid_cents':300,'actual_payment_confirmed':True,'items':[]}
        self.req('POST',self.g+'/receipts',body);body['paid_cents']=400
        self.assertEqual(self.req('POST',self.g+'/receipts',body).status_code,409)

    def test_estimated_weight_does_not_become_exact_price_history(self):
        body={'request_id':'estimated-rec','paid_cents':500,'actual_payment_confirmed':True,'items':[
            {'ingredient_id':'rice','grams':1000,'line_cents':500,'estimated':True,'expires_on':date.today().isoformat()}]}
        self.req('POST',self.g+'/receipts',body)
        self.assertNotIn('rice',self.req('GET',self.g+'/prices').json())

    def test_actual_price_has_priority_over_new_reference(self):
        body={'request_id':'realprice-rec','paid_cents':500,'actual_payment_confirmed':True,'items':[
            {'ingredient_id':'rice','grams':1000,'line_cents':500,'expires_on':date.today().isoformat()}]}
        self.req('POST',self.g+'/receipts',body)
        self.req('POST',self.g+'/prices',{'ingredient_id':'rice','cents_per_kg':999,'source':'Local reference'})
        p=self.req('GET',self.g+'/prices').json()['rice']
        self.assertEqual(p['cents_per_kg'],500);self.assertFalse(p['estimated'])

    def test_outside_meal_never_deducts_stock(self):
        row=self.inventory()
        body={'request_id':'outside-meal1','context':'out','items':[{'ingredient_id':'rice','grams':100}],
              'consumption':[{'inventory_id':row['id'],'grams':100}]}
        self.assertEqual(self.req('POST',self.g+'/meals',body).status_code,422)
        body['consumption']=[]
        self.assertEqual(self.req('POST',self.g+'/meals',body).status_code,201)
        self.assertEqual(self.req('GET',self.g+'/inventory').json()[0]['grams'],1000)

    def test_unknown_food_and_negative_weights_rejected(self):
        for body in [dict(ingredient_id='not-in-catalog',grams=10),dict(ingredient_id='rice',grams=-1)]:
            body['expires_on']=date.today().isoformat()
            self.assertEqual(self.req('POST',self.g+'/inventory',body).status_code,422)

    def test_recognition_draft_does_not_touch_stock(self):
        r=self.req('POST',self.g+'/drafts/text',{'kind':'inventory','text':'Some tomatoes'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()['items'][0]['estimated'])
        self.assertEqual(r.json()['items'][0]['grams'],400)
        self.assertEqual(self.req('GET',self.g+'/inventory').json(),[])
        key=r.json()['id'];_,h=self.bob()
        self.assertEqual(self.req('GET','/drafts/'+key,headers=h).status_code,403)

    def test_inventory_draft_can_be_confirmed_only_once(self):
        key=self.req('POST',self.g+'/drafts/text',{'kind':'inventory','text':'Tomatoes'}).json()['id']
        body={'items':[dict(ingredient_id='tomato',grams=400,estimated=True,expires_on=date.today().isoformat())]}
        self.assertEqual(self.req('POST','/drafts/'+key+'/confirm-inventory',body).status_code,200)
        self.assertEqual(self.req('POST','/drafts/'+key+'/confirm-inventory',body).status_code,409)

    def test_four_independent_agent_calls_and_sse_replay(self):
        self.stock();r=self.request_plan();self.assertEqual(r.status_code,202,r.text)
        result=self.run_job(r.json()['id']);self.assertEqual(result['status'],'complete',result)
        self.assertEqual([c[0] for c in self.provider.calls],['inventory','health','iteration','budget'])
        self.assertNotIn('context',result)
        stream=self.req('GET','/plans/'+result['id']+'/events').text
        self.assertIn('event: complete',stream);self.assertIn('event: day',stream)
        ids=[int(line[4:]) for line in stream.splitlines() if line.startswith('id: ')]
        tail=self.req('GET','/plans/'+result['id']+'/events?after='+str(max(ids))).text
        self.assertEqual(tail,'')

    def test_invalid_plan_retries_three_times_and_never_publishes(self):
        self.stock();self.provider.bad=True
        key=self.request_plan().json()['id'];result=self.run_job(key)
        self.assertEqual(result['status'],'needs_input');self.assertIsNone(result['result'])
        self.assertEqual(len(self.provider.calls),7)
        self.assertEqual(len(self.req('GET','/notifications').json()),1)

    def test_cache_and_inventory_invalidation(self):
        stock=self.stock();key=self.request_plan().json()['id'];self.run_job(key)
        self.assertTrue(self.request_plan('plan-request-2').json()['cache_hit'])
        self.req('POST',self.g+'/consume',{'request_id':'invalidate-req','items':[{'inventory_id':stock[0]['id'],'grams':1}]})
        self.assertFalse(self.request_plan('plan-request-3').json()['cache_hit'])

    def test_hard_allergy_never_overridden(self):
        self.stock();self.inventory('egg',1000)
        self.req('PUT','/me/profile',{'allergens':['egg'],'meal_target':TARGET})
        key=self.request_plan().json()['id']
        with self.app.state.store.tx() as db:ctx=self.app.state.store.get(db,key,'job')['context']
        raw=asyncio.run(self.provider.complete('budget','',{'context':ctx,'required_json_schema':{}}))
        raw['variants'][0]['days'][0]['dishes'][0]['ingredients'].append({'ingredient_id':'egg','grams':30})
        ctx['request']['override_soft']=True
        result,errors=validate_plan(raw,ctx)
        self.assertIsNone(result);self.assertTrue(any('Hard exclusion' in e['message'] for e in errors))

    def test_server_computes_cost_and_detects_missing_price(self):
        self.stock();key=self.request_plan().json()['id']
        with self.app.state.store.tx() as db:ctx=self.app.state.store.get(db,key,'job')['context']
        raw=asyncio.run(self.provider.complete('budget','',{'context':ctx,'required_json_schema':{}}))
        ctx['inventory']=[]
        result,errors=validate_plan(raw,ctx)
        self.assertTrue(any(e['layer']=='budget' for e in errors))
        ctx['prices']={k:dict(cents_per_kg=1000,estimated=True,source='test only') for k in ctx['foods']}
        result,errors=validate_plan(raw,ctx)
        self.assertFalse(errors);self.assertEqual(result['variants'][0]['cost_cents'],720)

    def test_personal_memory_not_leaked_to_group(self):
        self.req('POST',self.g+'/feedback',{'action':'substitute','text':'PRIVATE DETAIL','shared':False})
        self.assertIn('PRIVATE DETAIL',json.dumps(self.req('GET','/twins/personal').json()))
        self.assertNotIn('PRIVATE DETAIL',json.dumps(self.req('GET',self.g+'/twin').json()))
        _,h=self.bob()
        self.assertEqual(self.req('GET',self.g+'/twin',headers=h).status_code,403)
        self.req('PUT',self.g+'/settings',{'budget_cents':8000,'budget_mode':'per_person','twin_visibility':'all'})
        self.assertEqual(self.req('GET',self.g+'/twin',headers=h).status_code,200)

    def test_job_is_private_until_selected(self):
        self.stock();key=self.request_plan().json()['id'];self.run_job(key)
        _,h=self.bob()
        self.assertEqual(self.req('GET','/plans/'+key,headers=h).status_code,403)
        self.assertEqual(self.req('POST','/plans/'+key+'/select',{'mode':'balanced'}).status_code,200)
        self.assertEqual(len(self.req('GET',self.g+'/selected-plans',headers=h).json()),1)

    def test_special_profiles_require_explicit_targets(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):target_for({'tags':['pregnant'],'age':29,'height_cm':170,'weight_kg':60,'sex':'female'})
        with self.assertRaises(HTTPException):target_for({'age':14,'height_cm':160,'weight_kg':50,'sex':'male'})

    def test_reference_nutrition_and_image_sanitization(self):
        n=nutrition([{'ingredient_id':'chicken_breast','grams':100}])
        self.assertEqual(n['kcal'],120);self.assertEqual(n['protein'],22.5)
        image=Image.new('RGB',(10,10),'red');buf=io.BytesIO();image.save(buf,'PNG')
        self.assertTrue(clean_image(buf.getvalue()).startswith(b'\xff\xd8'))
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):clean_image(b'not an image')

    def test_restart_recovery_does_not_silently_rebill(self):
        self.stock();key=self.request_plan().json()['id'];s=self.app.state.store
        with s.tx() as db:
            row=s.get(db,key,'job');row['status']='running';s.put(db,'job',self.group,self.user,row,key)
        self.app.state.orchestrator.recover()
        self.assertEqual(self.req('GET','/plans/'+key).json()['status'],'failed')
        self.assertEqual(self.provider.calls,[])

    def test_changed_profile_invalidates_plan_selection(self):
        self.stock();key=self.request_plan().json()['id'];self.run_job(key)
        self.req('PUT','/me/profile',{'meal_target':TARGET,'forbidden_ingredients':['rice']})
        self.assertEqual(self.req('POST','/plans/'+key+'/select',{'mode':'balanced'}).status_code,409)

    def test_invalid_receipt_rolls_back_all_inventory(self):
        body={'request_id':'rollback-receipt','paid_cents':1000,'actual_payment_confirmed':True,'items':[
            {'ingredient_id':'rice','grams':500,'line_cents':500,'expires_on':date.today().isoformat()},
            {'ingredient_id':'fake','grams':500,'line_cents':500,'expires_on':date.today().isoformat()}]}
        self.assertEqual(self.req('POST',self.g+'/receipts',body).status_code,422)
        self.assertEqual(self.req('GET',self.g+'/inventory').json(),[])
        self.assertEqual(self.req('GET',self.g+'/receipts').json(),[])

    def test_reference_prices_always_marked_estimated(self):
        self.req('POST',self.g+'/prices',{'ingredient_id':'rice','cents_per_kg':200,'source':'Market reference'})
        self.assertTrue(self.req('GET',self.g+'/prices').json()['rice']['estimated'])

    def test_future_purchase_rejected(self):
        body={'request_id':'future-receipt','paid_cents':10,'actual_payment_confirmed':True,
              'purchased_on':(date.today()+timedelta(days=1)).isoformat(),'items':[]}
        self.assertEqual(self.req('POST',self.g+'/receipts',body).status_code,422)

    def test_feedback_withdrawal_invalidates_memory(self):
        row=self.req('POST',self.g+'/feedback',{'action':'substitute','text':'REMOVE ME','shared':True}).json()
        self.assertIn('REMOVE ME',self.req('GET','/twins/personal').text)
        self.req('DELETE','/feedback/'+row['id'])
        self.assertNotIn('REMOVE ME',self.req('GET','/twins/personal').text)

    def test_group_websocket_needs_member_token(self):
        with self.client.websocket_connect('/api'+self.g+'/live') as ws:
            ws.send_json({'token':self.headers['Authorization'][7:]})
            self.assertEqual(ws.receive_json()['type'],'ready')
            self.inventory()
            event=ws.receive_json()
            while event['type']=='ping':
                ws.send_text('pong');event=ws.receive_json()
            self.assertEqual(event['type'],'inventory_changed')

    def test_web_console_and_openapi_available(self):
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/app.js').status_code,200)
        schema=self.client.get('/openapi.json').json()
        self.assertIn('/api/groups/{group}/plans',schema['paths'])

    def test_no_daily_zero_for_unrecorded_meals(self):
        result=self.req('GET',self.g+'/reports').json()
        self.assertEqual(result['days'],{});self.assertIsNone(result['score'])

    def test_real_background_queue_completes_with_test_provider(self):
        import time
        self.stock()
        settings=copy.copy(self.settings);settings.worker_enabled=True
        app=create_app(settings,self.provider)
        with TestClient(app) as worker_client:
            body=dict(prompt='Background queue test',days=1,start_date=date.today().isoformat(),diners=[self.user],budget_cents=5000,request_id='background-job')
            r=worker_client.post('/api'+self.g+'/plans',json=body,headers=self.headers)
            self.assertEqual(r.status_code,202,r.text);key=r.json()['id']
            for _ in range(50):
                job=worker_client.get('/api/plans/'+key,headers=self.headers).json()
                if job['status'] not in ('queued','running'):break
                time.sleep(.05)
            self.assertEqual(job['status'],'complete',job)

    def test_duplicate_diners_rejected(self):
        self.stock()
        body=dict(prompt='Plan dinners',days=1,diners=[self.user,self.user],budget_cents=5000,request_id='duplicate-diners')
        self.assertEqual(self.req('POST',self.g+'/plans',body).status_code,422)

    def test_expired_stock_is_not_a_free_purchase(self):
        self.stock();key=self.request_plan().json()['id']
        with self.app.state.store.tx() as db:ctx=self.app.state.store.get(db,key,'job')['context']
        raw=asyncio.run(self.provider.complete('budget','',{'context':ctx,'required_json_schema':{}}))
        for row in ctx['inventory']:row['expires_on']=(date.today()-timedelta(days=1)).isoformat()
        _,errors=validate_plan(raw,ctx)
        self.assertTrue(any(e['layer']=='budget' and 'Missing purchase price' in e['message'] for e in errors))

    def test_receipt_without_confirmation_is_rejected(self):
        body={'request_id':'unconfirmed-rec','paid_cents':100,'items':[],'actual_payment_confirmed':False}
        self.assertEqual(self.req('POST',self.g+'/receipts',body).status_code,422)

    def test_report_alignment_is_explicit_and_not_full_day(self):
        self.req('POST',self.g+'/meals',{'request_id':'score-meal-test','context':'out','items':[{'ingredient_id':'rice','grams':100},{'ingredient_id':'olive_oil','grams':10}]})
        report=self.req('GET',self.g+'/reports').json()
        self.assertEqual(report['scored_meals'],1);self.assertEqual(report['score_method'],'target-alignment-v1')
        self.assertIn('NOT a clinical',report['score_note'])

    def test_confirmed_weight_correction_calibrates_only_own_estimates(self):
        row=self.req('POST',self.g+'/drafts/text',{'kind':'inventory','text':'Tomato reference estimate'}).json()
        self.assertEqual(row['items'][0]['grams'],400)
        self.req('POST','/drafts/'+row['id']+'/confirm-inventory',{'items':[
            {'ingredient_id':'tomato','grams':600,'estimated':False,'expires_on':date.today().isoformat()}]})
        corrected=self.req('POST',self.g+'/drafts/text',{'kind':'inventory','text':'Tomato reference estimate'}).json()
        self.assertEqual(corrected['items'][0]['grams'],600)
        self.assertTrue(corrected['items'][0]['estimated'])
        _,h=self.bob()
        other=self.req('POST',self.g+'/drafts/text',{'kind':'inventory','text':'Tomato reference estimate'},h).json()
        self.assertEqual(other['items'][0]['grams'],400)

    def test_logout_revokes_token(self):
        self.assertEqual(self.req('POST','/auth/logout',{}).status_code,200)
        self.assertEqual(self.req('GET','/me').status_code,401)


if __name__ == '__main__':
    unittest.main()
