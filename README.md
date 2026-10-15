# jiyi-mianbao
记忆面包：一条B站链接，同时生成带时间戳的 Anki 卡组和小红书卡片 (mbread)

## 快速开始（macOS）

```bash
git clone https://github.com/neardws/jiyi-mianbao.git
cd jiyi-mianbao
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
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
