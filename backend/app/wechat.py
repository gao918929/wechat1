"""WeChat server APIs: login (code2session) and subscription messages."""
from __future__ import annotations

import hashlib
import logging
import time

import httpx

from .config import settings

log = logging.getLogger("mealagent.wechat")
_token_cache: dict[str, float | str] = {"token": "", "expires": 0.0}


async def code2session(code: str, dev_id: str = "") -> str:
    """Return the user's openid. Without WeChat credentials (local dev) a stable dev id is used."""
    if not settings.wechat_enabled:
        seed = dev_id or code
        return "dev-" + hashlib.sha256(seed.encode()).hexdigest()[:24]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.weixin.qq.com/sns/jscode2session", params={
            "appid": settings.wechat_appid, "secret": settings.wechat_secret, "js_code": code,
            "grant_type": "authorization_code"})
    data = r.json()
    if "openid" not in data:
        raise RuntimeError(f"code2session failed: {data}")
    return data["openid"]


async def _access_token() -> str:
    if _token_cache["token"] and float(_token_cache["expires"]) > time.time() + 60:
        return str(_token_cache["token"])
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.weixin.qq.com/cgi-bin/token", params={
            "grant_type": "client_credential", "appid": settings.wechat_appid, "secret": settings.wechat_secret})
    data = r.json()
    _token_cache.update(token=data.get("access_token", ""), expires=time.time() + int(data.get("expires_in", 0)))
    return str(_token_cache["token"])


async def send_plan_ready(openid: str, plan_id: int, title: str) -> bool:
    """Notify via a WeChat subscription message (the user must have subscribed in the mini program)."""
    if not (settings.wechat_enabled and settings.wechat_plan_template_id) or openid.startswith("dev-"):
        return False
    try:
        token = await _access_token()
        payload = {
            "touser": openid, "template_id": settings.wechat_plan_template_id,
            "page": f"pages/plan/plan?id={plan_id}",
            "data": {"thing1": {"value": title[:20]}, "time2": {"value": time.strftime("%Y-%m-%d %H:%M")}},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={token}",
                                  json=payload)
        ok = r.json().get("errcode") == 0
        if not ok:
            log.warning("subscribe message failed: %s", r.text)
        return ok
    except httpx.HTTPError as exc:
        log.warning("subscribe message error: %s", exc)
        return False
