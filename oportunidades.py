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
import sqlite3
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
    # migracion suave: precio de referencia UY (cuando ML no expone el precio
    # de la publicacion exacta, se usa el equivalente mas barato del catalogo)
    for col, tipo in (("precio_uy_ref", "REAL"), ("moneda_uy_ref", "TEXT"),
                      ("match_uy_id", "TEXT"), ("match_uy_nombre", "TEXT")):
        try:
            con.execute(f"ALTER TABLE oportunidades ADD COLUMN {col} {tipo}")
        except sqlite3.OperationalError:
            pass  # ya existe


def limpiar_para_busqueda(nombre):
    """Nombre UY -> query para MLB: sin medidas de cuotas ni ruido local."""
    n = re.sub(r"[^\w\s/.-]", " ", nombre)
    return " ".join(n.split()[:8])  # las primeras palabras concentran el producto


def resolver_uy(cliente, tipo, meli_id):
    """Nombre, dominio, precio, link y marca de un highlight de MLU.
    La marca (attribute BRAND) sirve para reintentar la busqueda de referencia
    sin ella: las marcas locales (Benacedo, Bartl...) no existen en el catalogo
    y matan el match."""
    nombre = dominio = link = marca = None
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
            for a in d.get("attributes", []):
                if a.get("id") == "BRAND" and a.get("values"):
                    marca = a["values"][0].get("name")
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
    return nombre, dominio, precio, moneda, link, marca


def buscar_referencia(cliente, site_id, nombre):
    """Producto de REFERENCIA en el catalogo del sitio (MLU o MLB), matcheado
    por nombre: no es la publicacion exacta del ranking, es el equivalente mas
    barato con ofertas activas. Reintenta con queries cada vez mas cortas
    (8 -> 5 -> 3 palabras) hasta encontrar algo.

    Devuelve (precio, moneda, product_id, product_nombre) o cuatro None."""
    palabras = limpiar_para_busqueda(nombre).split()
    for n in (8, 5, 3):
        q = " ".join(palabras[:n])
        if not q:
            break
        r = cliente.get("/products/search", {
            "status": "active", "site_id": site_id, "q": q,
            "limit": MAX_INTENTOS_BR,
        })
        if r.status_code != 200:
            continue
        for prod in r.json().get("results", [])[:MAX_INTENTOS_BR]:
            rr = cliente.get(f"/products/{prod['id']}/items")
            if rr.status_code != 200:
                continue
            ofertas = [it for it in rr.json().get("results", []) if it.get("price")]
            if not ofertas:
                continue
            # min dentro de la moneda mayoritaria del producto (en MLU
            # conviven USD y UYU; mezclarlas daria un "minimo" sin sentido)
            monedas = [it.get("currency_id") for it in ofertas]
            moneda = max(set(monedas), key=monedas.count)
            mejor = min((it for it in ofertas if it.get("currency_id") == moneda),
                        key=lambda it: it["price"])
            return mejor["price"], moneda, prod["id"], prod.get("name")
    return None, None, None, None


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
            nombre, dominio, precio, moneda, link, marca = \
                resolver_uy(cliente, tipo, meli_id)
            if not nombre:
                continue
            # si la marca es local (Benacedo, Bartl...) no esta en el catalogo:
            # segundo intento de referencia con el nombre sin la marca
            sin_marca = (re.sub(re.escape(marca), " ", nombre, flags=re.IGNORECASE)
                         if marca else None)
            # sin precio directo (publicacion sin catalogar): precio de
            # referencia = equivalente mas barato del catalogo UY
            p_ref = m_ref = uy_ref_id = uy_ref_nombre = None
            if precio is None:
                p_ref, m_ref, uy_ref_id, uy_ref_nombre = \
                    buscar_referencia(cliente, "MLU", nombre)
                if p_ref is None and sin_marca:
                    p_ref, m_ref, uy_ref_id, uy_ref_nombre = \
                        buscar_referencia(cliente, "MLU", sin_marca)
            precio_br = br_id = br_nombre = None
            if con_brasil:
                precio_br, _, br_id, br_nombre = \
                    buscar_referencia(cliente, "MLB", nombre)
                if precio_br is None and sin_marca:
                    precio_br, _, br_id, br_nombre = \
                        buscar_referencia(cliente, "MLB", sin_marca)
            con.execute("""INSERT OR REPLACE INTO oportunidades
                (fecha_captura, categoria_id, categoria_nombre, posicion, tipo,
                 meli_id, nombre, dominio, precio_uy, moneda_uy, link_uy,
                 precio_br, match_br_id, match_br_nombre,
                 precio_uy_ref, moneda_uy_ref, match_uy_id, match_uy_nombre)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (hoy, cat_id, cat_nombre, pos, tipo, meli_id, nombre, dominio,
                 precio, moneda, link, precio_br, br_id, br_nombre,
                 p_ref, m_ref, uy_ref_id, uy_ref_nombre))
            total += 1
            br_txt = f" | BR {precio_br} BRL" if precio_br else ""
            if precio is not None:
                uy_txt = f"{moneda} {precio}"
            elif p_ref is not None:
                uy_txt = f"{m_ref} {p_ref} (ref)"
            else:
                uy_txt = "s/precio"
            print(f"    #{pos:>2} {nombre[:48]:<48} {uy_txt}{br_txt}")
        con.commit()  # checkpoint por categoria

    con.close()
    print(f"\nListo: {total} oportunidades guardadas en data/meli.db")


if __name__ == "__main__":
    capturar(sys.argv[1:] or None)
