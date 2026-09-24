"""転載・翻案リスクと、断定的な言い切りを下げるための機械チェック。
法的判断を代替するものではなく、「元の言い回しに近すぎないか」「言い切っていないか」を数値・語で弾く安全装置。
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\W_]+", "", text)


def _ngrams(text: str, n: int) -> set[str]:
    return {text[i:i + n] for i in range(max(len(text) - n + 1, 0))}


def overlap_ratio(out: str, src: str, n: int) -> float:
    """出力の n-gram のうち、元文にも含まれる割合。"""
    a, b = _ngrams(_norm(out), n), _ngrams(_norm(src), n)
    return len(a & b) / len(a) if a else 0.0


def longest_common_run(out: str, src: str) -> int:
    """出力と元文で連続して一致する最長の文字数。"""
    a, b = _norm(out), _norm(src)
    if not a or not b:
        return 0
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size


def check(result: dict, item: dict, cfg: dict) -> list[str]:
    """問題点のリストを返す。空なら合格。"""
    s = cfg["safety"]
    problems = []
    headline, fact, why, for_agency, for_solo = (
        result.get(k, "") for k in ("headline", "fact", "why", "for_agency", "for_solo")
    )
    source_text = f"{item.get('title', '')} {item.get('excerpt', '')}"

    if not headline or not fact or not why or not for_agency or not for_solo:
        problems.append("headline・fact・why・for_agency・for_soloのいずれかが空")
    if len(headline) > s["headline_max_chars"]:
        problems.append(f"見出しが長すぎる({len(headline)}字 > {s['headline_max_chars']}字)")
    if len(fact) > s["fact_max_chars"]:
        problems.append(f"factが長すぎる({len(fact)}字 > {s['fact_max_chars']}字)")
    if len(why) > s["why_max_chars"]:
        problems.append(f"whyが長すぎる({len(why)}字 > {s['why_max_chars']}字)")
    for label, text in (("for_agency", for_agency), ("for_solo", for_solo)):
        if len(text) > s["impact_max_chars"]:
            problems.append(f"{label}が長すぎる({len(text)}字 > {s['impact_max_chars']}字)")
    if not item.get("link", "").startswith("http"):
        problems.append("元記事リンクがない")

    for label, text in (("見出し", headline), ("fact", fact)):
        ratio = overlap_ratio(text, source_text, s["ngram_size"])
        run = longest_common_run(text, source_text)
        if ratio > s["ngram_overlap_max"]:
            problems.append(f"{label}が元文と似すぎている(一致率 {ratio:.0%})")
        if run > s["common_run_max"]:
            problems.append(f"{label}に元文と同じ文字列が {run} 字続いている")

    for label, text in (("for_agency", for_agency), ("for_solo", for_solo)):
        if not text:
            continue
        if any(w in text for w in s["absolute_words"]):
            problems.append(f"{label}に断定的な言い切り表現が含まれている")
        if not any(w in text for w in s["hedge_words"]):
            problems.append(f"{label}に断定を避ける表現(可能性がある、など)が含まれていない")

    return problems
