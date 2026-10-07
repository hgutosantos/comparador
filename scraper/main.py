"""Coleta todos os sites e gera docs/data/products.json.

Uso:  python -m scraper.main            (todos os sites)
      python -m scraper.main --only Lupax
"""
import argparse
import asyncio
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

from .api import scrape_api
from .extract import popularity_signals, scrape_site

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "products.json"
CAPT = ROOT / "capturas"
TZ = dt.timezone(dt.timedelta(hours=-3))  # horário de Brasília


def now():
    return dt.datetime.now(TZ)


def log(msg):
    print(msg, flush=True)


def compile_rules(rules):
    cats = [(r["name"], re.compile(r["match"], re.I)) for r in rules.get("categories", [])]
    groups = [(r["name"], re.compile(r["match"], re.I)) for r in rules.get("groups", [])]
    excl = [re.compile(x, re.I) for x in rules.get("exclude", [])]
    return cats, groups, excl


FILLER = re.compile(
    r"\b(entrega|automatica|imediata|rapida|garantia|total|completa|brindes?|bonus|suporte|"
    r"exclusiv[oa]|privad[oa]|individual|compartilhad[oa]|tela|perfil|no seu e ?mail|na sua conta|"
    r"seu proprio e ?mail|sua propria conta|original|oficial|melhor preco( do mercado| da plataforma)?|"
    r"promocao|promo|estamos on|on|novo|nova|atualizad[oa]|com|de|do|da|e|o|a|para|por|via|\+)\b")
DUR_RX = [
    (re.compile(r"(\d+)\s*(dias?|d)\b"), 1),
    (re.compile(r"(\d+)\s*(mes|meses)\b"), 30),
    (re.compile(r"(\d+)\s*(anos?)\b"), 360),  # 1 ano = 12 meses
]
DUR_WORDS = [("vitalicio", "vitalício"), ("anual", 360), ("semestral", 180), ("trimestral", 90), ("mensal", 30)]


def plain(text):
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9+ ]+", " ", t)


def duration(name):
    t = plain(name)
    for rx, mult in DUR_RX:
        m = rx.search(t)
        if m:
            return int(m.group(1)) * mult
    for word, val in DUR_WORDS:
        if word in t:
            return val
    return None


def duration_label(d):
    if d is None:
        return ""
    if isinstance(d, str):
        return d
    if d % 360 == 0:
        n = d // 360
        return f"{n} ano" + ("s" if n > 1 else "")
    if d % 30 == 0:
        n = d // 30
        return f"{n} " + ("meses" if n > 1 else "mês")
    return f"{d} dias"


def auto_key(name):
    t = plain(name)
    for rx, _ in DUR_RX:
        t = rx.sub(" ", t)
    t = FILLER.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def popularity(raw):
    """Estimativa: vendas e avaliações do anúncio pesam mais; destaque no site e
    contador do vendedor ajudam; aparecer cedo na página também conta um pouco."""
    score = raw.get("sold", 0) * 3 + raw.get("reviews", 0) * 2 + raw.get("seller_count", 0) * 0.2
    score += 150 * len(raw.get("highlights") or [])
    score += max(0, 60 - (raw.get("position") or 0) * 0.1)
    return round(score, 1)


def normalize(raw, site, stamp, cats, groups):
    hay = f"{raw['name']} {raw.get('site_category', '')}"
    category = next((n for n, rx in cats if rx.search(hay)), "Outros")
    group = next((n for n, rx in groups if rx.search(raw["name"])), "")
    dur = duration(raw["name"])
    dlabel = duration_label(dur)
    if group:
        match_key = f"{group}|{dur}" if dur is not None else group
        match_label = f"{group} ({dlabel})" if dlabel else group
    else:
        match_key = auto_key(raw["name"]) + (f"|{dur}" if dur is not None else "")
        match_label = raw["name"]
    return {
        "id": hashlib.sha1((raw["link"] + "|" + raw["name"]).encode()).hexdigest()[:12],
        "name": raw["name"],
        "category": category,
        "site_category": (raw.get("site_category") or "").strip()[:80],
        "group": group,
        "match_key": match_key,
        "match_label": match_label,
        "duration": dlabel,
        "price": round(raw["price"], 2) if raw.get("price") else None,
        "list_price": round(raw["list_price"], 2) if raw.get("list_price") else None,
        "popularity": popularity(raw),
        "highlights": raw.get("highlights") or [],
        "link": raw["link"],
        "image": raw.get("image") or "",
        "site": site["name"],
        "seen_at": stamp,
    }


def collect_downloads():
    """Move capturas manuais da pasta Downloads para comparador/capturas."""
    CAPT.mkdir(exist_ok=True)
    for d in {Path.home() / "Downloads", Path.home() / "downloads"}:
        if d.is_dir():
            for f in d.glob("captura_*.json"):
                try:
                    shutil.move(str(f), CAPT / f.name)
                    log(f"  captura importada: {f.name}")
                except OSError:
                    pass


def load_captures(stamp_now, cats, groups, max_age_days):
    """Junta as capturas manuais: vale a mais recente de cada página; antigas demais saem."""
    collect_downloads()
    latest = {}
    for f in sorted(CAPT.glob("captura_*.json")):
        try:
            cap = json.loads(f.read_text(encoding="utf-8"))
            when = dt.datetime.fromisoformat(cap["captured_at"].replace("Z", "+00:00"))
        except Exception as e:
            log(f"  ! captura ignorada {f.name}: {e}")
            continue
        key = (cap["site"], cap["page_url"])
        if key not in latest or when > latest[key][0]:
            latest[key] = (when, cap)
    products, meta = [], {}
    for (site, _), (when, cap) in latest.items():
        if (stamp_now - when).total_seconds() > max_age_days * 86400:
            continue
        seen = when.astimezone(TZ).isoformat(timespec="seconds")
        for it in cap["items"]:
            it.update(popularity_signals(it.get("text", "")))
            p = normalize(it, {"name": site}, seen, cats, groups)
            p["manual"] = True
            products.append(p)
        m = meta.setdefault(site, {"name": site, "url": cap["page_url"], "status": "manual", "count": 0, "last_ok": seen})
        m["last_ok"] = max(m["last_ok"], seen)
    for p in products:
        meta[p["site"]]["count"] += 1
    return products, list(meta.values())


async def run(only=None):
    sites_cfg = yaml.safe_load((ROOT / "config" / "sites.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
    settings = sites_cfg.get("settings", {})
    cats, groups, excl = compile_rules(rules)

    previous = {}
    if OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        for s in prev.get("sites", []):
            previous[s["name"]] = {"meta": s, "items": [p for p in prev["products"] if p["site"] == s["name"]]}

    stamp = now().isoformat(timespec="seconds")
    all_products, site_meta = [], []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for site in sites_cfg["sites"]:
            if not site.get("enabled", True):
                continue  # site desativado sai do índice
            if only and site["name"] != only:
                if site["name"] in previous:  # mantém dados de sites não rodados agora
                    all_products += previous[site["name"]]["items"]
                    site_meta.append(previous[site["name"]]["meta"])
                continue
            log(f"→ {site['name']}")
            try:
                if site.get("type") == "api":
                    raw = scrape_api(site, log)
                else:
                    raw = await scrape_site(browser, site, settings, log)
                if not raw:
                    raise RuntimeError("nenhum produto encontrado — confira product_link_regex com o discover")
                items = [normalize(r, site, stamp, cats, groups) for r in raw]
                kept = [p for p in items if not any(rx.search(f"{p['name']} {p['site_category']}") for rx in excl)]
                all_products += kept
                site_meta.append({"name": site["name"], "url": site["start_urls"][0], "status": "ok",
                                  "count": len(kept), "excluded": len(items) - len(kept), "last_ok": stamp})
                log(f"  ✓ {len(kept)} produtos ({len(items) - len(kept)} excluídos pelo filtro)")
            except Exception as e:
                log(f"  ✗ {site['name']} falhou: {e}")
                prev = previous.get(site["name"])
                meta = {"name": site["name"], "url": site["start_urls"][0], "status": "erro",
                        "error": str(e)[:200], "count": 0, "last_ok": None}
                if prev and prev["meta"].get("last_ok"):
                    age = now() - dt.datetime.fromisoformat(prev["meta"]["last_ok"])
                    if age.total_seconds() < settings.get("stale_after_hours", 6) * 3600:
                        all_products += prev["items"]
                        meta.update(status="desatualizado", count=len(prev["items"]), last_ok=prev["meta"]["last_ok"])
                site_meta.append(meta)
        await browser.close()

    manual, manual_meta = load_captures(now(), cats, groups, settings.get("manual_max_age_days", 7))
    if manual:
        log(f"→ Capturas manuais: {len(manual)} anúncios de {len(manual_meta)} site(s)")
        all_products += manual
        known = {m["name"] for m in site_meta}
        site_meta += [m for m in manual_meta if m["name"] not in known]

    # sem duplicados (link + nome: lojas sem página por produto usam o mesmo link)
    uniq = {p["link"] + "|" + p["name"]: p for p in all_products}
    data = {"generated_at": stamp, "sites": site_meta, "products": sorted(uniq.values(), key=lambda p: (p["category"], p["name"].lower()))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Pronto: {len(uniq)} produtos em {OUT.relative_to(ROOT)}")
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="rodar só um site (nome do sites.yaml)")
    args = ap.parse_args()
    asyncio.run(run(args.only))
