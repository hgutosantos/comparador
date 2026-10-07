"""Extração genérica de produtos de qualquer loja, via navegador headless."""
import asyncio
import json
import re
from urllib.parse import urljoin

PRICE_RE = re.compile(r"R\$\s*([\d.]+,\d{2})")

# Roda dentro da página: acha cada link de produto, sobe até o "card" e lê imagem/título/preço/categoria.
CARDS_JS = r"""
(pattern) => {
  const re = new RegExp(pattern);
  const clean = h => h.split('#')[0];
  const isProd = h => re.test(new URL(h, location.href).pathname);
  const countLinks = el => new Set([...el.querySelectorAll('a[href]')]
      .map(x => clean(x.href)).filter(isProd)).size;
  const headingOf = el => {
    if (!el || !el.matches) return '';
    if (el.matches('h1,h2,h3,h4')) return el.innerText;
    const h = el.querySelector && el.querySelector('h1,h2,h3,h4');
    return h ? h.innerText : '';
  };
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = clean(a.href);
    if (!href.startsWith('http') || !isProd(href) || seen.has(href)) continue;
    seen.add(href);
    let card = a;
    for (let i = 0; i < 8; i++) {
      if (card.querySelector('img') && /R\$\s*\d/.test(card.innerText)) break;
      const p = card.parentElement;
      if (!p || countLinks(p) > 1) break;
      card = p;
    }
    const img = card.querySelector('img');
    const tEl = card.querySelector('h1,h2,h3,h4,h5,h6,[class*="title" i],[class*="name" i]');
    const title = (tEl && tEl.innerText) || (img && img.alt) || a.getAttribute('title') || a.innerText || '';
    // categoria = cabeçalho de seção mais próximo ANTES do card (ignorando outros cards)
    let cat = '', el = card;
    while (el && !cat) {
      let sib = el.previousElementSibling;
      while (sib && !cat) {
        if (countLinks(sib) === 0) cat = headingOf(sib);
        sib = sib.previousElementSibling;
      }
      el = el.parentElement;
    }
    out.push({
      link: href,
      name: title.trim(),
      image: img ? (img.currentSrc || img.src || img.dataset.src || '') : '',
      text: (card.innerText || '').slice(0, 600),
      site_category: cat.trim(),
    });
  }
  const h1 = document.querySelector('h1');
  return {cards: out, page_title: h1 ? h1.innerText.trim() : document.title,
          links: [...document.querySelectorAll('a[href]')].map(x => clean(x.href))};
}
"""

DETAIL_JS = r"""
() => {
  const meta = p => (document.querySelector(`meta[property="${p}"],meta[name="${p}"]`) || {}).content || '';
  let ld = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const j = JSON.parse(s.textContent);
      const arr = Array.isArray(j) ? j : (j['@graph'] || [j]);
      ld = arr.find(x => /Product/i.test(x['@type'])) || ld;
    } catch (e) {}
  }
  const main = document.querySelector('main') || document.body;
  const imgs = [...main.querySelectorAll('img')]
    .filter(i => (i.naturalWidth || i.width) >= 120)
    .map(i => i.currentSrc || i.src);
  const h = main.querySelector('h1,h2');
  return {
    og_title: meta('og:title'), og_image: meta('og:image'),
    price_meta: meta('product:price:amount') || meta('og:price:amount'),
    ld, imgs, heading: h ? h.innerText.trim() : '',
    text: main.innerText.slice(0, 4000),
  };
}
"""


def parse_prices(text):
    vals = [float(v.replace(".", "").replace(",", ".")) for v in PRICE_RE.findall(text or "")]
    return [v for v in vals if v > 0]


def parse_price(text):
    # preço com desconto aparece junto do original; o menor costuma ser o atual
    vals = parse_prices(text)
    return min(vals) if vals else None


HIGHLIGHT_RE = re.compile(r"destaque|mais procurad|mais vendid|popular|em alta|recomendad|top \d|ofertas? d[oa]", re.I)
NUM = r"(\d{1,3}(?:\.\d{3})+|\d+)"


def popularity_signals(text):
    """Sinais de popularidade que aparecem no card (vendas, avaliações, contador do vendedor)."""
    t = text or ""
    def grab(rx):
        m = re.search(rx, t, re.I)
        return int(m.group(1).replace(".", "")) if m else 0
    return {
        "sold": grab(NUM + r"\s*(?:vendid|vendas)"),
        "reviews": grab(NUM + r"\s*avalia"),
        "seller_count": grab(r"\(" + NUM + r"\)"),
    }


def clean_name(name, site_name):
    name = re.sub(r"\s+", " ", name or "").strip()
    # remove prefixo "Loja - " que vem do <title>
    name = re.sub(rf"^{re.escape(site_name)}\s*[-|–]\s*", "", name, flags=re.I)
    return name[:200]


async def autoscroll(page, rounds):
    for _ in range(rounds):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(350)
    await page.evaluate("window.scrollTo(0, 0)")


async def scrape_site(browser, site, settings, log):
    timeout = settings.get("page_timeout_ms", 45000)
    delay = settings.get("delay_ms", 800)
    prod_re = site["product_link_regex"]
    crawl_re = re.compile(site.get("crawl_regex") or "^$")
    ctx = await browser.new_context(
        locale="pt-BR",
        user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 ComparadorPessoal/1.0"),
        viewport={"width": 1366, "height": 900},
    )
    page = await ctx.new_page()
    queue = list(site["start_urls"])
    visited, products = set(), {}

    while queue and len(visited) < site.get("max_pages", 10):
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass  # networkidle pode nunca chegar em sites com chat/websocket
        await autoscroll(page, settings.get("scroll_rounds", 10))
        data = await page.evaluate(CARDS_JS, prod_re)
        for c in data["cards"]:
            cat = c["site_category"] or data["page_title"]
            vals = parse_prices(c["text"])
            c["price"] = min(vals) if vals else None
            c["list_price"] = max(vals) if len(vals) > 1 and max(vals) > min(vals) else None
            c.update(popularity_signals(c["text"]))
            c["highlights"] = []
            c["position"] = len(products)
            hl = bool(HIGHLIGHT_RE.search(cat))
            c["site_category"] = "" if hl else cat
            old = products.get(c["link"])
            if old is None:
                products[c["link"]] = old = c
            elif not old["site_category"] and not hl:
                old["site_category"] = cat  # troca "Em destaque" pela categoria real
            if hl and cat not in old["highlights"]:
                old["highlights"].append(cat.strip()[:40])
        for link in data["links"]:
            if link.startswith("http") and crawl_re.search(link) and link not in visited \
                    and link.split("/")[2] == url.split("/")[2]:
                queue.append(link)
        log(f"  {site['name']}: {url} → {len(data['cards'])} cards")
        await page.wait_for_timeout(delay)

    # enriquecimento pela página do produto
    mode = site.get("detail_fetch", "missing")
    limit = settings.get("detail_limit_per_site", 150)
    todo = [p for p in products.values()
            if mode == "always" or (mode == "missing" and (not p.get("price") or not p.get("image") or not p.get("name")))]
    for p in todo[:limit]:
        try:
            await page.goto(p["link"], wait_until="domcontentloaded", timeout=timeout)
            await page.wait_for_timeout(1200)
            d = await page.evaluate(DETAIL_JS)
        except Exception as e:
            log(f"  ! detalhe falhou {p['link']}: {e}")
            continue
        ld = d.get("ld") or {}
        offers = ld.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get("price") or d.get("price_meta")
        try:
            price = float(str(price).replace(",", ".")) if price else None
        except ValueError:
            price = None
        p["price"] = p.get("price") or price or parse_price(d["text"])
        p["name"] = p.get("name") or ld.get("name") or d["heading"] or d["og_title"]
        og = d.get("og_image") or ""
        # og:image de muitas lojas é só o logo; prefira a maior imagem do conteúdo
        ld_img = ld.get("image")
        if isinstance(ld_img, list):
            ld_img = ld_img[0] if ld_img else ""
        p["image"] = p.get("image") or ld_img or (d["imgs"][0] if d["imgs"] else "") or og
        await page.wait_for_timeout(delay)

    await ctx.close()
    for p in products.values():
        p["name"] = clean_name(p.get("name"), site["name"])
        if not p.get("site_category") and p.get("highlights"):
            p["site_category"] = p["highlights"][0]
        if p.get("image"):
            p["image"] = urljoin(p["link"], p["image"])
    return [p for p in products.values() if p["name"]]
