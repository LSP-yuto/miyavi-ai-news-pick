"""各ソースから新着記事を集める。本文は取得せず、タイトルと短い概要だけを扱う。"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; AINewsPick/1.0; +https://github.com/)"
TIMEOUT = 20


def _clean(text: str, limit: int) -> str:
    text = BeautifulSoup(html.unescape(text or ""), "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def fetch_rss(src: dict, cfg: dict) -> list[dict]:
    limit = cfg["safety"]["input_max_chars"]
    max_age = timedelta(days=cfg["collect"]["max_age_days"])
    now = datetime.now(timezone.utc)
    feed = feedparser.parse(_get(src["url"]).content)
    items = []
    for e in feed.entries:
        link = e.get("link")
        if not link:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        published = datetime.fromtimestamp(time.mktime(ts), timezone.utc) if ts else None
        if published and now - published > max_age:
            continue
        items.append({
            "source_id": src["id"],
            "source_name": src["name"],
            "link": link,
            "title": _clean(e.get("title", ""), 200),
            "excerpt": _clean(e.get("summary", ""), limit),
            "published": published.isoformat() if published else None,
        })
    return items


def _meta_description(url: str, limit: int) -> str:
    """記事ページの meta description(発行元が用意した短い紹介文)だけを取る。"""
    try:
        soup = BeautifulSoup(_get(url).text, "html.parser")
    except requests.RequestException:
        return ""
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return _clean(tag["content"], limit)
    return ""


def fetch_html(src: dict, cfg: dict, known: set[str]) -> list[dict]:
    """一覧ページのリンクを差分検知。新しいリンクだけ meta description を取りに行く。"""
    limit = cfg["safety"]["input_max_chars"]
    soup = BeautifulSoup(_get(src["url"]).text, "html.parser")
    base_host = urlparse(src["url"]).netloc
    seen_here, items = set(), []
    for a in soup.find_all("a", href=True):
        link = urljoin(src["url"], a["href"]).split("#")[0]
        if urlparse(link).netloc != base_host:
            continue
        if src.get("link_pattern") not in link or link.rstrip("/") == src["url"].rstrip("/"):
            continue
        title = _clean(a.get_text(" "), 200)
        if len(title) < 8 or link in seen_here:
            continue
        seen_here.add(link)
        items.append({
            "source_id": src["id"],
            "source_name": src["name"],
            "link": link,
            "title": title,
            "excerpt": "",
            "published": None,
        })
    # 取得の負荷を抑えるため、未処理の記事だけ概要を取る
    for it in items:
        if it["link"] not in known:
            it["excerpt"] = _meta_description(it["link"], limit)
            time.sleep(1)
    return items


def collect(cfg: dict, state: dict) -> list[dict]:
    """許可済みソースから未処理の記事を返す。state['seen'] を更新する。"""
    seen: dict[str, list[str]] = state.setdefault("seen", {})
    boot_n = cfg["collect"]["bootstrap_items"]
    new_items = []
    for src in cfg["sources"]:
        if not src.get("approved"):
            continue
        known = set(seen.get(src["id"], []))
        try:
            if src["type"] == "rss":
                items = fetch_rss(src, cfg)
            elif src["type"] == "html":
                items = fetch_html(src, cfg, known)
            else:
                print(f"[skip] {src['id']}: 未対応のtype")
                continue
        except Exception as ex:  # 1ソースの失敗で全体を止めない
            print(f"[error] {src['id']}: {ex}")
            continue

        fresh = [i for i in items if i["link"] not in known]
        order = list(seen.get(src["id"], []))
        if src["id"] not in seen:
            # 初回は過去記事を一気に要約しないよう、最新N件だけ処理
            fresh = fresh[:boot_n]
            order.extend(i["link"] for i in items if i["link"] not in known)
        else:
            order.extend(i["link"] for i in fresh)
        seen[src["id"]] = list(dict.fromkeys(order))[-500:]
        print(f"[ok] {src['id']}: 新着 {len(fresh)} 件")
        new_items.extend(fresh)
    return new_items
