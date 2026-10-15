"""获取 B站视频字幕（只取字幕与元数据，绝不下载视频/音频）。

用法:
    python -m mbread.subtitles BV1ys411472E [--page 1] [--lang zh-CN] [--sessdata XXX]
环境变量 BILI_SESSDATA 也可提供登录 cookie（可选）。
输出: JSON {"bvid","cid","title","lang","lang_doc","ai","segments":[{"start","end","text"}]}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
MIXIN = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
         49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55,
         40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57,
         62, 11, 36, 20, 34, 44, 52]


class SubtitleError(RuntimeError):
    pass


class NoSubtitleError(SubtitleError):
    pass


def parse_bvid(s: str) -> str:
    m = re.search(r"(BV[0-9A-Za-z]{10})", s)
    if not m:
        raise SubtitleError(f"无法从输入中识别 BV 号: {s!r}")
    return m.group(1)


class Bili:
    def __init__(self, sessdata: str | None = None, timeout: int = 15):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
        self.timeout = timeout
        if sessdata:
            self.s.cookies.set("SESSDATA", sessdata, domain=".bilibili.com")
        # 拿 buvid3 等基础 cookie，降低风控概率
        self.s.get("https://www.bilibili.com/", timeout=timeout)
        nav = self.s.get("https://api.bilibili.com/x/web-interface/nav", timeout=timeout).json()
        self.logged_in = bool(nav.get("data", {}).get("isLogin"))
        w = nav["data"]["wbi_img"]
        key = (w["img_url"].rsplit("/", 1)[1].split(".")[0]
               + w["sub_url"].rsplit("/", 1)[1].split(".")[0])
        self.mixin_key = "".join(key[i] for i in MIXIN)[:32]

    def _sign(self, params: dict) -> dict:
        p = {k: re.sub(r"[!'()*]", "", str(v)) for k, v in params.items()}
        p["wts"] = int(time.time())
        q = urllib.parse.urlencode(sorted(p.items()))
        p["w_rid"] = hashlib.md5((q + self.mixin_key).encode()).hexdigest()
        return p

    def _get(self, url: str, params: dict, wbi: bool = True) -> dict:
        r = self.s.get(url, params=self._sign(params) if wbi else params, timeout=self.timeout)
        if r.status_code != 200:
            raise SubtitleError(f"HTTP {r.status_code} {url}（可能触发风控）")
        j = r.json()
        if j.get("code") != 0:
            raise SubtitleError(f"接口错误 {j.get('code')}: {j.get('message')} ({url})")
        return j["data"]

    def view(self, bvid: str) -> dict:
        return self._get("https://api.bilibili.com/x/web-interface/wbi/view", {"bvid": bvid})

    def player(self, bvid: str, cid: int, aid: int | None = None) -> dict:
        p = {"bvid": bvid, "cid": cid}
        if aid:
            p["aid"] = aid
        return self._get("https://api.bilibili.com/x/player/wbi/v2", p)

    def fetch_json(self, url: str) -> dict:
        if url.startswith("//"):
            url = "https:" + url
        r = self.s.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def list_tracks(bili: Bili, bvid: str, page: int = 1) -> tuple[dict, int, list[dict]]:
    v = bili.view(bvid)
    pages = v.get("pages") or [{"cid": v["cid"]}]
    if not 1 <= page <= len(pages):
        raise SubtitleError(f"分P {page} 不存在（共 {len(pages)} P）")
    cid = pages[page - 1]["cid"]
    pl = bili.player(bvid, cid, v.get("aid"))
    tracks = (pl.get("subtitle") or {}).get("subtitles") or []
    v["_need_login_subtitle"] = bool(pl.get("need_login_subtitle"))
    return v, cid, tracks


def get_subtitles(src: str, page: int = 1, lang: str | None = None,
                  sessdata: str | None = None) -> dict:
    bvid = parse_bvid(src)
    bili = Bili(sessdata or os.environ.get("BILI_SESSDATA"))
    v, cid, tracks = list_tracks(bili, bvid, page)
    tracks = [t for t in tracks if t.get("subtitle_url")]
    if not tracks:
        if not bili.logged_in and v.get("_need_login_subtitle"):
            raise NoSubtitleError(f"{bvid} P{page}: 接口返回 need_login_subtitle=true，"
                                  "未登录拿不到字幕列表；请设置 BILI_SESSDATA 后重试")
        hint = "" if bili.logged_in else "（当前未登录）"
        raise NoSubtitleError(f"{bvid} P{page} 没有可用字幕{hint}")
    pick = None
    if lang:
        pick = next((t for t in tracks if t.get("lan") == lang), None)
    if pick is None:  # 优先人工字幕，再 AI 字幕
        pick = sorted(tracks, key=lambda t: str(t.get("lan", "")).startswith("ai-"))[0]
    body = bili.fetch_json(pick["subtitle_url"]).get("body") or []
    segs = [{"start": round(float(b["from"]), 3), "end": round(float(b["to"]), 3),
             "text": b["content"].strip()} for b in body]
    if not segs:
        raise NoSubtitleError(f"{bvid} 字幕文件为空")
    return {"bvid": bvid, "cid": cid, "page": page, "title": v.get("title"),
            "owner": (v.get("owner") or {}).get("name"),
            "url": f"https://www.bilibili.com/video/{bvid}?p={page}",
            "lang": pick.get("lan"), "lang_doc": pick.get("lan_doc"),
            "ai": str(pick.get("lan", "")).startswith("ai-"),
            "segments": segs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="获取 B站视频带时间戳字幕")
    ap.add_argument("src", help="BV 号或视频链接")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--lang")
    ap.add_argument("--sessdata")
    ap.add_argument("--list", action="store_true", help="只列出字幕轨道")
    a = ap.parse_args(argv)
    try:
        if a.list:
            b = Bili(a.sessdata or os.environ.get("BILI_SESSDATA"))
            v, cid, t = list_tracks(b, parse_bvid(a.src), a.page)
            print(json.dumps({"title": v.get("title"), "cid": cid, "logged_in": b.logged_in,
                              "tracks": [{k: x.get(k) for k in ("lan", "lan_doc", "subtitle_url")} for x in t]},
                             ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(get_subtitles(a.src, a.page, a.lang, a.sessdata), ensure_ascii=False, indent=2))
        return 0
    except NoSubtitleError as e:
        print(f"无字幕: {e}", file=sys.stderr); return 2
    except SubtitleError as e:
        print(f"错误: {e}", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
