"""用本地假 OpenAI 兼容服务器测试推理模型的各种返回。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mbread import knowledge as kn


@pytest.fixture
def server(monkeypatch):
    state = {"replies": [], "seen": [], "reject": set()}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["seen"].append(body)
            if state["reject"] & body.keys():
                self.send_response(400); self.end_headers(); self.wfile.write(b"unknown field"); return
            msg, fr = state["replies"].pop(0) if len(state["replies"]) > 1 else state["replies"][0]
            out = json.dumps({"choices": [{"message": msg, "finish_reason": fr}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("MBREAD_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setenv("MBREAD_API_KEY", "k")
    monkeypatch.setenv("MBREAD_MODEL", "/models/Qwen-MLX-4bit")
    for v in ("MBREAD_THINKING", "MBREAD_MAX_TOKENS", "MBREAD_TIMEOUT"):
        monkeypatch.delenv(v, raising=False)
    yield state
    srv.shutdown()


OK = '{"points": []}'


def test_defaults_disable_thinking_and_max_tokens(server):
    server["replies"] = [({"content": OK}, "stop")]
    assert kn.openai_chat("s", "u") == OK
    b = server["seen"][0]
    assert b["chat_template_kwargs"] == {"enable_thinking": False}
    assert b["max_tokens"] == 8192 and "reasoning_effort" not in b


def test_thinking_env_and_max_tokens_env(server, monkeypatch):
    monkeypatch.setenv("MBREAD_THINKING", "1")
    monkeypatch.setenv("MBREAD_MAX_TOKENS", "16384")
    server["replies"] = [({"content": OK}, "stop")]
    kn.openai_chat("s", "u")
    assert "chat_template_kwargs" not in server["seen"][0]
    assert server["seen"][0]["max_tokens"] == 16384


def test_backend_rejects_extra_fields(server):
    server["reject"] = {"chat_template_kwargs"}
    server["replies"] = [({"content": OK}, "stop")]
    assert kn.openai_chat("s", "u") == OK
    assert len(server["seen"]) == 3 and server["seen"][-1].keys() >= {"model", "max_tokens"}
    assert "chat_template_kwargs" not in server["seen"][-1]


def test_content_none_finish_length(server):
    server["replies"] = [({"content": None, "reasoning": "嗯，我想想……" * 50}, "length")]
    with pytest.raises(kn.KnowledgeError, match="MBREAD_MAX_TOKENS"):
        kn.openai_chat("s", "u")


def test_content_none_json_in_reasoning(server):
    server["replies"] = [({"content": None, "reasoning": '先分析……最终答案：{"points": [{"title": "x"}]}'}, "stop")]
    assert json.loads(kn.openai_chat("s", "u")) == {"points": [{"title": "x"}]}


def test_content_none_reasoning_content_field(server):
    server["replies"] = [({"content": "", "reasoning_content": '{"points": []}'}, "stop")]
    assert kn.openai_chat("s", "u") == OK


def test_empty_then_retry_succeeds(server):
    server["replies"] = [({"content": None, "reasoning": "没有json"}, "stop"), ({"content": OK}, "stop")]
    assert kn.openai_chat("s", "u") == OK
    assert len(server["seen"]) == 2


def test_empty_twice_raises(server):
    server["replies"] = [({"content": None}, "stop")]
    with pytest.raises(kn.KnowledgeError, match="两次都返回空内容"):
        kn.openai_chat("s", "u")


def test_think_tags_stripped(server):
    server["replies"] = [({"content": "<think>先想想 {\"bad\": 1}</think>\n```json\n" + OK + "\n```"}, "stop")]
    out = kn.openai_chat("s", "u")
    assert "think" not in out and kn.parse_json(out) == {"points": []}


def test_parse_json_none():
    with pytest.raises(kn.KnowledgeError):
        kn.parse_json(None)
    assert kn.parse_json("</think>" + OK) == {"points": []}


def test_timeout_message(server, monkeypatch):
    import requests
    def boom(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setenv("MBREAD_TIMEOUT", "5")
    with pytest.raises(kn.KnowledgeError, match="MBREAD_TIMEOUT"):
        kn.openai_chat("s", "u")
