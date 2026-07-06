"""Scraper browser de ML Uruguay — CORRE EN LA MAC, no en el VPS.

Por que existe: ML bloquea las busquedas desde IPs de datacenter (el VPS
recibe account-verification en listados y detalle; verificado 05-jul-2026
con 3 variantes). Desde una IP residencial pasa sin problema. Ademas cubre
lo que la API de catalogo no ve: publicaciones sin catalogar (casi todos
los accesorios) y la señal de demanda "+X vendidos" del detalle.

Uso (manual, cuando Rodrigo quiera — ej. semanal):
    python3 scraper.py                     # accesorios + neumaticos (~20 min)
    python3 scraper.py accesorios          # solo accesorios
    python3 scraper.py neumaticos          # solo neumaticos
    python3 scraper.py 265/70R16 175/70R13 # solo esas medidas
    python3 scraper.py --sin-detalle ...   # sin "+X vendidos" (mas rapido)
    python3 scraper.py --publicar ...      # ademas sube el CSV al repo (gh api)

Salida: outputs/scraper_<fecha>.csv (historico local) y, con --publicar,
docs/data/browser.csv en el repo roraag/meli-radar-uy — SOLO datos publicos
scrapeados (sin costos de TireShop). El cron del VPS lo integra al dashboard.
"""

import base64
import csv
import datetime
import json
import os
import random
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

from radar import (cargar_accesorios, cargar_skus, clasificar, detectar_marca,
                   normalizar, relevancia_accesorio, unidades_kit)

BASE = os.path.dirname(os.path.abspath(__file__))
REPO_GH = "roraag/meli-radar-uy"
RUTA_CSV_REPO = "docs/data/browser.csv"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")
DETALLES_POR_SKU = 3    # paginas de detalle a visitar (señal vendidos)
MAX_ITEMS_LISTADO = 30  # items del listado a procesar por SKU

CAMPOS = ["fecha_captura", "sku", "familia", "medida", "clasificacion",
          "titulo", "precio", "moneda", "unidades_kit", "precio_unitario",
          "vendidos", "posicion", "link"]


def pausa_humana(a=2.0, b=4.5):
    import time
    time.sleep(random.uniform(a, b))


def slug_busqueda(keywords):
    return re.sub(r"[^a-z0-9]+", "-", keywords.lower()).strip("-")


def parsear_precio(item):
    """Precio actual del item del listado (ignora el tachado si lo hay)."""
    caja = item.query_selector(".poly-price__current") or item
    frac = caja.query_selector(".andes-money-amount__fraction")
    if not frac:
        return None, None
    precio = float(frac.inner_text().strip().replace(".", "").replace(",", "."))
    cents = caja.query_selector(".andes-money-amount__cents")
    if cents:
        precio += float(cents.inner_text().strip() or 0) / 100
    simbolo = caja.query_selector(".andes-money-amount__currency-symbol")
    moneda = "USD" if simbolo and "US" in simbolo.inner_text() else "UYU"
    return precio, moneda


def leer_listado(page, url):
    """Items relevantes de una pagina de listado: (titulo, precio, moneda, link)."""
    page.goto(url, timeout=60000, wait_until="load")
    try:
        page.wait_for_selector("li.ui-search-layout__item", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if "account-verification" in page.url:
        raise RuntimeError("ML pidio verificacion (anti-bot) — corta y reintenta mas tarde")
    filas = []
    for it in page.query_selector_all("li.ui-search-layout__item")[:MAX_ITEMS_LISTADO]:
        t = it.query_selector(".poly-component__title") or it.query_selector("h3, h2")
        a = it.query_selector("a")
        if not t or not a:
            continue
        precio, moneda = parsear_precio(it)
        filas.append({"titulo": t.inner_text().strip(),
                      "precio": precio, "moneda": moneda,
                      "link": a.get_attribute("href") or ""})
    return filas


def leer_vendidos(page, link):
    """Señal '+X vendidos' del subtitulo del detalle. None si no aparece."""
    try:
        page.goto(link, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
    except Exception:
        return None
    if "account-verification" in page.url:
        raise RuntimeError("ML pidio verificacion (anti-bot) en detalle")
    sub = page.query_selector(".ui-pdp-subtitle")
    texto = sub.inner_text() if sub else ""
    m = re.search(r"\+?\s?(\d+)\s*vendidos?", texto)
    return int(m.group(1)) if m else None


def procesar_sku(page, s, hoy, estado):
    """Listado + clasificacion + (opcional) vendidos de los primeros relevantes.

    estado["detalle"] es compartido por toda la corrida: si ML pide
    verificacion en una pagina de detalle, se apaga y el resto de la corrida
    sigue solo con listados (los precios se salvan, se pierde la señal de
    vendidos). El anti-bot de ML salta mucho antes en detalle que en listado
    (corte real del 05-jul tras ~80 detalles)."""
    url = "https://listado.mercadolibre.com.uy/" + slug_busqueda(s["keywords"])
    filas_csv = []
    try:
        items = leer_listado(page, url)
    except RuntimeError:
        raise
    except Exception as e:
        print(f"    [error en listado: {str(e)[:60]} — SKU salteado]")
        return []
    relevantes = []
    for pos, it in enumerate(items, start=1):
        if s["familia"] == "accesorio":
            clasif = ("equivalente" if relevancia_accesorio(s["medida"], it["titulo"])
                      else "no_relevante")
        else:
            clasif = clasificar(s["medida"], it["titulo"])
        if clasif == "no_relevante" or it["precio"] is None:
            continue
        unidades = unidades_kit(it["titulo"]) if s["familia"] == "neumatico" else 1
        relevantes.append({
            "fecha_captura": hoy, "sku": s["sku"], "familia": s["familia"],
            "medida": s["medida"], "clasificacion": clasif,
            "titulo": it["titulo"], "precio": it["precio"], "moneda": it["moneda"],
            "unidades_kit": unidades,
            "precio_unitario": round(it["precio"] / unidades, 2),
            "vendidos": None, "posicion": pos, "link": it["link"],
        })
    # señal de demanda: detalle de los primeros N relevantes (orden = relevancia ML)
    if estado["detalle"]:
        for fila in relevantes[:DETALLES_POR_SKU]:
            pausa_humana(4.0, 8.0)  # el detalle es lo que dispara el anti-bot
            try:
                fila["vendidos"] = leer_vendidos(page, fila["link"])
            except RuntimeError:
                estado["detalle"] = False
                print("    [anti-bot en detalle: la corrida sigue solo con listados]")
                break
    filas_csv.extend(relevantes)
    n_vend = sum(1 for f in filas_csv if f["vendidos"] is not None)
    print(f"  {s['medida'][:36]:<36} {len(items):>2} en listado | "
          f"{len(relevantes):>2} relevantes | vendidos en {n_vend}")
    return filas_csv


def publicar_csv(path_csv, hoy):
    """Sube el CSV a docs/data/browser.csv del repo via gh api (sin clone)."""
    with open(path_csv, "rb") as f:
        contenido = base64.b64encode(f.read()).decode()
    sha = subprocess.run(
        ["gh", "api", f"repos/{REPO_GH}/contents/{RUTA_CSV_REPO}", "--jq", ".sha"],
        capture_output=True, text=True).stdout.strip()
    cmd = ["gh", "api", f"repos/{REPO_GH}/contents/{RUTA_CSV_REPO}", "-X", "PUT",
           "-f", f"message=browser {hoy} (scraper Mac)",
           "-f", f"content={contenido}"]
    if sha:
        cmd += ["-f", f"sha={sha}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ERROR publicando al repo: {r.stderr[:200]}]")
        return False
    print(f"  Publicado: {REPO_GH}/{RUTA_CSV_REPO}")
    return True


def correr(args):
    con_detalle = "--sin-detalle" not in args
    publicar = "--publicar" in args
    filtros = [a for a in args if not a.startswith("--")]

    skus = []
    if not filtros or "accesorios" in [f.lower() for f in filtros]:
        skus += cargar_accesorios()
    if not filtros or "neumaticos" in [f.lower() for f in filtros]:
        skus += cargar_skus()
    if filtros and not skus:  # medidas puntuales
        todos = cargar_accesorios() + cargar_skus()
        objetivo = {normalizar(f) for f in filtros}
        skus = [s for s in todos
                if normalizar(s["medida"]) in objetivo or s["sku"] in filtros]

    hoy = datetime.date.today().isoformat()
    print(f"Scraper {hoy} — {len(skus)} SKUs "
          f"({'con' if con_detalle else 'sin'} detalle de vendidos)\n")

    filas = []
    procesados = set()   # solo estos se pisan en el merge del dia
    faltantes = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True,
                              args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=UA, locale="es-UY",
                            timezone_id="America/Montevideo",
                            viewport={"width": 1366, "height": 900})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()
        estado = {"detalle": con_detalle}
        for i, s in enumerate(skus):
            pausa_humana()
            try:
                filas.extend(procesar_sku(page, s, hoy, estado))
                procesados.add(s["sku"])
            except RuntimeError as e:
                # anti-bot en LISTADO: no insistir; guardar lo acumulado y salir
                faltantes = [x["sku"] for x in skus[i:]]
                print(f"\n[CORTE anti-bot en listado: {e}]")
                break
        b.close()

    os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
    path_csv = os.path.join(BASE, "outputs", f"scraper_{hoy}.csv")
    # corridas parciales del mismo dia: conservar los SKUs que no se re-corrieron
    if os.path.exists(path_csv):
        with open(path_csv) as f:
            filas = [r for r in csv.DictReader(f) if r["sku"] not in procesados] + filas
    with open(path_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"\nListo: {len(filas)} filas -> {path_csv}")
    if faltantes:
        print(f"CORRIDA INCOMPLETA — quedaron {len(faltantes)} SKUs sin correr. "
              f"Re-correr mas tarde con: python3 scraper.py {' '.join(faltantes)}")

    if publicar and filas:
        publicar_csv(path_csv, hoy)
    elif publicar:
        print("  [nada que publicar: 0 filas]")


if __name__ == "__main__":
    correr(sys.argv[1:])
