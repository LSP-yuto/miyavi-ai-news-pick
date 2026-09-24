"""Claude Haiku で重要度判定・要約・影響コメントを作る。安全チェック不合格なら理由を渡して書き直させる。"""
from __future__ import annotations

import json
import os
import re

import requests

from . import safety

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = """あなたはAIビジネスニュースの編集者です。読者は、AIや自動化を使って個人でビジネスをしている日本人です。
渡されるのは記事の「タイトル」と「短い概要」だけです。ここに書かれている事実だけを使ってください。推測や、書かれていない数字は足さないでください。

守るルール:
- 元の文章の言い回しや語順をなぞらず、事実だけを自分の言葉で書き直す
- 元のタイトルをそのまま訳したり並べ替えたりせず、見出しは新しく書く
- 見出しは{h}字以内、要約は{s}字以内の日本語
- impact は「個人でビジネスをしている人にとって何が変わるか」を1文で。煽らず具体的に
- importance は1〜5。AIの主要企業の新製品・価格・提携・大型投資・規制は高く、小さな事例紹介や採用情報は低く

出力はJSONのみ。前置きやコードブロックは付けない:
{{"importance": 1〜5の整数, "headline": "...", "summary": "...", "impact": "...", "tags": ["企業名や人名を最大3つ"]}}"""


def _call(messages: list[dict], cfg: dict) -> str:
    key = os.environ["ANTHROPIC_API_KEY"]
    s = cfg["safety"]
    r = requests.post(
        API_URL,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": cfg["ai"]["model"],
            "max_tokens": 600,
            "system": SYSTEM.format(h=s["headline_max_chars"], s=s["summary_max_chars"]),
            "messages": messages,
        },
        timeout=60,
    )
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


def _parse(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def process(item: dict, cfg: dict) -> tuple[dict | None, dict]:
    """(公開用データ or None, ログ) を返す。"""
    prompt = (
        f"情報源: {item['source_name']}\n"
        f"タイトル: {item['title']}\n"
        f"概要: {item['excerpt'] or '(概要なし。タイトルの事実だけで書く)'}"
    )
    messages = [{"role": "user", "content": prompt}]
    log = {"link": item["link"], "source": item["source_id"], "attempts": []}

    for attempt in range(cfg["ai"]["max_retries"] + 1):
        try:
            raw = _call(messages, cfg)
            result = _parse(raw)
        except (requests.RequestException, json.JSONDecodeError, KeyError) as ex:
            log["attempts"].append({"error": str(ex)})
            continue

        problems = safety.check(result, item, cfg)
        log["attempts"].append({"result": result, "problems": problems})
        if not problems:
            importance = int(result.get("importance", 0) or 0)
            if importance < cfg["collect"]["min_importance"]:
                log["status"] = "skipped_low_importance"
                return None, log
            log["status"] = "published"
            return {
                "source_id": item["source_id"],
                "source_name": item["source_name"],
                "link": item["link"],
                "published": item.get("published"),
                "importance": importance,
                "headline": result["headline"].strip(),
                "summary": result["summary"].strip(),
                "impact": result["impact"].strip(),
                "tags": [str(t) for t in result.get("tags", [])][:3],
            }, log

        # 不合格:理由を伝えて書き直させる
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "次の問題があります。元の言い回しから離れて、事実だけを別の表現で書き直してください:\n- "
             + "\n- ".join(problems)},
        ]

    log["status"] = "held"  # 公開せず保留
    return None, log
