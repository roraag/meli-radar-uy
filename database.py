"""SQLite del radar: data/meli.db

Tablas:
- products:  el catálogo propio (los 27 neumáticos de TireShop)
- snapshots: cada oferta de la competencia capturada en una corrida
  (clave única: fecha + sku + producto de catálogo + item del seller)
"""

import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "meli.db")


def conectar():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            medida TEXT NOT NULL,
            segmento TEXT,
            marca_referencial TEXT,
            costo_usd REAL,
            precio_final_usd REAL,
            mercado_min_usd REAL,
            mercado_tipico_usd REAL,
            prioridad TEXT,
            keywords TEXT
        )""")
    con.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            fecha_captura TEXT NOT NULL,          -- YYYY-MM-DD
            sku TEXT NOT NULL,
            query TEXT,
            catalog_product_id TEXT NOT NULL,
            product_name TEXT,
            clasificacion TEXT,                   -- equivalente / premium / no_relevante
            marca_detectada TEXT,
            posicion_producto INTEGER,            -- orden en products/search
            item_id TEXT NOT NULL,
            price REAL,
            currency_id TEXT,
            seller_id TEXT,
            free_shipping INTEGER,                -- 0/1
            condition TEXT,
            PRIMARY KEY (fecha_captura, sku, catalog_product_id, item_id)
        )""")
    return con


def guardar_producto(con, p):
    con.execute("""INSERT OR REPLACE INTO products
        (sku, medida, segmento, marca_referencial, costo_usd, precio_final_usd,
         mercado_min_usd, mercado_tipico_usd, prioridad, keywords)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (p["sku"], p["medida"], p["segmento"], p["marca_referencial"],
         p["costo_usd"], p["precio_final_usd"], p["mercado_min_usd"],
         p["mercado_tipico_usd"], p["prioridad"], p["keywords"]))


def guardar_snapshot(con, s):
    con.execute("""INSERT OR REPLACE INTO snapshots
        (fecha_captura, sku, query, catalog_product_id, product_name,
         clasificacion, marca_detectada, posicion_producto, item_id,
         price, currency_id, seller_id, free_shipping, condition)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (s["fecha_captura"], s["sku"], s["query"], s["catalog_product_id"],
         s["product_name"], s["clasificacion"], s["marca_detectada"],
         s["posicion_producto"], s["item_id"], s["price"], s["currency_id"],
         s["seller_id"], s["free_shipping"], s["condition"]))
