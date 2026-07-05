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
def _resolver_csv(env_var, nombre):
    path = os.environ.get(env_var, os.path.join(os.path.dirname(BASE), nombre))
    if not os.path.exists(path):
        alt = os.path.expanduser(f"~/.config/meli-radar-uy/{nombre}")
        if os.path.exists(alt):
            return alt
    return path


CSV_FUENTE = _resolver_csv("MELI_RADAR_CSV", "Neumaticos_etapa1_margen_ML.csv")
CSV_ACCESORIOS = _resolver_csv("MELI_RADAR_CSV_ACC", "Accesorios_etapa1_precios_ML.csv")

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
    """Lee el CSV fuente de neumáticos de TireShop (fuente de verdad de precios)."""
    skus = []
    with open(CSV_FUENTE) as f:
        for r in csv.DictReader(f):
            medida = r["medida"].strip()
            skus.append({
                "sku": f"NEU-{r['codigo_tireshop']}",
                "familia": "neumatico",
                "moneda": "USD",
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


# --- accesorios (tazas, tornillos, tuercas, válvulas; precios en $U) ---

STOPWORDS_ACC = {"RUEDA", "RUEDAS", "DE", "P/", "PACK", "C/", "CROMADOS",
                 "CROMADAS", "BLACK", "ARANDELA", "NEUMATICOS", "EXAGONO"}


def _normalizar_medida_acc(texto):
    """12X1,50 / 12x1.50 / 12 x 1,5 -> 12X1.5 (para comparar tornillos/tuercas)."""
    t = texto.upper().replace(",", ".").replace(" ", "")
    return re.sub(r"(\d\.\d)0\b", r"\1", t)


def tokens_accesorio(articulo):
    """Tipo (TAZA/TORNILLO/...) + tokens distintivos (modelos, medidas, rodado).
    Tokeniza ANTES de normalizar: la normalización quita espacios y si se
    aplica primero deja un token gigante inservible."""
    partes = re.split(r"[\s/\-]+", articulo.upper().replace('"', ""))
    partes = [_normalizar_medida_acc(p) for p in partes if p]
    tipo = partes[0].rstrip("S")  # TAZAS -> TAZA
    resto = [p for p in partes[1:] if p and p not in STOPWORDS_ACC]
    return tipo, resto


def relevancia_accesorio(articulo, nombre):
    """Relevante si el nombre trae el tipo de pieza y algún token distintivo."""
    tipo, distintivos = tokens_accesorio(articulo)
    n = _normalizar_medida_acc(nombre)
    if tipo not in n:
        return False
    return any(tok in n for tok in distintivos) if distintivos else True


def cargar_accesorios():
    """Lee el CSV de accesorios (generado desde el xlsx de precios de junio)."""
    if not os.path.exists(CSV_ACCESORIOS):
        print(f"  [sin CSV de accesorios en {CSV_ACCESORIOS} — solo neumáticos]")
        return []
    skus = []
    with open(CSV_ACCESORIOS) as f:
        for r in csv.DictReader(f):
            articulo = r["articulo"].strip()
            tipo, distintivos = tokens_accesorio(articulo)
            keywords = " ".join([tipo.lower()] + [d.lower() for d in distintivos][:3])
            skus.append({
                "sku": r["sku"],
                "familia": "accesorio",
                "moneda": "UYU",
                "medida": articulo,  # el articulo cumple el rol de "medida" en tablas
                "segmento": r["categoria"],
                "marca_referencial": "",
                "costo_usd": float(r["costo_uy"]),          # en $U (nombre legado)
                "precio_final_usd": float(r["precio_sugerido_uy"]),  # en $U
                "mercado_min_usd": None,
                "mercado_tipico_usd": None,
                "prioridad": r["prioridad"],
                "keywords": keywords,
            })
    return skus


def capturar(filtro_medidas=None):
    cliente = MeliClient()
    con = conectar()
    hoy = datetime.date.today().isoformat()

    # Los accesorios NO entran a la corrida por default: el catalogo de ML
    # casi no los cubre (los sellers usan publicaciones sin catalogar) y la
    # API daria veredictos basura. Fuente pendiente: scraper browser (fase 2).
    # Se fuerzan con: python3 radar.py accesorios
    skus = cargar_skus()
    if filtro_medidas:
        if [f for f in filtro_medidas if f.lower() == "accesorios"]:
            skus = cargar_accesorios()
        elif [f for f in filtro_medidas if f.lower() == "neumaticos"]:
            pass  # ya son solo neumaticos
        else:
            skus += cargar_accesorios()
            objetivo = {normalizar(m) for m in filtro_medidas}
            skus = [s for s in skus
                    if normalizar(s["medida"]) in objetivo or s["sku"] in filtro_medidas]
    print(f"Corrida {hoy} — {len(skus)} SKUs\n")

    total_ofertas = 0
    for s in skus:
        guardar_producto(con, s)
        total, productos = cliente.buscar_productos(s["keywords"],
                                                    limit=MAX_PRODUCTOS_POR_SKU)
        relevantes, ofertas_sku = 0, 0
        for pos, p in enumerate(productos, start=1):
            nombre = p.get("name", "")
            if s["familia"] == "accesorio":
                clasif = ("equivalente"
                          if relevancia_accesorio(s["medida"], nombre)
                          else "no_relevante")
            else:
                clasif = clasificar(s["medida"], nombre)
            if clasif == "no_relevante":
                continue
            relevantes += 1
            # los accesorios se venden por juego/pack (igual que nuestros
            # precios): NO se convierte a unitario, solo los neumaticos
            unidades = unidades_kit(nombre) if s["familia"] == "neumatico" else 1
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
        print(f"  {s['medida'][:32]:<32} [{s['prioridad']:<10}] "
              f"{total:>5} en catálogo | {relevantes:>2} relevantes | "
              f"{ofertas_sku:>3} ofertas")

    con.close()
    print(f"\nListo: {total_ofertas} ofertas guardadas en data/meli.db")


if __name__ == "__main__":
    capturar(sys.argv[1:] or None)
