"""Claude Haiku で「事実の要点・なぜ重要か・代理店/一人起業家むけの示唆」を作る。

元記事の文章を要約(パラフレーズ)するのではなく、タイトルと概要から読み取れる
「事実」だけを材料に、Miyaviの言葉でゼロから書かせる設計にしている。
安全チェック不合格なら理由を渡して書き直させる。
"""
from __future__ import annotations

import json
import os
import re

import requests

from . import safety

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = """あなたは「Miyavi」というAI自動化ツールの中の人です。読者はAIや自動化を使って個人でビジネスをしている日本人で、
「代理店を経営している人」と「一人で起業している人」の2種類がいます。

渡されるのは、ある発信元の「タイトル」と「短い概要」、そして同じ発信元の直近の見出し(参考情報)です。
ここに書かれている事実だけを使ってください。推測や、書かれていない数字は足さないでください。

やってはいけないこと:
- 元の文章の言い回し・語順を要約・翻訳としてなぞること。「記事を要約する」のではなく「その事実を材料にMiyaviが考えたことを書く」
- 元のタイトルをそのまま訳したり並べ替えたりすること。見出しは事実から新しく書く
- 断定的な言い切り({absolute})。予測やビジネスへの示唆は必ずぼかした表現({hedge}などの語)を使う

出力する項目:
- headline: 見出し。{h}字以内
- fact: 「何が起きたか」を自分の言葉で。{f}字以内
- why: 「なぜ重要か」を初心者にも分かるように。{w}字以内
- for_agency: 代理店を経営している人にとっての示唆・使い方の予測。{i}字以内、断定を避ける
- for_solo: 一人で起業している人にとっての示唆・使い方の予測。{i}字以内、断定を避ける
- importance: 1〜5。AIの主要企業の新製品・価格・提携・大型投資・規制は高く、小さな事例紹介や採用情報は低く

出力はJSONのみ。前置きやコードブロックは付けない:
{{"importance": 1〜5の整数, "headline": "...", "fact": "...", "why": "...", "for_agency": "...", "for_solo": "...", "tags": ["企業名や人名を最大3つ"]}}"""


def _call(messages: list[dict], cfg: dict) -> str:
    key = os.environ["ANTHROPIC_API_KEY"]
    s = cfg["safety"]
    system = SYSTEM.format(
        h=s["headline_max_chars"], f=s["fact_max_chars"], w=s["why_max_chars"], i=s["impact_max_chars"],
        absolute="/".join(s["absolute_words"]), hedge="/".join(s["hedge_words"]),
    )
    r = requests.post(
        API_URL,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": cfg["ai"]["model"],
            "max_tokens": 800,
            "system": system,
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


def process(item: dict, cfg: dict, history: list[str] | None = None) -> tuple[dict | None, dict]:
    """(公開用データ or None, ログ) を返す。history は同じ発信元の直近の見出し(古い→新しい順)。"""
    history_text = "(なし。この発信元は今回が初めて)"
    if history:
        history_text = "\n".join(f"- {h}" for h in history)

    prompt = (
        f"情報源: {item['source_name']}\n"
        f"タイトル: {item['title']}\n"
        f"概要: {item['excerpt'] or '(概要なし。タイトルの事実だけで書く)'}\n\n"
        f"この発信元の直近の見出し(参考。予測の材料にしてよいが、内容を混同しないこと):\n{history_text}"
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
                "fact": result["fact"].strip(),
                "why": result["why"].strip(),
                "for_agency": result["for_agency"].strip(),
                "for_solo": result["for_solo"].strip(),
                "tags": [str(t) for t in result.get("tags", [])][:3],
            }, log

        # 不合格:理由を伝えて書き直させる
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "次の問題があります。元の言い回しから離れ、事実だけを材料にMiyaviの言葉で書き直してください:\n- "
             + "\n- ".join(problems)},
        ]

    log["status"] = "held"  # 公開せず保留
    return None, log
