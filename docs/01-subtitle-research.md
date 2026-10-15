# 01 · B站字幕获取实测（2026-10-15）

> 规矩：只取字幕和元数据，**绝不下载视频/音频**。所有 yt-dlp 测试均带 `--skip-download`。
> 测试环境：海外/机房 IP 的 Linux box，未登录（无 SESSDATA）。yt-dlp 2026.08.19，Python requests。

## 结论速览

| 路径 | 未登录：人工 CC 字幕 | 未登录：AI 字幕 | 备注 |
|---|---|---|---|
| yt-dlp `--list-subs` / `--write-subs --write-auto-subs` | ❌ | ❌ | 视频网页直接 HTTP 412（风控），带 buvid3 cookie 仍 412，连元数据都拿不到 |
| `x/web-interface/view`（无签名） | — | — | HTTP 412 |
| `x/web-interface/wbi/view`（WBI 签名） | 元数据 ✅，`subtitle.list` 为空 | 同左 | 先访问首页拿 buvid3 后可用；可拿 cid/分P/标题/UP 主 |
| `x/player/wbi/v2`（WBI 签名） | ❌ `subtitles: []` | ❌ `subtitles: []` | 响应明确返回 `need_login_subtitle: true`、`login_mid: 0` |
| `x/player/v2`（无签名） | ❌ `subtitles: []` | ❌ `subtitles: []` | 同上 |

**一句话：2026 年未登录拿不到任何字幕（人工 CC 和 AI 都拿不到），B站在播放器接口里直接标注 `need_login_subtitle: true`。必须提供登录 cookie（SESSDATA）。**

注意：未登录时字幕列表一律为空，所以本次**无法区分**哪些视频「有 CC / 只有 AI / 无字幕」——这三类分组要等拿到 SESSDATA 后再补测。

## 测试的视频

| BV 号 | 标题 | 分区 | 未登录结果 |
|---|---|---|---|
| BV1ys411472E | 【官方双语/合集】线性代数的本质（16P） | 知识 | view/player 均无字幕；yt-dlp 412 |
| BV1VZWc6dECG | 【Re:从零开始的AI学习】第一季总集篇 | 计算机技术 | 同上 |
| BV1SQpX6oETX | 当你在抱怨上升通道受阻时，下沉通道也堵了 | 社科·法律·心理 | 同上，`need_login_subtitle: true` |
| BV1VZpm6EEEG | 大暴雨来了… | 科学科普 | 同上 |
| BV1gaWA6HE7S | 皮莱是谁？2026诺贝尔和平奖背后的政治博弈 | 社科·法律·心理 | view 无 subtitle 字段 |

另外对热门榜前 40 个视频批量调用 `x/player/wbi/v2` 与 `x/player/v2`，**全部** `subtitles: []`。

## 其他观察
- `x/web-interface/wbi/search/type` 未登录返回 `v_voucher`（人机验证），搜索不可用；MVP 只接收用户给的链接即可，不需要搜索。
- WBI 签名：从 `x/web-interface/nav` 的 `wbi_img` 取 img_key+sub_key，按固定置换表取 32 位 mixin key，参数加 `wts` 后排序 urlencode 再 md5 得 `w_rid`。已实现在 `mbread/subtitles.py`。
- 字幕文件（`subtitle_url`，hdslb CDN 上的 JSON）`body[]` 每条含 `from`/`to`/`content`，直接映射为 `start/end/text`。AI 字幕的 `lan` 以 `ai-` 开头（如 `ai-zh`）。
- 412 可能与机房 IP 有关；在 Neil 本机（国内住宅 IP）上 yt-dlp 也许能通过，但字幕仍需登录。

## 推荐方案
1. **主路径：自写 API 客户端**（`mbread/subtitles.py`）：`wbi/view` 取 cid → `player/wbi/v2` 取 `subtitle_url` → 下载字幕 JSON。依赖只有 requests，可控、易于报错。
2. **必须支持 SESSDATA**：通过环境变量 `BILI_SESSDATA` 或 `--sessdata` 传入，本地保存不入库（已加 .gitignore）。优先人工字幕，没有时退回 AI 字幕，并在输出里标 `ai: true`。
3. yt-dlp 作为备选（`--cookies-from-browser` / `--cookies`），不作主路径。
4. 无字幕时清晰报错（退出码 2）；后续可考虑本地 ASR，但那需要音频，违反现有规矩，需 Neil 另行决定。

## 原型用法
```bash
pip install -r requirements.txt
python -m mbread.subtitles --list BV1ys411472E          # 只看字幕轨道
BILI_SESSDATA=xxx python -m mbread.subtitles <BV或链接> [--page N] [--lang zh-CN]
```
输出 JSON：`bvid, cid, page, title, owner, url, lang, lang_doc, ai, segments[{start,end,text}]`。
退出码：0 成功；1 接口/输入错误；2 无字幕（未登录时会提示需要 SESSDATA）。

## 待 Neil 决定
- 是否提供 B站 SESSDATA（建议用小号；存在本地环境变量，不提交）。
- 无字幕视频怎么处理：直接报错跳过，还是允许音频 ASR（会突破「不下载音频」的规矩）。
- 是否值得在国内网络下再测一次 yt-dlp。

## 更新（2026-10-15）：登录方式定为「读本机浏览器 cookie」
Neil 决定不把 SESSDATA 交给 box，`mbread` 在用户自己的 Mac 上运行：
- `--cookies-from-browser {chrome,edge,safari,firefox,brave,chromium,opera,vivaldi,whale}`：调用 `yt_dlp.cookies.extract_cookies_from_browser`（处理 macOS Keychain / Safari binarycookies），只把域名为 `bilibili.com` 或 `*.bilibili.com` 的 cookie 放进内存 session；yt-dlp 日志被静音，cookie 不打印、不写文件。
- `--sessdata` / `BILI_SESSDATA` 保留为备选。
- 运行时在 stderr 提示：已登录（含 cookie 来源）/ 加载了 cookie 但仍未登录（cookie 过期）/ 未登录。
- `--from-file`：离线导入 SRT 或 B站字幕 JSON，输出同样的 `segments` 结构，作为接口失效时的备用路径。

验证情况：
- ✅ box 上：`--from-file` 解析 SRT（含多行字幕）与 B站 JSON；域名过滤（用伪造的 Firefox cookies.sqlite 测试，`.bilibili.com`、`.api.bilibili.com` 被保留，`.google.com`、`evilbilibili.com` 被排除）；cookie 失效/未登录提示；不支持浏览器的报错。
- ❌ 未验证：真实 Mac 上 Chrome/Safari 解密、登录后 `player/wbi/v2` 是否返回人工/AI 字幕、字幕 JSON 下载与解析的线上路径。需 Neil 在 Mac 上跑验证命令。
