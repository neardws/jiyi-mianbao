# jiyi-mianbao
记忆面包：一条B站链接，同时生成带时间戳的 Anki 卡组和小红书卡片 (mbread)

## 快速开始（macOS）

**需要 Python 3.10+**（yt-dlp 新版不支持 3.9；macOS/Xcode 自带的 `python3` 是 3.9，不能用）。

```bash
brew install python@3.12            # 没有 Homebrew 先装：https://brew.sh
git clone https://github.com/neardws/jiyi-mianbao.git
cd jiyi-mianbao
python3.12 -m venv .venv && source .venv/bin/activate
python --version                    # 应显示 3.12.x
pip install -e .                    # 安装依赖和 mbread 命令
# 先在 Chrome 里登录 bilibili.com，然后验证（首次会弹钥匙串授权，点「允许」）：
python -m mbread.subtitles BV1ys411472E --cookies-from-browser chrome --list
```

stderr 应出现「已登录 B站」，stdout 的 `tracks` 里列出字幕轨道。

### 字幕获取 `mbread.subtitles`

```bash
# 拿带时间戳的字幕 JSON（优先人工字幕，没有则 AI 字幕）
python -m mbread.subtitles <BV号或链接> --cookies-from-browser chrome [--page N] [--lang zh-CN]
# 其他浏览器：safari / edge / firefox / brave / chromium …；多 profile 用 --browser-profile "Profile 1"
# 备选：手动提供 SESSDATA
BILI_SESSDATA=xxx python -m mbread.subtitles <BV号>
# 离线备用：导入 SRT 或 B站字幕 JSON（可附 BV 号作为出处）
python -m mbread.subtitles --from-file tests/fixtures/sample.srt BV1ys411472E
```

- 浏览器 cookie 通过 yt-dlp 库读取（支持 macOS Keychain 解密），**只保留 .bilibili.com 域，只在内存里用，不打印、不落盘**。
- Safari：需在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」里给终端授权。
- 退出码：0 成功；1 错误；2 无字幕。

### 生成 Anki 卡组 `mbread anki`

需要一个 OpenAI 兼容的 LLM（DeepSeek、通义千问、本地 Ollama 都行）：

```bash
export MBREAD_BASE_URL=https://api.deepseek.com/v1
export MBREAD_API_KEY=sk-...
export MBREAD_MODEL=deepseek-chat

mbread anki BV1SQpX6oETX --cookies-from-browser chrome -o out.apkg
# 同时生成 out.knowledge.json（知识点中间层，schema 见 docs/02-knowledge-schema.md）
mbread anki --from-file subs.srt BV1SQpX6oETX -o out.apkg     # 离线字幕
mbread anki --knowledge out.knowledge.json -o out.apkg         # 改过 knowledge.json 后重新出卡
mbread knowledge BV1SQpX6oETX --cookies-from-browser chrome -o k.json
mbread validate k.json                                          # 校验时间戳和引用
```

#### 本地模型：mlx-lm（Apple Silicon）

```bash
pip install mlx-lm                       # 可以装在单独的 venv 里
mlx_lm.server --model /path/to/Qwen3.8-27B-MLX-4bit --port 8080   # 另开一个终端，保持运行

export MBREAD_BASE_URL=http://127.0.0.1:8080/v1
export MBREAD_API_KEY=local              # 随便填
export MBREAD_MODEL=/path/to/Qwen3.8-27B-MLX-4bit   # 与 --model 一致
mbread anki BV1SQpX6oETX --cookies-from-browser chrome -o out.apkg
```

可选环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `MBREAD_MAX_TOKENS` | 8192 | 单次输出上限；报「被 max_tokens 截断」时调大 |
| `MBREAD_TIMEOUT` | 600 | 单块请求超时（秒）；本地大模型一块可能要几分钟 |
| `MBREAD_THINKING` | 关 | 设为 `1` 时开启推理模型的思考。默认发送 `chat_template_kwargs: {enable_thinking: false}`，后端不支持时会自动去掉重试 |

推理模型如果把输出放在 `reasoning` / `reasoning_content` 字段，或者带 `<think>…</think>`，mbread 会自动剔除思考过程，并从中提取 JSON。

把 `out.apkg` 双击导入 Anki。背面的时间戳链接会跳到 B站对应秒数。重新生成后再导入会更新已有卡片，不会重复。

**注意**：读取 Chrome cookie 必须在你自己的终端里运行（远程或代理进程会被 macOS 隐私权限拦截，报 Operation not permitted）。

开发测试：`pip install -e ".[dev]" && pytest -q`
