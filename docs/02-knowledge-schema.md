# 02 · knowledge.json（知识点中间层）

流程：B站字幕 segments → `mbread/knowledge.py`（LLM 切知识点 + 代码校验）→ **knowledge.json** → Anki（`mbread/anki.py`）/ 小红书卡片 / 图文总结。

## Schema（schema_version = 1）
```jsonc
{
  "schema_version": 1,
  "source": {                    // 出处，三种输出都要带
    "bvid": "BV1SQpX6oETX", "page": 1,
    "title": "视频标题", "owner": "UP主",
    "url": "https://www.bilibili.com/video/BV…?p=1",
    "lang": "ai-zh", "ai": true,  // 字幕语言，是否 AI 字幕
    "source_file": null           // 用 --from-file 时为文件名
  },
  "generator": {"model": "deepseek-chat", "chunks": 3},
  "points": [{
    "id": "kp01",                 // 按时间排序的稳定编号
    "title": "≤20字标题",
    "summary": "1-3 句，只基于字幕",
    "start": 12.3, "end": 95.0,   // 秒；必须等于某个字幕段的 start / end
    "seg_range": [3, 27],         // 对应 segments 下标（含两端）
    "quote": "字幕原文逐字摘抄",
    "cards": [{"q": "问题", "a": "答案"}],
    "url": "https://www.bilibili.com/video/BV…?p=1&t=12"   // 可点击跳转的时间戳
  }],
  "segments": [{"start": 0.0, "end": 2.5, "text": "…"}]   // 原始字幕，用于校验和回溯
}
```

## 防止编造的约束（代码层）
- 模型只看到带段号的字幕，返回 `start_seg/end_seg`（段号），**时间戳由代码根据真实段计算**；段号不在本块里的知识点直接丢弃。
- `quote` 归一化（去掉空白和标点）后必须是对应段落（前后各放宽 1 段）字幕原文的子串，否则替换为该段字幕原文。
- `validate_knowledge()`（`mbread validate k.json`）：字段齐全；start<end；start、end 分别对齐某个 segment 的 start、end（±0.01s）；不超出字幕范围；quote 在对应段落中。手写或修改过的 knowledge.json 也会经过同样的校验。
- 提示词要求只用字幕内容；但「答案是否忠实」目前**只靠提示词**，代码只校验时间戳和原话。

## 分块
按约 6000 字符（`--max-chars`）一块切分，相邻块重叠 3 段；块间如有知识点时间重叠超过一半，就去重。

## LLM 配置（OpenAI 兼容）
| 变量 | 例子 |
|---|---|
| `MBREAD_BASE_URL` | `https://api.deepseek.com/v1` · `https://dashscope.aliyuncs.com/compatible-mode/v1` · `http://localhost:11434/v1`（Ollama） |
| `MBREAD_API_KEY` | 服务商的 key；Ollama 填任意值 |
| `MBREAD_MODEL` | `deepseek-chat` · `qwen-plus` · `qwen2.5:14b` |

请求会带 `response_format: json_object`；后端返回 400 时，自动去掉它重试一次。

## Anki 输出
- 正面：知识点标题 + 问题；背面：答案、原文引用、`▶ mm:ss–mm:ss 跳到B站原片`（`?p=N&t=秒`）、出处（《标题》· UP主 · BV号）。
- 固定 model id `1729384001`；deck id 由 BV号+分P 哈希得出；note guid 由 BV号+知识点id+卡序号+问题得出。所以重新生成后再导入，会更新已有卡片，不会重复。
- 卡组名：`记忆面包::<标题>`；tags：`mbread`、BV号、AI 字幕时加 `ai字幕`。
