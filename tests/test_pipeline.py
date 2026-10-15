import copy
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from mbread import knowledge as kn
from mbread.anki import write_apkg, MODEL_ID, build_deck
from mbread.subtitles import load_subtitle_file, pick_track
from mbread.cli import main as cli

FX = Path(__file__).parent / "fixtures"
SUB = load_subtitle_file(str(FX / "feynman_synthetic.bili.json"))
SUB.update(bvid="BV1xxxxxxxxx", page=2, title="费曼学习法", owner="测试UP主")
K = json.loads((FX / "feynman_knowledge.json").read_text(encoding="utf-8"))


def test_pick_track_priority():
    t = [{"lan": "ai-en"}, {"lan": "ai-zh"}, {"lan": "en-US"}]
    assert pick_track(t)["lan"] == "ai-zh"
    assert pick_track(t + [{"lan": "zh-CN"}])["lan"] == "zh-CN"
    assert pick_track([{"lan": "ai-ja"}, {"lan": "en"}])["lan"] == "en"
    assert pick_track(t, "ai-en")["lan"] == "ai-en"
    assert pick_track(t, "ai-ko") is None


def test_handwritten_knowledge_valid():
    assert kn.validate_knowledge(K) == []


@pytest.mark.parametrize("mut,msg", [
    (lambda p: p.update(start=p["start"] + 0.37), "不是任何字幕段的开始时间"),
    (lambda p: p.update(end=9999.0), "不是任何字幕段的结束时间"),
    (lambda p: p.update(end=p["start"]), "start/end 非法"),
    (lambda p: p.update(quote="费曼说学习要靠天赋"), "quote 不在"),
])
def test_validate_catches_bad_timestamps(mut, msg):
    k = copy.deepcopy(K)
    mut(k["points"][0])
    assert any(msg in e for e in kn.validate_knowledge(k))


def test_chunking_covers_all_with_overlap():
    ch = kn.chunk_segments(SUB["segments"], max_chars=300, overlap=2)
    assert len(ch) > 1
    assert set().union(*map(set, ch)) == set(range(len(SUB["segments"])))
    for a, b in zip(ch, ch[1:]):
        assert a[-2:] == b[:2]


def make_mock(log):
    """模拟 LLM：每块返回一个合法知识点 + 一个越界知识点 + 一个改写引用的知识点。"""
    def chat(system, user):
        log.append(user)
        ids = [int(l.split("]")[0][1:]) for l in user.splitlines() if l.startswith("[")]
        a, b = ids[0], min(ids[0] + 2, ids[-1])
        return "```json\n" + json.dumps({"points": [
            {"title": f"块{ids[0]}", "summary": "s", "start_seg": a, "end_seg": b,
             "quote": "", "cards": [{"q": "问", "a": "答"}]},
            {"title": "越界", "summary": "s", "start_seg": ids[-1] + 50, "end_seg": ids[-1] + 51,
             "quote": "x", "cards": [{"q": "q", "a": "a"}]},
            {"title": "改写引用", "summary": "s", "start_seg": b, "end_seg": ids[-1],
             "quote": "这句话字幕里根本没有", "cards": [{"q": "q2", "a": "a2"}]},
        ]}, ensure_ascii=False) + "\n```"
    return chat


def test_build_knowledge_with_mock_llm():
    calls = []
    k = kn.build_knowledge(SUB, chat=make_mock(calls), max_chars=300)
    assert len(calls) == len(kn.chunk_segments(SUB["segments"], 300)) > 1
    assert "越界" not in [p["title"] for p in k["points"]]
    assert kn.validate_knowledge(k) == []          # 时间戳全部对齐真实 segment
    for p in k["points"]:
        assert p["url"] == f"https://www.bilibili.com/video/BV1xxxxxxxxx?p=2&t={int(p['start'])}"
        if p["title"] == "改写引用":
            assert "根本没有" not in p["quote"]       # 被替换为字幕原文
    assert [p["id"] for p in k["points"]] == [f"kp{i:02d}" for i in range(1, len(k["points"]) + 1)]


def test_anki_render(tmp_path):
    out = tmp_path / "t.apkg"
    n = write_apkg(K, str(out))
    assert n == 5
    with zipfile.ZipFile(out) as z:
        z.extract("collection.anki2", tmp_path)
    db = sqlite3.connect(tmp_path / "collection.anki2")
    rows = db.execute("select flds, tags, mid from notes").fetchall()
    assert len(rows) == 5 and all(r[2] == MODEL_ID for r in rows)
    f = rows[0][0].split("\x1f")
    assert f[0] == "费曼学习法的核心判断标准是什么？"
    assert '<a href="https://www.bilibili.com/video/BV1xxxxxxxxx?p=1&amp;t=' in f[3]
    assert "测试UP主" in f[4] and "BV1xxxxxxxxx" in rows[0][1]
    # 稳定 id：两次构建 deck id 与 guid 一致
    d1, d2 = build_deck(K), build_deck(K)
    assert d1.deck_id == d2.deck_id
    assert [x.guid for x in d1.notes] == [x.guid for x in d2.notes]


def test_cli_from_knowledge_and_from_file(tmp_path, monkeypatch):
    out = tmp_path / "a.apkg"
    assert cli(["anki", "--knowledge", str(FX / "feynman_knowledge.json"), "-o", str(out)]) == 0
    assert out.stat().st_size > 0
    monkeypatch.setattr(kn, "openai_chat", lambda s, u: make_mock([])(s, u))
    out2 = tmp_path / "b.apkg"
    assert cli(["anki", "--from-file", str(FX / "feynman_synthetic.bili.json"), "BV1xxxxxxxxx",
                "--max-chars", "300", "-o", str(out2)]) == 0
    k = json.loads((tmp_path / "b.knowledge.json").read_text(encoding="utf-8"))
    assert k["source"]["bvid"] == "BV1xxxxxxxxx" and kn.validate_knowledge(k) == []


def test_missing_llm_env(monkeypatch):
    for v in ("MBREAD_BASE_URL", "MBREAD_API_KEY", "MBREAD_MODEL"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(kn.KnowledgeError, match="MBREAD_BASE_URL"):
        kn.llm_config()


def test_openai_chat_http(monkeypatch):
    """用本地假服务器验证 OpenAI 兼容请求格式及 response_format 400 回退。"""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers["Authorization"], body))
            if "response_format" in body:
                self.send_response(400); self.end_headers(); self.wfile.write(b"no"); return
            out = json.dumps({"choices": [{"message": {"content": '{"points": []}'}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("MBREAD_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1/")
    monkeypatch.setenv("MBREAD_API_KEY", "k")
    monkeypatch.setenv("MBREAD_MODEL", "m")
    assert kn.openai_chat("sys", "usr") == '{"points": []}'
    srv.shutdown()
    assert seen[0][0] == "/v1/chat/completions" and seen[0][1] == "Bearer k"
    assert seen[1][2]["model"] == "m" and "response_format" not in seen[1][2]
