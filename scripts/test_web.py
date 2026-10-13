"""Optional headless browser test against a REAL temporary backend (no AI fixture).
Requires: pip install playwright; installed Chromium or Microsoft Edge.
All entered records are explicitly synthetic acceptance-test inputs, not model outputs.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exports"
OUT.mkdir(exist_ok=True)
with socket.socket() as sock:
    sock.bind(("127.0.0.1",0)); port=sock.getsockname()[1]
url=f"http://127.0.0.1:{port}"
with tempfile.TemporaryDirectory(prefix="web-check-",dir=OUT) as tmp:
    key=secrets.token_urlsafe(30)
    env={**os.environ,"ALLOW_DEV_LOGIN":"true","DEV_LOGIN_KEY":key,
         "MEALAGENT_DB":str(Path(tmp)/"acceptance.sqlite3"),"DEEPSEEK_API_KEY":""}
    proc=subprocess.Popen([sys.executable,"-m","uvicorn","backend.app.main:app","--host","127.0.0.1","--port",str(port)],
                          cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    try:
        for _ in range(80):
            try:
                if httpx.get(url+'/api/health',timeout=.5).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.2)
        else:raise RuntimeError('Backend did not start')
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1060},device_scale_factor=1)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url);page.locator('#auth').wait_for(state='visible')
            page.locator('#loginForm [name=name]').fill('浏览器验收用户（测试）')
            page.locator('#loginForm [name=key]').fill(key)
            page.locator('#loginForm button').click();page.locator('#auth').wait_for(state='hidden')
            page.locator('#createGroup [name=name]').fill('验收测试家庭 · 非真实用户数据')
            page.locator('#createGroup button').click()
            page.wait_for_function("document.querySelector('#groupPicker').selectedOptions[0].textContent.includes('验收测试家庭')")
            page.locator('[data-tab=inventory]').click()
            page.locator('#stockForm [name=ingredient_id]').select_option('rice')
            page.locator('#stockForm [name=grams]').fill('1000')
            page.locator('#stockForm [name=expires_on]').fill((date.today()+timedelta(days=10)).isoformat())
            page.locator('#stockForm button').click();page.locator('.stockrow').wait_for()
            assert '1000g' in page.locator('.stockrow').inner_text()
            page.locator('[data-tab=record]').click();page.locator('#receiptForm [name=paid]').fill('25.50')
            page.locator('#receiptForm input[type=checkbox]').check();page.locator('#receiptForm button').click()
            page.wait_for_function("document.querySelector('#spent').textContent==='¥25.50'")
            page.locator('[data-tab=profile]').click()
            profile=json.loads(page.locator('#profileEditor').input_value())
            profile['meal_target']={'kcal_min':100,'kcal_max':2000,'protein_min':1,'protein_max':200,'carbs_min':1,'carbs_max':400,'fat_min':1,'fat_max':150}
            page.locator('#profileEditor').fill(json.dumps(profile,ensure_ascii=False,indent=2));page.locator('#saveProfile').click()
            page.wait_for_function("document.querySelector('#toast').textContent==='画像已保存'")
            page.locator('[data-tab=plan]').click();page.locator('#planForm button').click()
            page.wait_for_function("document.querySelector('#toast').textContent.includes('DEEPSEEK_API_KEY')")
            assert page.locator('#planResults').inner_text()==''
            page.locator('[data-tab=overview]').click();page.locator('#toast').evaluate('(e)=>e.hidden=true')
            page.locator('#invite').evaluate('(e)=>e.textContent="邀请码已隐藏（截图验收）"')
            page.wait_for_timeout(250)
            page.screenshot(path=str(OUT/'desktop-verification.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Desktop overflows'
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(OUT/'mobile-verification.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Mobile overflows'
            assert not errors, errors
            browser.close()
        print('PASS: real-backend login, group creation, inventory, immutable payment, profile save, missing-key error, responsive desktop/mobile, zero browser exceptions')
        print('Screenshots:', OUT)
    finally:
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
