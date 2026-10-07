"""Coletor para lojas que entregam a lista de produtos em JSON (API pública da própria loja)."""
import json
import re
import urllib.request
from urllib.parse import urljoin

NAME_KEYS = ("name", "title", "nome", "titulo")
PRICE_KEYS = ("price", "salePrice", "preco", "valor")
IMG_KEYS = ("image", "imageUrl", "image_url", "img", "cover", "coverUrl", "thumbnail", "banner", "picture", "photo")
LINK_KEYS = ("url", "link", "href", "permalink")
STOCK_KEYS = ("inStock", "available", "disponivel")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def first(o, keys):
    for k in keys:
        v = o.get(k)
        if v not in (None, "", []):
            return v[0] if isinstance(v, list) else v
    return None


def walk(o):
    """Encontra todo objeto que tenha nome + preço, em qualquer nível do JSON."""
    if isinstance(o, dict):
        if first(o, NAME_KEYS) and first(o, PRICE_KEYS) is not None:
            yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def to_price(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"([\d.]+,\d{2}|\d+(?:\.\d+)?)", str(v))
    if not m:
        return None
    s = m.group(1)
    return float(s.replace(".", "").replace(",", ".") if "," in s else s)


def scrape_api(site, log):
    out, seen = [], set()
    for api_url in site["api_urls"]:
        req = urllib.request.Request(api_url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        found = 0
        for o in walk(data):
            if site.get("skip_out_of_stock", True) and any(o.get(k) is False for k in STOCK_KEYS):
                continue
            name = str(first(o, NAME_KEYS)).strip()
            price = to_price(first(o, PRICE_KEYS))
            key = (name, price)
            if key in seen:
                continue
            seen.add(key)
            link = first(o, LINK_KEYS)
            tpl = site.get("product_link_template")
            if link:
                link = urljoin(api_url, str(link))
            elif tpl:
                try:
                    link = tpl.format(**o)
                except (KeyError, IndexError):
                    link = None
            link = link or site.get("link_fallback") or site["start_urls"][0]
            img = first(o, IMG_KEYS)
            lp = first(o, ("listPrice", "originalPrice", "compareAtPrice", "precoOriginal", "oldPrice"))
            lp = to_price(lp) if lp is not None else None
            cat_field = site.get("category_field")
            out.append({
                "link": link,
                "name": name,
                "price": price,
                "list_price": lp if lp and price and lp > price else None,
                "image": urljoin(api_url, str(img)) if img else "",
                "site_category": str(o.get(cat_field, "")) if cat_field else "",
            })
            found += 1
        log(f"  {site['name']}: {api_url} → {found} produtos")
    return out
