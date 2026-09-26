"""毎朝の実行: 収集 → 要約 → 安全チェック → 保存 → サイト生成

使い方:
  python main.py          本番実行(ANTHROPIC_API_KEY が必要)
  python main.py --build  データからサイトだけ作り直す
  python main.py --demo   サンプルデータでデザイン確認(APIもネットも不要)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from src import build, fetch, summarize

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
JST = timezone(timedelta(hours=9))


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _recent_headlines(source_id: str, n: int) -> list[str]:
    """直近の公開済み見出しを、同じ発信元について新しい順にn件集める(予測の材料用)。"""
    headlines = []
    for f in sorted((DATA / "items").glob("*.json"), reverse=True):
        for it in reversed(load_json(f, [])):
            if it.get("source_id") == source_id and it.get("headline"):
                headlines.append(it["headline"])
                if len(headlines) >= n:
                    return list(reversed(headlines))
    return list(reversed(headlines))


def run(cfg: dict) -> None:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    state_path = DATA / "state.json"
    state = load_json(state_path, {})
    lookback = cfg["ai"]["history_lookback"]

    items = fetch.collect(cfg, state)[: cfg["collect"]["max_items_per_run"]]
    published, logs = [], []
    for it in items:
        history = _recent_headlines(it["source_id"], lookback)
        result, log = summarize.process(it, cfg, history)
        logs.append(log)
        if result:
            published.append(result)
        print(f"  [{log.get('status', 'error')}] {it['source_id']} {it['link']}")

    day_path = DATA / "items" / f"{today}.json"
    save_json(day_path, load_json(day_path, []) + published)
    log_path = DATA / "logs" / f"{today}.json"
    save_json(log_path, load_json(log_path, []) + logs)
    save_json(state_path, state)

    held = sum(1 for l in logs if l.get("status") == "held")
    print(f"[done] 公開 {len(published)} / 保留 {held} / 対象 {len(items)}")


def demo(cfg: dict) -> None:
    demo_dir = ROOT / "demo_data"
    today = datetime.now(JST).strftime("%Y-%m-%d")
    sample = [
        {"source_name": "OpenAI", "link": "https://example.com/1", "importance": 5,
         "headline": "(サンプル)新モデルを発表、API料金も改定",
         "fact": "サンプルのfactです。実際の運用では、元記事の要約ではなく「何が起きたか」をMiyaviの言葉でゼロから書きます。",
         "why": "サンプルのwhyです。この動きがなぜ重要かを初心者にも分かるように書きます。",
         "for_agency": "サンプルです。代理店であれば、複数クライアントへの提案コストが下がる可能性があります。",
         "for_solo": "サンプルです。一人起業家であれば、外注していた作業を自分でまかなえる可能性があります。"},
        {"source_name": "NVIDIA", "link": "https://example.com/2", "importance": 4,
         "headline": "(サンプル)データセンター向け新チップの出荷開始",
         "fact": "サンプルのfactです。見出しも元記事のものは使わず、事実ベースで新しく書き直します。",
         "why": "サンプルのwhyです。中長期的な業界への影響を短く説明します。",
         "for_agency": "サンプルです。案件の見積もり単価が下がる材料になるかもしれません。",
         "for_solo": "サンプルです。個人でも高性能な処理を使える環境が広がるかもしれません。"},
    ]
    save_json(demo_dir / f"{today}.json", sample)
    build.build(cfg, items_dir=demo_dir, out_dir=ROOT / "site_demo")


if __name__ == "__main__":
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    cfg["glossary"] = yaml.safe_load((ROOT / "config" / "glossary.yaml").read_text(encoding="utf-8"))["terms"]
    if "--demo" in sys.argv:
        demo(cfg)
    elif "--build" in sys.argv:
        build.build(cfg)
    else:
        run(cfg)
        build.build(cfg)
