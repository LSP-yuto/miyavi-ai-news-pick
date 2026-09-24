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


def run(cfg: dict) -> None:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    state_path = DATA / "state.json"
    state = load_json(state_path, {})

    items = fetch.collect(cfg, state)[: cfg["collect"]["max_items_per_run"]]
    published, logs = [], []
    for it in items:
        result, log = summarize.process(it, cfg)
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
         "summary": "サンプルの要約文です。実際の運用では、元記事のタイトルと概要から事実だけを抜き出し、150字以内でまとめます。",
         "impact": "API経由の自動化ツールを使っている人は、月々のコストを見直すタイミングです。"},
        {"source_name": "NVIDIA", "link": "https://example.com/2", "importance": 4,
         "headline": "(サンプル)データセンター向け新チップの出荷開始",
         "summary": "サンプルの要約文です。見出しも元記事のものは使わず、AIが事実ベースで新しく書き直します。",
         "impact": "中長期ではAIサービスの利用料が下がる方向の材料です。"},
    ]
    save_json(demo_dir / f"{today}.json", sample)
    build.build(cfg, items_dir=demo_dir, out_dir=ROOT / "site_demo")


if __name__ == "__main__":
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    if "--demo" in sys.argv:
        demo(cfg)
    elif "--build" in sys.argv:
        build.build(cfg)
    else:
        run(cfg)
        build.build(cfg)
