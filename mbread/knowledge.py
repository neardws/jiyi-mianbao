"""字幕 segments → knowledge.json（知识点中间层）。

knowledge.json 由 Anki 卡组、小红书卡片、图文总结三种输出共用。schema 见 docs/02-knowledge-schema.md。
LLM 走 OpenAI 兼容接口，配置：
    MBREAD_BASE_URL  例如 https://api.deepseek.com/v1、http://localhost:11434/v1
    MBREAD_API_KEY   本地 Ollama 可随便填
    MBREAD_MODEL     例如 deepseek-chat、qwen-plus、qwen2.5:14b
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable

SCHEMA_VERSION = 1
TS_TOL = 0.01  # 秒

SYSTEM_PROMPT = """你是学习卡片编辑。只能使用用户给出的字幕内容，不得加入字幕之外的事实或常识补充。
字幕每行格式：[段号] 开始秒-结束秒 文本。
任务：把这段字幕切成若干个独立的知识点（一般每 1-4 分钟一个；闲聊、广告、片头片尾不要）。
每个知识点：
- title：≤20 字的标题
- summary：1-3 句话概括，只基于字幕
- start_seg / end_seg：这个知识点起止的段号（整数，必须是上面出现过的段号，start_seg ≤ end_seg）
- quote：从字幕原文中**逐字摘抄**的一句关键原话（可去掉语气词，不得改写）
- cards：1-3 张问答卡 [{"q": 问题, "a": 简洁答案}]，答案必须能在字幕中找到依据
只输出 JSON：{"points": [ ... ]}，不要任何解释。"""


class KnowledgeError(RuntimeError):
    pass


# ---------- 分块 ----------
def chunk_segments(segments: list[dict], max_chars: int = 6000, overlap: int = 3) -> list[list[int]]:
    """按字符预算把段号切块，块间重叠 overlap 段以免知识点被切断。返回每块的段号列表。"""
    chunks, cur, size = [], [], 0
    for i, s in enumerate(segments):
        n = len(s["text"]) + 20
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur = cur[-overlap:] if overlap else []
            size = sum(len(segments[j]["text"]) + 20 for j in cur)
        cur.append(i)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def render_chunk(segments: list[dict], idx: list[int]) -> str:
    return "\n".join(f"[{i}] {segments[i]['start']:.1f}-{segments[i]['end']:.1f} {segments[i]['text']}"
                     for i in idx)


# ---------- LLM ----------
def llm_config() -> dict:
    cfg = {k: os.environ.get(f"MBREAD_{k.upper()}") for k in ("base_url", "api_key", "model")}
    missing = [f"MBREAD_{k.upper()}" for k, v in cfg.items() if not v]
    if missing:
        raise KnowledgeError("缺少 LLM 配置环境变量: " + ", ".join(missing))
    return cfg


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v else default
    except ValueError:
        raise KnowledgeError(f"{name} 必须是整数，当前为 {v!r}")


def strip_think(text: str) -> str:
    """去掉推理模型的 <think>…</think>（含未闭合的开头块）。"""
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "<think>" in t:  # 没闭合：思考被截断，剩下的不可用
        t = t.split("<think>")[0]
    if "</think>" in t:  # 只有结束标签（模板已吃掉开头）
        t = t.split("</think>")[-1]
    return t.strip()


def _extract_json_text(text: str | None) -> str | None:
    if not text:
        return None
    t = strip_think(text)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        json.loads(m.group(0))
        return m.group(0)
    except json.JSONDecodeError:
        return None


def openai_chat(system: str, user: str, cfg: dict | None = None, timeout: int | None = None) -> str:
    """调用 OpenAI 兼容 /chat/completions，返回去掉思考过程后的文本。

    环境变量：MBREAD_MAX_TOKENS（默认 8192）、MBREAD_TIMEOUT（秒，默认 600）、
    MBREAD_THINKING=1 开启推理模型的思考（默认通过 chat_template_kwargs 关闭）。
    """
    import requests
    cfg = cfg or llm_config()
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    timeout = timeout or _env_int("MBREAD_TIMEOUT", 600)
    max_tokens = _env_int("MBREAD_MAX_TOKENS", 8192)
    thinking = os.environ.get("MBREAD_THINKING", "") in ("1", "true", "yes")
    base = {"model": cfg["model"], "temperature": 0.2, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    extras = {"response_format": {"type": "json_object"}}
    if not thinking:
        extras["chat_template_kwargs"] = {"enable_thinking": False}
    # 依次尝试：全部扩展字段 → 去掉 response_format → 去掉全部扩展（后端不认识时会 400/422）
    variants = [extras, {k: v for k, v in extras.items() if k != "response_format"}, {}]
    h = {"Authorization": f"Bearer {cfg['api_key']}"}

    def post() -> dict:
        last = None
        for ex in variants:
            try:
                r = requests.post(url, json=base | ex, headers=h, timeout=(10, timeout))
            except requests.Timeout:
                raise KnowledgeError(f"LLM 超时（>{timeout}s）：可调大 MBREAD_TIMEOUT 或减小 --max-chars")
            except requests.ConnectionError as e:
                raise KnowledgeError(f"连不上 LLM 服务 {url}：{e.__class__.__name__}（服务启动了吗？）")
            if r.status_code == 200:
                return r.json()
            last = r
            if r.status_code not in (400, 422):
                break
        raise KnowledgeError(f"LLM 请求失败 HTTP {last.status_code}: {last.text[:300]}")

    for attempt in (1, 2):
        data = post()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content")
        if content and strip_think(content):
            return strip_think(content)
        if choice.get("finish_reason") == "length":
            raise KnowledgeError(
                f"模型输出被 max_tokens={max_tokens} 截断，正文为空（多半是思考过程用光了额度）。"
                "请调大 MBREAD_MAX_TOKENS（如 16384），或去掉 MBREAD_THINKING 关闭思考，或减小 --max-chars")
        for k in ("reasoning", "reasoning_content"):
            j = _extract_json_text(msg.get(k)) or _extract_json_text(content)
            if j:
                return j
    raise KnowledgeError("LLM 两次都返回空内容（content 为空，reasoning 中也没有 JSON）。"
                         "可检查模型是否支持关闭思考，或换模型")


def parse_json(text: str | None) -> dict:
    if not text:
        raise KnowledgeError("LLM 返回空内容")
    t = strip_think(text)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            return json.loads(m.group(0))
        raise KnowledgeError(f"LLM 输出不是 JSON: {text[:200]}")


# ---------- 校验 ----------
def _norm(s: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;“”\"'（）()…—-]", "", s)


def quote_in_segments(quote: str, segments: list[dict], i0: int, i1: int, slack: int = 1) -> bool:
    lo, hi = max(0, i0 - slack), min(len(segments) - 1, i1 + slack)
    hay = _norm("".join(segments[k]["text"] for k in range(lo, hi + 1)))
    q = _norm(quote)
    return bool(q) and q in hay


def _point_from_llm(p: dict, segments: list[dict], allowed: set[int]) -> dict | None:
    try:
        a, b = int(p["start_seg"]), int(p["end_seg"])
    except (KeyError, TypeError, ValueError):
        return None
    if a > b:
        a, b = b, a
    if a not in allowed or b not in allowed:
        return None
    quote = str(p.get("quote", "")).strip()
    if not quote_in_segments(quote, segments, a, b):
        # 模型改写了原话：退回用真实字幕原文，保证引用可信
        quote = "".join(segments[k]["text"] for k in range(a, min(b, a + 2) + 1))
    cards = [{"q": str(c["q"]).strip(), "a": str(c["a"]).strip()}
             for c in p.get("cards", []) if isinstance(c, dict) and c.get("q") and c.get("a")]
    if not cards or not p.get("title"):
        return None
    return {"title": str(p["title"]).strip(), "summary": str(p.get("summary", "")).strip(),
            "start": segments[a]["start"], "end": segments[b]["end"],
            "seg_range": [a, b], "quote": quote, "cards": cards}


def validate_knowledge(k: dict) -> list[str]:
    """校验 knowledge.json；返回问题列表（空 = 通过）。时间戳必须对齐真实 segment 边界。"""
    errs = []
    segs = k.get("segments") or []
    if k.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version 应为 {SCHEMA_VERSION}")
    if not segs:
        errs.append("缺少 segments（校验时间戳需要原始字幕）")
    starts = [s["start"] for s in segs]
    ends = [s["end"] for s in segs]
    for n, p in enumerate(k.get("points", [])):
        tag = f"points[{n}] {p.get('title', '')!r}"
        for f in ("id", "title", "summary", "start", "end", "quote", "cards", "url"):
            if f not in p:
                errs.append(f"{tag} 缺字段 {f}")
        if not p.get("cards"):
            errs.append(f"{tag} 没有卡片")
        s, e = p.get("start"), p.get("end")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)) or s >= e:
            errs.append(f"{tag} start/end 非法: {s}, {e}")
            continue
        if segs:
            if not any(abs(s - x) <= TS_TOL for x in starts):
                errs.append(f"{tag} start={s} 不是任何字幕段的开始时间")
            if not any(abs(e - x) <= TS_TOL for x in ends):
                errs.append(f"{tag} end={e} 不是任何字幕段的结束时间")
            if s < starts[0] - TS_TOL or e > max(ends) + TS_TOL:
                errs.append(f"{tag} 时间超出字幕范围")
            ia = next((i for i, x in enumerate(starts) if abs(s - x) <= TS_TOL), None)
            ib = next((i for i, x in enumerate(ends) if abs(e - x) <= TS_TOL), None)
            if ia is not None and ib is not None and p.get("quote") and \
                    not quote_in_segments(p["quote"], segs, ia, ib):
                errs.append(f"{tag} quote 不在对应时间段的字幕原文中")
    return errs


# ---------- 主流程 ----------
def video_url(bvid: str | None, page: int = 1, t: float | None = None) -> str | None:
    if not bvid:
        return None
    u = f"https://www.bilibili.com/video/{bvid}?p={page}"
    return u + (f"&t={int(t)}" if t is not None else "")


def build_knowledge(sub: dict, chat: Callable[[str, str], str] | None = None,
                    max_chars: int = 6000, log: Callable[[str], None] = lambda m: None) -> dict:
    """sub 为 subtitles.get_subtitles / load_subtitle_file 的输出。chat(system, user)->str 可注入（测试用 mock）。"""
    segments = sub["segments"]
    if not segments:
        raise KnowledgeError("字幕为空")
    chat = chat or (lambda s, u: openai_chat(s, u))
    page = sub.get("page") or 1
    points: list[dict] = []
    chunks = chunk_segments(segments, max_chars)
    for ci, idx in enumerate(chunks, 1):
        log(f"知识点切分：第 {ci}/{len(chunks)} 块（段 {idx[0]}-{idx[-1]}）")
        user = f"视频标题：{sub.get('title') or '未知'}\n字幕：\n{render_chunk(segments, idx)}"
        data = parse_json(chat(SYSTEM_PROMPT, user))
        allowed = set(idx)
        for p in data.get("points", []):
            q = _point_from_llm(p, segments, allowed)
            if q is None:
                log(f"  丢弃不合法的知识点: {str(p)[:80]}")
                continue
            # 重叠区去重：与已有知识点时间重叠超过一半则跳过
            dup = any(min(q["end"], o["end"]) - max(q["start"], o["start"])
                      > 0.5 * (q["end"] - q["start"]) for o in points)
            if not dup:
                points.append(q)
    points.sort(key=lambda p: p["start"])
    for n, p in enumerate(points, 1):
        p["id"] = f"kp{n:02d}"
        p["url"] = video_url(sub.get("bvid"), page, p["start"])
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {k: sub.get(k) for k in ("bvid", "page", "title", "owner", "url", "lang", "ai")}
        | {"source_file": sub.get("source_file")},
        "generator": {"model": os.environ.get("MBREAD_MODEL"), "chunks": len(chunks)},
        "points": points,
        "segments": segments,
    }
