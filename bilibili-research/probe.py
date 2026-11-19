#!/usr/bin/env python3
"""Read-only connectivity diagnostic for Bilibili publicly accessible endpoints.
No credentials, scraping bypass, or persistent comment dataset.
"""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

VIDEOS = {
    "2026_07_method": "BV1ZCGP6kExh",
    "2026_09_drawdown": "BV1VoeJ6vENo",
    "2025_09_gain": "BV1MKJRziEC5",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PublicResearch/1.0)",
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json,text/plain,*/*",
}

def get_json(url):
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=8) as resp:
            raw = resp.read(450_000)
            return {"http": resp.status, "data": json.loads(raw)}
    except HTTPError as e:
        return {"http": e.code, "error": str(e)}
    except Exception as e:
        return {"error": type(e).__name__ + ": " + str(e)[:130]}

for label, bvid in VIDEOS.items():
    result = {"video": label, "bvid": bvid}
    v = get_json("https://api.bilibili.com/x/web-interface/view?" + urlencode({"bvid": bvid}))
    result["metadata_request"] = {"http": v.get("http"), "api_code": v.get("data",{}).get("code"),"error":v.get("error")}
    dat = v.get("data", {}).get("data") or {}
    if dat:
        result.update({"title":dat.get("title"),"aid":dat.get("aid"),"comment_count":dat.get("stat",{}).get("reply"),"pubdate":dat.get("pubdate")})
        subs = (dat.get("subtitle") or {}).get("list",[])
        result["public_subtitle_tracks"] = len(subs)
        result["subtitle_samples"] = []
        for sub in subs[:1]:
            url = sub.get("subtitle_url","")
            if url.startswith("//"): url = "https:" + url
            if url.startswith("https://"):
                z = get_json(url)
                body = z.get("data",{}).get("body",[])
                result["subtitle_samples"] = [d.get("content","")[:130] for d in body[:5]]
                result["subtitle_http"] = z.get("http")
        aid=dat.get("aid")
        if aid:
            c=get_json("https://api.bilibili.com/x/v2/reply?" + urlencode({"type":1,"oid":aid,"pn":1,"ps":20}))
            result["comments_request"]={"http":c.get("http"),"api_code":c.get("data",{}).get("code"),"error":c.get("error")}
            replies=(c.get("data",{}).get("data") or {}).get("replies") or []
            result["public_comment_sample"]=[p.get("content",{}).get("message","")[:145] for p in replies[:6]]
            result["comment_count_sample"]=len(replies)
    print(json.dumps(result,ensure_ascii=False),flush=True)
