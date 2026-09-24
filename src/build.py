"""data/items/*.json から静的サイト(site/)を生成する。"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
WEEK = "月火水木金土日"


def _label(d: str) -> str:
    y, m, dd = map(int, d.split("-"))
    return f"{m}月{dd}日({WEEK[date(y, m, dd).weekday()]})"


def _load_days(items_dir: Path) -> list[dict]:
    days = []
    for f in sorted(items_dir.glob("*.json"), reverse=True):
        items = json.loads(f.read_text(encoding="utf-8"))
        if items:
            items.sort(key=lambda x: x.get("importance", 0), reverse=True)
            days.append({"date": f.stem, "label": _label(f.stem), "items": items})
    return days


def build(cfg: dict, items_dir: Path | None = None, out_dir: Path | None = None) -> None:
    items_dir = items_dir or ROOT / "data" / "items"
    out = out_dir or ROOT / "site"
    if out.exists():
        shutil.rmtree(out)
    (out / "archive").mkdir(parents=True)

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("page.html")
    site = cfg["site"]
    days = _load_days(items_dir)

    top = days[: site["top_days"]]
    if top:
        n = len(top[0]["items"])
        hero_title, hero_text = top[0]["label"], f"今朝のピックは{n}件です。{site['description']}"
    else:
        hero_title, hero_text = site["title"], site["description"]
    (out / "index.html").write_text(tpl.render(
        mode="top", site=site, root="", page_title=site["title"],
        hero_title=hero_title, hero_text=hero_text, days=top), encoding="utf-8")

    for d in days:
        (out / "archive" / f"{d['date']}.html").write_text(tpl.render(
            mode="day", site=site, root="../", page_title=f"{d['label']}のピック | {site['title']}",
            hero_title=d["label"], hero_text=f"この日のピックは{len(d['items'])}件です。", days=[d]),
            encoding="utf-8")

    (out / "archive" / "index.html").write_text(tpl.render(
        mode="archive_index", site=site, root="../", page_title=f"過去のピック | {site['title']}",
        dates=[{"file": f"{d['date']}.html", "label": d["label"], "count": len(d["items"])} for d in days]),
        encoding="utf-8")
    (out / ".nojekyll").write_text("")
    print(f"[build] {len(days)}日分のページを生成しました → {out}")
