"""mbread 命令行。

  mbread anki <BV|链接> --cookies-from-browser chrome -o out.apkg
  mbread anki --from-file subs.srt [BV号] -o out.apkg
  mbread anki --knowledge knowledge.json -o out.apkg
  mbread knowledge <BV|链接> --cookies-from-browser chrome -o knowledge.json
  mbread subs ...   （等同 python -m mbread.subtitles）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import subtitles as st
from .knowledge import KnowledgeError, build_knowledge, validate_knowledge


def _log(m: str) -> None:
    print(m, file=sys.stderr)


def _add_source_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("src", nargs="?", help="BV 号或视频链接")
    ap.add_argument("--cookies-from-browser", dest="browser", metavar="BROWSER")
    ap.add_argument("--browser-profile")
    ap.add_argument("--sessdata")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--lang", help="字幕语言，如 ai-zh；默认人工 zh > ai-zh > 其他")
    ap.add_argument("--from-file", help="离线字幕文件（SRT / B站 JSON）")
    ap.add_argument("--max-chars", type=int, default=6000, help="每块送给 LLM 的字幕字符数")


def _load_subs(a) -> dict:
    if a.from_file:
        sub = st.load_subtitle_file(a.from_file)
        if a.src:
            sub["bvid"] = st.parse_bvid(a.src)
            sub["page"] = a.page
            sub["url"] = f"https://www.bilibili.com/video/{sub['bvid']}?p={a.page}"
        return sub
    if not a.src:
        raise st.SubtitleError("需要 BV 号/链接，或 --from-file，或 --knowledge")
    return st.get_subtitles(a.src, a.page, a.lang, a.sessdata, a.browser, a.browser_profile)


def _knowledge(a) -> dict:
    if getattr(a, "knowledge", None):
        with open(a.knowledge, encoding="utf-8") as f:
            k = json.load(f)
    else:
        sub = _load_subs(a)
        _log(f"字幕 {len(sub['segments'])} 段，开始切知识点…")
        k = build_knowledge(sub, max_chars=a.max_chars, log=_log)
    errs = validate_knowledge(k)
    if errs:
        raise KnowledgeError("knowledge.json 校验失败：\n  " + "\n  ".join(errs))
    if not k["points"]:
        raise KnowledgeError("没有生成任何知识点")
    return k


def _dump(k: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(k, f, ensure_ascii=False, indent=2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mbread", description="记忆面包：B站链接 → Anki 卡组")
    sp = ap.add_subparsers(dest="cmd", required=True)

    pa = sp.add_parser("anki", help="生成 Anki .apkg")
    _add_source_args(pa)
    pa.add_argument("--knowledge", help="直接用已有 knowledge.json")
    pa.add_argument("-o", "--output", default="mbread.apkg")
    pa.add_argument("--deck-name")
    pa.add_argument("--save-knowledge", help="同时保存 knowledge.json（默认 <output>.knowledge.json）")

    pk = sp.add_parser("knowledge", help="只生成 knowledge.json")
    _add_source_args(pk)
    pk.add_argument("-o", "--output", default="knowledge.json")

    pv = sp.add_parser("validate", help="校验 knowledge.json")
    pv.add_argument("path")

    sp.add_parser("subs", help="获取字幕（参数同 python -m mbread.subtitles）", add_help=False)

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "subs":
        return st.main(argv[1:])
    a = ap.parse_args(argv)
    try:
        if a.cmd == "validate":
            with open(a.path, encoding="utf-8") as f:
                errs = validate_knowledge(json.load(f))
            for e in errs:
                _log(e)
            _log("校验通过" if not errs else f"{len(errs)} 个问题")
            return 0 if not errs else 1
        k = _knowledge(a)
        if a.cmd == "knowledge":
            _dump(k, a.output)
            _log(f"已写入 {a.output}：{len(k['points'])} 个知识点")
            return 0
        from .anki import write_apkg
        if not a.knowledge:
            kp = a.save_knowledge or os.path.splitext(a.output)[0] + ".knowledge.json"
            _dump(k, kp)
            _log(f"knowledge.json 已保存：{kp}")
        n = write_apkg(k, a.output, a.deck_name)
        _log(f"已生成 {a.output}：{len(k['points'])} 个知识点，{n} 张卡")
        return 0
    except st.NoSubtitleError as e:
        _log(f"无字幕: {e}"); return 2
    except (st.SubtitleError, KnowledgeError) as e:
        _log(f"错误: {e}"); return 1


if __name__ == "__main__":
    sys.exit(main())
