"""Captura del radar: recorre los SKUs de TireShop, busca los productos de
catálogo equivalentes en ML Uruguay y guarda las ofertas de la competencia.

Uso:
    python3 radar.py                # corrida completa (27 medidas)
    python3 radar.py 265/70R16 ...  # solo las medidas indicadas (dry-run)

Comparación siempre POR MEDIDA, segmento chino/genérico (regla del proyecto):
las marcas del catálogo propio son referenciales; acá se clasifica cada
producto de ML como 'equivalente' (chinos y segundas marcas), 'premium'
(marcas top, solo referencia secundaria) o 'no_relevante' (otra medida).
"""

import csv
import datetime
import os
import re
import sys

from database import conectar, guardar_producto, guardar_snapshot
from meli_client import MeliClient

BASE = os.path.dirname(os.path.abspath(__file__))
# El CSV fuente tiene COSTOS de TireShop -> nunca va al repo (publico).
# En el VPS vive junto al .env; localmente, en la carpeta ONLINE/ de Drive.
CSV_FUENTE = os.environ.get(
    "MELI_RADAR_CSV",
    os.path.join(os.path.dirname(BASE), "Neumaticos_etapa1_margen_ML.csv"))
if not os.path.exists(CSV_FUENTE):
    _alt = os.path.expanduser("~/.config/meli-radar-uy/Neumaticos_etapa1_margen_ML.csv")
    if os.path.exists(_alt):
        CSV_FUENTE = _alt

MARCAS_PREMIUM = {
    "MICHELIN", "BRIDGESTONE", "PIRELLI", "GOODYEAR", "CONTINENTAL",
    "YOKOHAMA", "DUNLOP", "HANKOOK", "BFGOODRICH", "FIRESTONE",
    # semi-premium / europeas-americanas caras: referencia, no equivalente chino
    "VREDESTEIN", "COOPER", "GT", "KUMHO", "NEXEN", "TOYO", "FALKEN",
    "MAXXIS", "GENERAL", "UNIROYAL",
}
MAX_PRODUCTOS_POR_SKU = 40  # productos de catálogo a mirar por medida

PALABRAS_NO_MARCA = {
    "CUBIERTA", "CUBIERTAS", "NEUMATICO", "NEUMATICOS", "NEUMÁTICO",
    "NEUMÁTICOS", "LLANTA", "LLANTAS", "KIT", "JUEGO", "COMBO", "PACK",
    "X2", "X4", "DE", "PARA", "AUTO", "CAMIONETA",
}


def normalizar(texto):
    return re.sub(r"[\s\-]", "", texto.upper())


def medida_en_nombre(medida, nombre):
    """¿El nombre del producto contiene exactamente esta medida?"""
    m, n = normalizar(medida), normalizar(nombre)
    variantes = {m, m.replace("/", ""), m.replace("R", "/")}
    if "X" in m:  # camioneta tipo 31X10.50R15
        variantes.add(m.replace("X", "X "))
    return any(v in n for v in variantes if v)


def detectar_marca(nombre):
    """Primera palabra 'con pinta de marca' del nombre del producto.
    Saltea genéricos (Cubierta, Neumático, Kit...) y tokens de medida/números.
    Si no encuentra nada, devuelve GENERICO."""
    for palabra in nombre.upper().split():
        limpia = palabra.strip(",.()")
        if limpia in PALABRAS_NO_MARCA:
            continue
        if re.search(r"\d", limpia):  # medidas, índices de carga, rodados
            continue
        return limpia
    return "GENERICO"


def clasificar(medida, nombre):
    if not medida_en_nombre(medida, nombre):
        return "no_relevante"
    return "premium" if detectar_marca(nombre) in MARCAS_PREMIUM else "equivalente"


def unidades_kit(nombre):
    """Detecta kits x2/x4/x6 en el título para convertir el precio a unitario.
    Cuidado: '4x4' (tracción) no es un kit — el lookbehind evita ese caso."""
    n = nombre.upper()
    m = (re.search(r"KIT\s+(?:DE\s+)?X?\s*(\d)", n)
         or re.search(r"(?<!\d)X\s?(\d)\b", n)
         or re.search(r"(?:PACK|JUEGO)\s+(?:DE\s+)?(\d)", n))
    if m:
        q = int(m.group(1))
        if q in (2, 4, 6):
            return q
    return 1


def cargar_skus():
    """Lee el CSV fuente de TireShop (fuente de verdad de precios)."""
    skus = []
    with open(CSV_FUENTE) as f:
        for r in csv.DictReader(f):
            medida = r["medida"].strip()
            skus.append({
                "sku": f"NEU-{r['codigo_tireshop']}",
                "medida": medida,
                "segmento": r["segmento"],
                "marca_referencial": r["marca_referencial"],
                "costo_usd": float(r["costo_usd"]),
                "precio_final_usd": float(r["precio_final_usd"]),
                "mercado_min_usd": float(r["mercado_min_usd"]),
                "mercado_tipico_usd": float(r["mercado_tipico_usd"]),
                "prioridad": r["prioridad"],
                "keywords": f"neumatico {medida.lower()}",
            })
    return skus


def capturar(filtro_medidas=None):
    cliente = MeliClient()
    con = conectar()
    hoy = datetime.date.today().isoformat()

    skus = cargar_skus()
    if filtro_medidas:
        objetivo = {normalizar(m) for m in filtro_medidas}
        skus = [s for s in skus if normalizar(s["medida"]) in objetivo]
    print(f"Corrida {hoy} — {len(skus)} medidas\n")

    total_ofertas = 0
    for s in skus:
        guardar_producto(con, s)
        total, productos = cliente.buscar_productos(s["keywords"],
                                                    limit=MAX_PRODUCTOS_POR_SKU)
        relevantes, ofertas_sku = 0, 0
        for pos, p in enumerate(productos, start=1):
            nombre = p.get("name", "")
            clasif = clasificar(s["medida"], nombre)
            if clasif == "no_relevante":
                continue
            relevantes += 1
            unidades = unidades_kit(nombre)
            for it in cliente.ofertas_de_producto(p["id"]):
                precio = it.get("price")
                if precio and unidades > 1:
                    precio = round(precio / unidades, 2)
                guardar_snapshot(con, {
                    "fecha_captura": hoy,
                    "sku": s["sku"],
                    "query": s["keywords"],
                    "catalog_product_id": p["id"],
                    "product_name": (nombre + f" [kit x{unidades} -> unitario]"
                                     if unidades > 1 else nombre),
                    "clasificacion": clasif,
                    "marca_detectada": detectar_marca(nombre),
                    "posicion_producto": pos,
                    "item_id": it.get("item_id") or it.get("id") or "",
                    "price": precio,
                    "currency_id": it.get("currency_id"),
                    "seller_id": str(it.get("seller_id", "")),
                    "free_shipping": 1 if it.get("shipping", {}).get("free_shipping") else 0,
                    "condition": it.get("condition"),
                })
                ofertas_sku += 1
        con.commit()  # checkpoint por SKU: si algo corta, lo hecho queda
        total_ofertas += ofertas_sku
        print(f"  {s['medida']:<12} [{s['prioridad']:<10}] "
              f"{total:>5} en catálogo | {relevantes:>2} relevantes | "
              f"{ofertas_sku:>3} ofertas")

    con.close()
    print(f"\nListo: {total_ofertas} ofertas guardadas en data/meli.db")


if __name__ == "__main__":
    capturar(sys.argv[1:] or None)
