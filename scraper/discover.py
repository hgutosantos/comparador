"""Diagnóstico de uma página: o que o robô vê, padrões de link e buscas de dados (API).

Uso: python -m scraper.discover URL          (navegador invisível)
     python -m scraper.discover URL --ver    (abre o navegador na tela)
Salva um print em discover.png.
"""
import asyncio
import sys
from collections import Counter
from urllib.parse import urlparse

from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def host(u):
    return urlparse(u).netloc.lower().removeprefix("www.")


async def main(url, visible):
    apis = []

    async def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if "json" not in ct or resp.request.resource_type not in ("xhr", "fetch"):
                return
            body = await resp.text()
            apis.append((resp.request.method, resp.url, len(body), body[:300].replace("\n", " ")))
        except Exception:
            pass

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=not visible)
        ctx = await b.new_context(locale="pt-BR", user_agent=UA, viewport={"width": 1366, "height": 900})
        page = await ctx.new_page()
        page.on("response", on_response)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)
        for _ in range(8):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(400)
        await page.screenshot(path="discover.png")
        title = await page.title()
        links = await page.evaluate("[...document.querySelectorAll('a[href]')].map(a=>a.href)")
        prices = await page.evaluate(
            "[...document.querySelectorAll('body *')].filter(e=>e.children.length===0 && /R\\$\\s*\\d/.test(e.textContent)).length")

        print(f"\nTítulo: {title}")
        print(f"Endereço final: {page.url}")
        print(f"Links: {len(links)}   Preços (R$) visíveis: {prices}")

        h = host(page.url)
        pats, examples = Counter(), {}
        for l in links:
            u = urlparse(l)
            if host(l) != h:
                continue
            parts = [p for p in u.path.split("/") if p]
            key = "/" + (parts[0] + "/" + ("*" if len(parts) > 1 else "") if parts else "")
            pats[key] += 1
            examples.setdefault(key, l)
        print("\nPadrões de link:")
        for k, n in pats.most_common(20):
            print(f"  {n:4d}  {k:30s} ex.: {examples[k]}")

        if len(links) <= 40:
            print("\nTodos os links:")
            for l in sorted(set(links)):
                print("  ", l)

        print("\nBuscas de dados (API) feitas pela página:")
        for m, u, n, sample in sorted(apis, key=lambda x: -x[2])[:12]:
            print(f"\n  {m} {u}\n  ({n:,} caracteres) {sample}")
        print()
        if visible:
            await asyncio.to_thread(input, "Navegador aberto. Aperte Enter aqui para fechar...")
        await b.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], "--ver" in sys.argv))