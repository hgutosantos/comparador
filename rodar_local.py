"""Modo local: atualiza (se os dados tiverem mais de 1h) e abre o comparador no navegador.

Uso: python rodar_local.py           (atualiza se preciso e abre)
     python rodar_local.py --forcar  (sempre atualiza antes de abrir)
     python rodar_local.py --sem-atualizar
Deixe a janela aberta: ele reatualiza sozinho de hora em hora.
"""
import asyncio
import datetime as dt
import functools
import http.server
import json
import sys
import threading
import time
import webbrowser
from pathlib import Path

from scraper.main import OUT, run

ROOT = Path(__file__).resolve().parent
PORT = 8765


def idade_horas():
    if not OUT.exists():
        return 999
    gen = json.loads(OUT.read_text(encoding="utf-8")).get("generated_at")
    return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(gen)).total_seconds() / 3600


def atualizar():
    try:
        asyncio.run(run())
    except Exception as e:
        print("Falha na atualização:", e)


def loop_horario():
    while True:
        time.sleep(3600)
        print("\n[atualização horária]")
        atualizar()


if __name__ == "__main__":
    if "--sem-atualizar" not in sys.argv and ("--forcar" in sys.argv or idade_horas() >= 1):
        print("Atualizando produtos… (pode levar alguns minutos)")
        atualizar()
    threading.Thread(target=loop_horario, daemon=True).start()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "docs"))
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler)
    url = f"http://localhost:{PORT}"
    print(f"\nComparador aberto em {url}  (no celular, na mesma rede: http://IP-DO-PC:{PORT})")
    print("Ctrl+C para fechar.")
    webbrowser.open(url)
    srv.serve_forever()
