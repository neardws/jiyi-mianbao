"""knowledge.json → Anki .apkg（genanki）。"""
from __future__ import annotations

import hashlib
import html

import genanki

from .knowledge import video_url

MODEL_ID = 1729384001  # 固定，勿改：改了会让已导入的卡片变成新笔记类型
DECK_ROOT = "记忆面包"


def _stable_id(s: str) -> int:
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16) | (1 << 30)


def fmt_ts(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


MODEL = genanki.Model(
    MODEL_ID, "记忆面包 Q/A",
    fields=[{"name": n} for n in ("Question", "Answer", "Quote", "Link", "Source", "KPTitle")],
    templates=[{
        "name": "Card 1",
        "qfmt": '<div class="kp">{{KPTitle}}</div><div class="q">{{Question}}</div>',
        "afmt": '{{FrontSide}}<hr id="answer"><div class="a">{{Answer}}</div>'
                '<blockquote class="quote">{{Quote}}</blockquote>'
                '<div class="link">{{Link}}</div><div class="src">{{Source}}</div>',
    }],
    css=""".card{font-family:-apple-system,"PingFang SC",sans-serif;font-size:20px;text-align:left;
color:#222;background:#fffaf2;line-height:1.5;padding:12px}
.kp{font-size:13px;color:#b07a3c}.q{font-weight:600}.a{margin:8px 0}
.quote{font-size:15px;color:#555;border-left:3px solid #e0b070;margin:10px 0;padding-left:10px}
.link a{color:#00a1d6;font-size:15px}.src{font-size:13px;color:#888;margin-top:6px}""",
)


def build_deck(k: dict, deck_name: str | None = None) -> genanki.Deck:
    src = k.get("source") or {}
    bvid = src.get("bvid")
    title = src.get("title") or src.get("source_file") or "未命名"
    deck = genanki.Deck(_stable_id(f"deck:{bvid or title}:{src.get('page') or 1}"),
                        deck_name or f"{DECK_ROOT}::{title}")
    source_html = html.escape(f"《{title}》" + (f" · UP主 {src['owner']}" if src.get("owner") else "")
                              + (f" · {bvid}" if bvid else ""))
    tags = ["mbread"] + ([bvid] if bvid else []) + (["ai字幕"] if src.get("ai") else [])
    for p in k["points"]:
        url = p.get("url") or video_url(bvid, src.get("page") or 1, p["start"])
        ts = f"{fmt_ts(p['start'])}–{fmt_ts(p['end'])}"
        link = f'<a href="{html.escape(url)}">▶ {ts} 跳到B站原片</a>' if url else f"⏱ {ts}"
        for ci, c in enumerate(p["cards"]):
            deck.add_note(genanki.Note(
                model=MODEL,
                fields=[html.escape(c["q"]), html.escape(c["a"]).replace("\n", "<br>"),
                        html.escape(p["quote"]), link, source_html, html.escape(p["title"])],
                tags=tags,
                guid=genanki.guid_for(bvid or title, p["id"], ci, c["q"]),
            ))
    return deck


def write_apkg(k: dict, path: str, deck_name: str | None = None) -> int:
    deck = build_deck(k, deck_name)
    genanki.Package(deck).write_to_file(path)
    return len(deck.notes)
