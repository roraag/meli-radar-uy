"""Scoring comercial por medida, sobre la última captura.

Veredictos (comparando SIEMPRE contra los equivalentes chinos/genéricos,
las premium quedan como referencia secundaria):
- veredicto_precio: barato (≥8% abajo del promedio equivalente),
  alineado (±8%), caro (>8% arriba). Regla heredada del repricing de julio:
  el objetivo era quedar 3-8% abajo del típico.
- competencia: baja (<8 ofertas equivalentes), media (8-25), alta (>25)
- cobertura_baja: menos de 3 ofertas equivalentes -> el número es poco
  confiable, validar a mano o con browser (el catálogo ML no lo cubre todo)
- oportunidad: alta / media / baja (sin demanda real: proxy por precio
  y competencia; sold_quantity ya no está disponible en la API)

Solo se usan ofertas en USD (los neumáticos en ML UY se publican en USD);
las ofertas en otras monedas se cuentan aparte en n_otras_monedas.
"""

import statistics

from database import conectar


def ultima_fecha(con):
    row = con.execute("SELECT MAX(fecha_captura) FROM snapshots").fetchone()
    return row[0]


def score_sku(con, sku, fecha):
    prod = con.execute(
        "SELECT medida, segmento, prioridad, costo_usd, precio_final_usd, "
        "mercado_min_usd, mercado_tipico_usd, familia, moneda "
        "FROM products WHERE sku=?", (sku,)).fetchone()
    (medida, segmento, prioridad, costo, nuestro, mkt_min_jul, mkt_tip_jul,
     familia, moneda) = prod

    filas = con.execute(
        "SELECT clasificacion, price, currency_id, seller_id, free_shipping, "
        "marca_detectada, catalog_product_id, product_name "
        "FROM snapshots WHERE sku=? AND fecha_captura=?", (sku, fecha)).fetchall()

    # se compara solo en la moneda esperada del rubro: USD neumaticos, $U accesorios
    equiv = [f for f in filas if f[0] == "equivalente" and f[2] == moneda and f[1]]
    premium = [f for f in filas if f[0] == "premium" and f[2] == moneda and f[1]]
    otras_monedas = [f for f in filas if f[2] != moneda]

    # anti-outlier: kits x4 encubiertos u ofertas absurdas. Un precio a mas
    # de 2,5x la mediana del set equivalente no entra al promedio.
    precios = sorted(f[1] for f in equiv)
    n_outliers = 0
    if len(precios) >= 3:
        med = statistics.median(precios)
        depurados = [p for p in precios if p <= 2.5 * med]
        n_outliers = len(precios) - len(depurados)
        precios = depurados
    r = {
        "sku": sku, "medida": medida, "segmento": segmento, "familia": familia,
        "moneda": moneda,
        "prioridad": prioridad, "costo_usd": costo, "precio_final_usd": nuestro,
        "mercado_min_jul": mkt_min_jul, "mercado_tipico_jul": mkt_tip_jul,
        "n_ofertas_equiv": len(equiv),
        "n_ofertas_premium": len(premium),
        "n_otras_monedas": len(otras_monedas),
        "sellers_unicos": len({f[3] for f in equiv}),
        "pct_envio_gratis": round(100 * sum(f[4] for f in equiv) / len(equiv)) if equiv else None,
        "precio_min": precios[0] if precios else None,
        "precio_promedio": round(statistics.mean(precios), 1) if precios else None,
        "precio_mediano": round(statistics.median(precios), 1) if precios else None,
        "precio_max": precios[-1] if precios else None,
        "premium_min": round(min(f[1] for f in premium), 1) if premium else None,
        "cobertura_baja": len(precios) < 3,
        "n_outliers_excluidos": n_outliers,
    }

    if precios:
        prom = r["precio_promedio"]
        r["brecha_pct"] = round(100 * (nuestro - prom) / prom, 1)
        if r["brecha_pct"] <= -8:
            r["veredicto_precio"] = "barato"
        elif r["brecha_pct"] <= 8:
            r["veredicto_precio"] = "alineado"
        else:
            r["veredicto_precio"] = "caro"
    else:
        r["brecha_pct"] = None
        r["veredicto_precio"] = "sin_datos"

    n = r["n_ofertas_equiv"]
    r["competencia"] = "baja" if n < 8 else ("media" if n <= 25 else "alta")

    if r["veredicto_precio"] == "sin_datos":
        r["oportunidad"] = "sin_datos"
    elif r["veredicto_precio"] == "barato" and r["competencia"] != "alta":
        r["oportunidad"] = "alta"
    elif r["veredicto_precio"] in ("barato", "alineado"):
        r["oportunidad"] = "media"
    else:
        r["oportunidad"] = "baja"

    # margen si vendemos al precio final (comision ML ~15% ya considerada en
    # el analisis de julio; aca margen bruto simple contra costo)
    r["margen_bruto_usd"] = round(nuestro - costo, 1)
    return r


def ranking(fecha=None):
    con = conectar()
    fecha = fecha or ultima_fecha(con)
    skus = [row[0] for row in con.execute("SELECT sku FROM products")]
    filas = [score_sku(con, sku, fecha) for sku in skus]
    con.close()
    orden_oport = {"alta": 0, "media": 1, "baja": 2, "sin_datos": 3}
    filas.sort(key=lambda r: (orden_oport[r["oportunidad"]],
                              r["brecha_pct"] if r["brecha_pct"] is not None else 999))
    return fecha, filas


def ofertas_detalle(fecha=None):
    """Todas las ofertas de la fecha, para la hoja cruda y el dashboard."""
    con = conectar()
    fecha = fecha or ultima_fecha(con)
    rows = con.execute(
        "SELECT s.sku, p.medida, s.clasificacion, s.marca_detectada, "
        "s.product_name, s.price, s.currency_id, s.seller_id, s.free_shipping, "
        "s.catalog_product_id "
        "FROM snapshots s JOIN products p ON p.sku=s.sku "
        "WHERE s.fecha_captura=? ORDER BY p.medida, s.price", (fecha,)).fetchall()
    con.close()
    return fecha, rows
