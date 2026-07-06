"""Oportunidades UY <-> BR: que se vende mejor en ML Uruguay (highlights =
BEST_SELLER real por categoria) y a cuanto esta el equivalente en ML Brasil.

Regla del negocio (Rodrigo, 05-jul-2026): de Brasil NO se traen neumaticos;
si accesorios y repuestos de alta rotacion. El "costo" de una oportunidad BR
es el precio de Brasil tal cual (el sobrecosto de traerlo lo calcula Rodrigo).

El match UY->BR es POR NOMBRE (busqueda en el catalogo MLB): es una
aproximacion, no una identidad — el dashboard muestra ambos nombres y el
link para validar a ojo antes de decidir.

Uso:
    python3 oportunidades.py              # todas las categorias
    python3 oportunidades.py MLU208681    # solo una (dry-run)
"""

import datetime
import re
import sys

from database import conectar
from meli_client import MeliClient

# (id, nombre corto, buscar equivalente en Brasil)
# MLU208681 (Llantas y Accesorios) NO tiene highlights (404) — tazas y
# tornillos quedan cubiertos por el scraper browser de la Mac.
CATEGORIAS = [
    ("MLU5725", "Acc. Vehiculos (general)", True),
    ("MLU208675", "Neumaticos", False),   # ranking UY informativo; sin BR
    ("MLU1747", "Acc. de Auto y Camioneta", True),
    ("MLU1748", "Repuestos Autos y Camionetas", True),
]

MAX_INTENTOS_BR = 5  # productos de catalogo MLB a probar por nombre


def crear_tabla(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS oportunidades (
            fecha_captura TEXT NOT NULL,
            categoria_id TEXT NOT NULL,
            categoria_nombre TEXT,
            posicion INTEGER,
            tipo TEXT,                    -- PRODUCT / USER_PRODUCT / ITEM
            meli_id TEXT NOT NULL,
            nombre TEXT,
            dominio TEXT,
            precio_uy REAL,
            moneda_uy TEXT,
            link_uy TEXT,
            precio_br REAL,               -- BRL, precio Brasil tal cual
            match_br_id TEXT,
            match_br_nombre TEXT,
            PRIMARY KEY (fecha_captura, categoria_id, meli_id)
        )""")


def limpiar_para_busqueda(nombre):
    """Nombre UY -> query para MLB: sin medidas de cuotas ni ruido local."""
    n = re.sub(r"[^\w\s/.-]", " ", nombre)
    return " ".join(n.split()[:8])  # las primeras palabras concentran el producto


def resolver_uy(cliente, tipo, meli_id):
    """Nombre, dominio, precio y link de un highlight de MLU."""
    nombre = dominio = link = None
    precio = moneda = None
    if tipo == "PRODUCT":
        r = cliente.get(f"/products/{meli_id}")
        if r.status_code == 200:
            d = r.json()
            nombre, dominio = d.get("name"), d.get("domain_id")
            link = d.get("permalink") or f"https://www.mercadolibre.com.uy/p/{meli_id}"
            bb = d.get("buy_box_winner") or {}
            precio, moneda = bb.get("price"), bb.get("currency_id")
        if precio is None:
            r = cliente.get(f"/products/{meli_id}/items")
            if r.status_code == 200:
                ofertas = [it for it in r.json().get("results", []) if it.get("price")]
                if ofertas:
                    mejor = min(ofertas, key=lambda it: it["price"])
                    precio, moneda = mejor["price"], mejor.get("currency_id")
    elif tipo == "USER_PRODUCT":
        r = cliente.get(f"/user-products/{meli_id}")
        if r.status_code == 200:
            d = r.json()
            nombre, dominio = d.get("name"), d.get("domain_id")
            cpid = d.get("catalog_product_id")
            if cpid:  # /user-products/{id}/items no existe (404): via catalogo
                link = f"https://www.mercadolibre.com.uy/p/{cpid}"
                rr = cliente.get(f"/products/{cpid}/items")
                if rr.status_code == 200:
                    ofertas = [it for it in rr.json().get("results", []) if it.get("price")]
                    if ofertas:
                        mejor = min(ofertas, key=lambda it: it["price"])
                        precio, moneda = mejor["price"], mejor.get("currency_id")
    if nombre and not link:
        slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower()).strip("-")
        link = f"https://listado.mercadolibre.com.uy/{slug}"
    return nombre, dominio, precio, moneda, link


def match_brasil(cliente, nombre):
    """Busca el equivalente en el catalogo de ML Brasil y devuelve el precio
    minimo de la primera coincidencia con ofertas activas."""
    r = cliente.get("/products/search", {
        "status": "active", "site_id": "MLB",
        "q": limpiar_para_busqueda(nombre), "limit": MAX_INTENTOS_BR,
    })
    if r.status_code != 200:
        return None, None, None
    for prod in r.json().get("results", [])[:MAX_INTENTOS_BR]:
        rr = cliente.get(f"/products/{prod['id']}/items")
        if rr.status_code != 200:
            continue
        ofertas = [it for it in rr.json().get("results", [])
                   if it.get("price") and it.get("currency_id") == "BRL"]
        if ofertas:
            return (min(it["price"] for it in ofertas),
                    prod["id"], prod.get("name"))
    return None, None, None


def capturar(filtro_categorias=None):
    cliente = MeliClient()
    con = conectar()
    crear_tabla(con)
    hoy = datetime.date.today().isoformat()

    categorias = CATEGORIAS
    if filtro_categorias:
        categorias = [c for c in CATEGORIAS if c[0] in filtro_categorias]
    print(f"Oportunidades {hoy} — {len(categorias)} categorias\n")

    total = 0
    for cat_id, cat_nombre, con_brasil in categorias:
        r = cliente.get(f"/highlights/MLU/category/{cat_id}")
        if r.status_code != 200:
            print(f"  {cat_nombre}: highlights {r.status_code} — salteada")
            continue
        contenido = r.json().get("content", [])
        print(f"  {cat_nombre}: {len(contenido)} best-sellers")
        for item in contenido:
            tipo, meli_id, pos = item.get("type"), item.get("id"), item.get("position")
            nombre, dominio, precio, moneda, link = resolver_uy(cliente, tipo, meli_id)
            if not nombre:
                continue
            precio_br = br_id = br_nombre = None
            if con_brasil:
                precio_br, br_id, br_nombre = match_brasil(cliente, nombre)
            con.execute("""INSERT OR REPLACE INTO oportunidades
                (fecha_captura, categoria_id, categoria_nombre, posicion, tipo,
                 meli_id, nombre, dominio, precio_uy, moneda_uy, link_uy,
                 precio_br, match_br_id, match_br_nombre)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (hoy, cat_id, cat_nombre, pos, tipo, meli_id, nombre, dominio,
                 precio, moneda, link, precio_br, br_id, br_nombre))
            total += 1
            br_txt = f" | BR {precio_br} BRL" if precio_br else ""
            uy_txt = f"{moneda} {precio}" if precio else "s/precio"
            print(f"    #{pos:>2} {nombre[:48]:<48} {uy_txt}{br_txt}")
        con.commit()  # checkpoint por categoria

    con.close()
    print(f"\nListo: {total} oportunidades guardadas en data/meli.db")


if __name__ == "__main__":
    capturar(sys.argv[1:] or None)
