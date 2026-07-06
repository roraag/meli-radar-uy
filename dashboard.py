"""Dashboard HTML autocontenido del radar.

Salida: outputs/TireShop - Radar ML <fecha>.html
Los datos van embebidos como JSON (placeholders + .replace, nunca f-strings
con JS adentro). Filtros por segmento / prioridad / veredicto en el cliente.
"""

import csv
import json
import os
import sqlite3

from database import conectar
from scoring import ofertas_detalle, ranking

BASE = os.path.dirname(os.path.abspath(__file__))

PLANTILLA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radar ML — TireShop</title>
<style>
  :root { --negro:#111; --amarillo:#ffd100; --gris:#666; --fondo:#f5f5f2; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:-apple-system,'Segoe UI',Roboto,sans-serif; background:var(--fondo); color:var(--negro); }
  header { background:var(--negro); color:#fff; padding:18px 28px; display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:22px; }
  header h1 span { color:var(--amarillo); }
  header .fecha { color:#bbb; font-size:13px; }
  .wrap { max-width:1240px; margin:0 auto; padding:20px 16px 60px; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:20px; }
  .kpi { background:#fff; border-radius:10px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  .kpi .v { font-size:26px; font-weight:700; }
  .kpi .l { font-size:12px; color:var(--gris); margin-top:2px; }
  .kpi.alerta .v { color:#c62828; }
  .kpi.ok .v { color:#2e7d32; }
  .filtros { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px; }
  .filtros select { padding:8px 10px; border-radius:8px; border:1px solid #ccc; background:#fff; font-size:13px; }
  table { width:100%; border-collapse:collapse; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  th { background:var(--negro); color:#fff; font-size:12px; padding:10px 8px; text-align:left; position:sticky; top:0; }
  td { padding:9px 8px; font-size:13px; border-top:1px solid #eee; }
  tr.fila { cursor:pointer; }
  tr.fila:hover { background:#fffbe6; }
  .num { text-align:right; font-variant-numeric:tabular-nums; }
  .tag { display:inline-block; padding:2px 8px; border-radius:20px; font-size:11px; font-weight:600; }
  .barato { background:#c8e6c9; color:#1b5e20; }
  .alineado { background:#fff9c4; color:#7a6400; }
  .caro { background:#ffcdd2; color:#b71c1c; }
  .sin_datos { background:#eceff1; color:#546e7a; }
  .alta { background:#111; color:var(--amarillo); }
  .media { background:#e0e0e0; color:#333; }
  .baja { background:#fafafa; color:#999; border:1px solid #ddd; }
  .cob { color:#c62828; font-size:11px; font-weight:700; }
  tr.detalle td { background:#faf9f4; padding:0; }
  .det-inner { padding:12px 16px; }
  .det-inner table { box-shadow:none; border:1px solid #eee; }
  .det-inner th { background:#444; }
  .det-inner a { color:#0d47a1; text-decoration:none; }
  .nota { margin-top:16px; font-size:12px; color:var(--gris); line-height:1.5; }
  .seccion { margin-top:38px; }
  .seccion h2 { font-size:17px; margin-bottom:4px; }
  .seccion h3 { font-size:14px; margin:20px 0 8px; }
  .seccion .sub { font-size:12px; color:var(--gris); line-height:1.5; margin-bottom:12px; }
  .seccion a { color:#0d47a1; text-decoration:none; }
  .seccion table { margin-bottom:6px; }
  .pos { color:var(--gris); font-weight:700; }
  .aprox { background:#fff3e0; color:#e65100; }
  @media (max-width:700px){ .oculta-movil { display:none; } }
</style>
</head>
<body>
<header>
  <h1>Radar ML <span>TireShop</span></h1>
  <div class="fecha">Captura: __FECHA__ &middot; comparación por medida, segmento chino/equivalente (premium solo referencia)</div>
</header>
<div class="wrap">
  <div class="kpis" id="kpis"></div>
  <div class="filtros">
    <select id="f-seg"><option value="">Segmento (todos)</option></select>
    <select id="f-pri"><option value="">Prioridad (todas)</option></select>
    <select id="f-ver"><option value="">Veredicto (todos)</option></select>
  </div>
  <table>
    <thead><tr>
      <th>Medida</th><th class="oculta-movil">Segmento</th><th>Prioridad</th>
      <th class="num">TireShop USD</th><th class="num">Prom. equiv.</th>
      <th class="num">Min</th><th class="num">Brecha %</th>
      <th>Veredicto</th><th>Oportunidad</th>
      <th class="num oculta-movil">Ofertas</th><th class="oculta-movil">Cobertura</th>
    </tr></thead>
    <tbody id="cuerpo"></tbody>
  </table>
  <p class="nota">Brecha % = (precio TireShop − promedio equivalentes) / promedio. Negativa = somos más baratos.
  Cobertura BAJA = menos de 3 ofertas equivalentes en el catálogo de ML: el promedio es poco confiable, validar a mano.
  Fuente: API de catálogo de MercadoLibre Uruguay (products/search + items). Los productos sin oferta activa no aparecen.
  Click en una fila para ver las ofertas relevadas y sus links.</p>

  <section class="seccion" id="sec-oportunidades" hidden>
    <h2>Best-sellers ML UY + precio en Brasil</h2>
    <div class="sub"><b>El ranking lo arma MercadoLibre</b> con sus datos internos de ventas (API highlights,
    captura <span id="fecha-opo"></span>): publica el orden — la columna # — pero NO la cifra de ventas de cada
    producto (ese dato no existe públicamente). El equivalente en Brasil se busca <b>por nombre</b>: es un match
    aproximado con falsos positivos frecuentes — validar SIEMPRE con los dos links antes de decidir. El precio BR
    es el de Brasil tal cual (sin flete ni impuestos). De Brasil no se traen neumáticos: por eso su tabla no tiene
    columnas BR.</div>
    <div id="cuerpo-oportunidades"></div>
  </section>

  <section class="seccion" id="sec-browser" hidden>
    <h2>Datos de browser (scraper Mac)</h2>
    <div class="sub">Relevado con browser desde la Mac (corrida manual; fecha propia: <span id="fecha-browser"></span> —
    puede ser anterior a la captura API de arriba). Cubre lo que el catálogo no ve: los accesorios (publicaciones sin
    catalogar) y la señal de demanda "+X vendidos" del detalle.</div>
    <h3>Accesorios — precios de la competencia (por unidad)</h3>
    <table>
      <thead><tr><th>SKU</th><th>Producto TireShop</th><th class="num">Ofertas</th>
      <th class="num">Mín.</th><th class="num">Promedio</th><th>Más barata de la competencia</th></tr></thead>
      <tbody id="cuerpo-accesorios"></tbody>
    </table>
    <h3>Señal de demanda — publicaciones con más vendidos</h3>
    <table>
      <thead><tr><th>Medida / producto</th><th>Publicación</th>
      <th class="num">Precio unit.</th><th class="num">Vendidos</th></tr></thead>
      <tbody id="cuerpo-vendidos"></tbody>
    </table>
  </section>
</div>
<script>
const RANKING = __RANKING__;
const OFERTAS = __OFERTAS__;
const OPORTUNIDADES = __OPORTUNIDADES__;
const BROWSER = __BROWSER__;

function esc(s){
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function kpis(filas){
  const tot = filas.length;
  const ofertas = filas.reduce((a,r)=>a+r.n_ofertas_equiv,0);
  const caras = filas.filter(r=>r.veredicto_precio==='caro').length;
  const baratas = filas.filter(r=>r.veredicto_precio==='barato').length;
  const cob = filas.filter(r=>r.cobertura_baja).length;
  const el = document.getElementById('kpis');
  el.innerHTML = '';
  const defs = [
    [tot, 'medidas monitoreadas', ''],
    [ofertas, 'ofertas equivalentes', ''],
    [baratas, 'medidas donde somos baratos', 'ok'],
    [caras, 'medidas donde quedamos caros', caras>0?'alerta':'ok'],
    [cob, 'medidas con cobertura baja', cob>8?'alerta':''],
  ];
  for (const [v,l,cls] of defs){
    const d = document.createElement('div');
    d.className = 'kpi ' + cls;
    d.innerHTML = '<div class="v">'+v+'</div><div class="l">'+l+'</div>';
    el.appendChild(d);
  }
}

function opciones(){
  const sel = {seg:new Set(), pri:new Set(), ver:new Set()};
  RANKING.forEach(r=>{ sel.seg.add(r.segmento); sel.pri.add(r.prioridad); sel.ver.add(r.veredicto_precio); });
  const mapa = {seg:'f-seg', pri:'f-pri', ver:'f-ver'};
  for (const k in mapa){
    const s = document.getElementById(mapa[k]);
    [...sel[k]].sort().forEach(v=>{
      const o = document.createElement('option'); o.value=v; o.textContent=v; s.appendChild(o);
    });
    s.addEventListener('change', pintar);
  }
}

function filaDetalle(sku){
  const ofs = OFERTAS.filter(o=>o.sku===sku);
  if (!ofs.length) return '<div class="det-inner">Sin ofertas relevadas para esta medida.</div>';
  let h = '<div class="det-inner"><table><thead><tr><th>Clasif.</th><th>Marca</th><th>Producto</th><th class="num">Precio</th><th>Envio</th><th>Link</th></tr></thead><tbody>';
  for (const o of ofs){
    h += '<tr><td>'+o.clasif+'</td><td>'+o.marca+'</td><td>'+o.nombre+'</td>'+
         '<td class="num">'+o.moneda+' '+o.precio+'</td>'+
         '<td>'+(o.gratis?'gratis':'-')+'</td>'+
         '<td><a href="'+o.link+'" target="_blank">ver en ML</a></td></tr>';
  }
  return h + '</tbody></table></div>';
}

function pintar(){
  const fs = document.getElementById('f-seg').value;
  const fp = document.getElementById('f-pri').value;
  const fv = document.getElementById('f-ver').value;
  const filas = RANKING.filter(r=>
    (!fs || r.segmento===fs) && (!fp || r.prioridad===fp) && (!fv || r.veredicto_precio===fv));
  kpis(filas);
  const tb = document.getElementById('cuerpo');
  tb.innerHTML = '';
  for (const r of filas){
    const tr = document.createElement('tr');
    tr.className = 'fila';
    tr.innerHTML =
      '<td><b>'+r.medida+'</b></td>'+
      '<td class="oculta-movil">'+r.segmento+'</td>'+
      '<td>'+r.prioridad+'</td>'+
      '<td class="num"><b>'+r.precio_final_usd+'</b></td>'+
      '<td class="num">'+(r.precio_promedio ?? '-')+'</td>'+
      '<td class="num">'+(r.precio_min ?? '-')+'</td>'+
      '<td class="num">'+(r.brecha_pct===null?'-':r.brecha_pct)+'</td>'+
      '<td><span class="tag '+r.veredicto_precio+'">'+r.veredicto_precio+'</span></td>'+
      '<td><span class="tag '+r.oportunidad+'">'+r.oportunidad+'</span></td>'+
      '<td class="num oculta-movil">'+r.n_ofertas_equiv+'</td>'+
      '<td class="oculta-movil">'+(r.cobertura_baja?'<span class="cob">BAJA</span>':'ok')+'</td>';
    tr.addEventListener('click', ()=>{
      const sig = tr.nextElementSibling;
      if (sig && sig.classList.contains('detalle')){ sig.remove(); return; }
      document.querySelectorAll('tr.detalle').forEach(e=>e.remove());
      const det = document.createElement('tr');
      det.className = 'detalle';
      det.innerHTML = '<td colspan="11">'+filaDetalle(r.sku)+'</td>';
      tr.after(det);
    });
    tb.appendChild(tr);
  }
}

function pintarOportunidades(){
  if (!OPORTUNIDADES || !OPORTUNIDADES.filas.length) return;
  document.getElementById('sec-oportunidades').hidden = false;
  document.getElementById('fecha-opo').textContent = OPORTUNIDADES.fecha;
  const cont = document.getElementById('cuerpo-oportunidades');
  const cats = [...new Set(OPORTUNIDADES.filas.map(f=>f.cat))];
  for (const cat of cats){
    const esNeum = cat.indexOf('Neum')>=0;  // neumaticos: sin columnas BR (no se traen de Brasil)
    const h = document.createElement('h3');
    h.textContent = esNeum ? 'Neumáticos — los más vendidos según MercadoLibre' : cat;
    cont.appendChild(h);
    const t = document.createElement('table');
    t.innerHTML = esNeum
      ? '<thead><tr><th>#</th><th>Producto (UY)</th><th class="num">Precio UY</th></tr></thead>'
      : '<thead><tr><th>#</th><th>Producto (UY)</th><th class="num">Precio UY</th>'+
        '<th>Equivalente BR</th><th class="num">Precio BR</th></tr></thead>';
    const tb = document.createElement('tbody');
    for (const f of OPORTUNIDADES.filas.filter(x=>x.cat===cat)){
      const uy = f.precio_uy!==null ? esc(f.moneda_uy)+' '+f.precio_uy : 's/precio';
      const tr = document.createElement('tr');
      let celdas = '<td class="pos">'+f.pos+'</td>'+
        '<td><a href="'+esc(f.link_uy)+'" target="_blank">'+esc(f.nombre)+'</a></td>'+
        '<td class="num">'+uy+'</td>';
      if (!esNeum){
        const br = f.precio_br!==null
          ? '<a href="'+esc(f.br_link)+'" target="_blank">'+esc(f.br_nombre)+'</a> '+
            '<span class="tag aprox">match aprox. — validar</span>'
          : '-';
        celdas += '<td>'+br+'</td>'+
          '<td class="num">'+(f.precio_br!==null ? 'BRL '+f.precio_br : '-')+'</td>';
      }
      tr.innerHTML = celdas;
      tb.appendChild(tr);
    }
    t.appendChild(tb);
    cont.appendChild(t);
  }
}

function pintarBrowser(){
  if (!BROWSER) return;
  document.getElementById('sec-browser').hidden = false;
  document.getElementById('fecha-browser').textContent = BROWSER.fecha;
  const ta = document.getElementById('cuerpo-accesorios');
  for (const a of BROWSER.accesorios){
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>'+esc(a.sku)+'</td><td>'+esc(a.medida)+'</td>'+
      '<td class="num">'+a.n+'</td>'+
      '<td class="num">'+esc(a.moneda)+' '+a.minimo+'</td>'+
      '<td class="num">'+esc(a.moneda)+' '+a.promedio+'</td>'+
      '<td><a href="'+esc(a.mejor_link)+'" target="_blank">'+esc(a.mejor_titulo)+'</a></td>';
    ta.appendChild(tr);
  }
  const tv = document.getElementById('cuerpo-vendidos');
  for (const v of BROWSER.vendidos){
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><b>'+esc(v.medida)+'</b></td>'+
      '<td><a href="'+esc(v.link)+'" target="_blank">'+esc(v.titulo)+'</a></td>'+
      '<td class="num">'+esc(v.moneda)+' '+v.precio_unitario+'</td>'+
      '<td class="num"><b>+'+v.vendidos+'</b></td>';
    tv.appendChild(tr);
  }
}

opciones();
pintar();
pintarOportunidades();
pintarBrowser();
</script>
</body>
</html>
"""


CAMPOS_PRIVADOS = ("costo_usd", "margen_bruto_usd")  # nunca al HTML publicado

# orden de presentacion de las categorias de oportunidades (nuestro rubro primero)
ORDEN_CATEGORIAS = {"Neumaticos": 0, "Acc. Vehiculos (general)": 1,
                    "Acc. de Auto y Camioneta": 2, "Repuestos Autos y Camionetas": 3}


def datos_oportunidades():
    """Best-sellers UY + match Brasil (tabla oportunidades, ultima captura).
    Devuelve None si la tabla no existe o esta vacia (el cron del VPS puede
    correr antes que oportunidades.py alguna vez)."""
    con = conectar()
    try:
        fecha = con.execute(
            "SELECT MAX(fecha_captura) FROM oportunidades").fetchone()[0]
    except sqlite3.OperationalError:
        fecha = None
    if not fecha:
        con.close()
        return None
    rows = con.execute(
        "SELECT categoria_nombre, posicion, nombre, precio_uy, moneda_uy, "
        "link_uy, precio_br, match_br_id, match_br_nombre "
        "FROM oportunidades WHERE fecha_captura=?", (fecha,)).fetchall()
    con.close()
    filas = [{
        "cat": r[0], "pos": r[1], "nombre": r[2], "precio_uy": r[3],
        "moneda_uy": r[4], "link_uy": r[5], "precio_br": r[6],
        "br_link": ("https://www.mercadolibre.com.br/p/" + r[7]) if r[7] else None,
        "br_nombre": r[8],
    } for r in rows]
    filas.sort(key=lambda f: (ORDEN_CATEGORIAS.get(f["cat"], 9), f["pos"] or 999))
    return {"fecha": fecha, "filas": filas}


def datos_browser():
    """Resumen del CSV del scraper Mac (docs/data/browser.csv). La fecha es
    propia del scraper (corrida manual): puede diferir de la captura API.
    Devuelve None si el CSV todavia no llego al repo."""
    path = os.path.join(BASE, "docs", "data", "browser.csv")
    if not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        filas = list(csv.DictReader(f))
    if not filas:
        return None
    fecha = max(f["fecha_captura"] for f in filas)

    # accesorios: min/promedio del precio unitario por SKU, en la moneda
    # dominante del SKU (si un listado mezcla USD y UYU, gana la mayoritaria)
    por_sku = {}
    for f in filas:
        if f["familia"] == "accesorio" and f["clasificacion"] == "equivalente":
            por_sku.setdefault(f["sku"], []).append(f)
    accesorios = []
    for sku, items in sorted(por_sku.items()):
        monedas = [i["moneda"] for i in items]
        moneda = max(set(monedas), key=monedas.count)
        mismos = [i for i in items if i["moneda"] == moneda]
        precios = [float(i["precio_unitario"]) for i in mismos]
        mejor = min(mismos, key=lambda i: float(i["precio_unitario"]))
        accesorios.append({
            "sku": sku, "medida": items[0]["medida"], "n": len(mismos),
            "moneda": moneda, "minimo": round(min(precios)),
            "promedio": round(sum(precios) / len(precios)),
            "mejor_titulo": mejor["titulo"], "mejor_link": mejor["link"],
        })

    vendidos = [{
        "medida": f["medida"], "titulo": f["titulo"],
        "precio_unitario": float(f["precio_unitario"]), "moneda": f["moneda"],
        "vendidos": int(f["vendidos"]), "link": f["link"],
    } for f in filas if f["vendidos"]]
    vendidos.sort(key=lambda v: -v["vendidos"])
    return {"fecha": fecha, "accesorios": accesorios, "vendidos": vendidos[:20]}


def generar():
    fecha, filas = ranking()
    filas = [{k: v for k, v in r.items() if k not in CAMPOS_PRIVADOS}
             for r in filas]
    _, ofertas = ofertas_detalle(fecha)
    ofertas_json = [{
        "sku": o[0], "medida": o[1], "clasif": o[2], "marca": o[3],
        "nombre": o[4], "precio": o[5], "moneda": o[6], "gratis": bool(o[8]),
        "link": "https://www.mercadolibre.com.uy/p/" + str(o[9]),
    } for o in ofertas]

    html = (PLANTILLA
            .replace("__FECHA__", fecha)
            .replace("__RANKING__", json.dumps(filas, ensure_ascii=False))
            .replace("__OFERTAS__", json.dumps(ofertas_json, ensure_ascii=False))
            .replace("__OPORTUNIDADES__",
                     json.dumps(datos_oportunidades(), ensure_ascii=False))
            .replace("__BROWSER__",
                     json.dumps(datos_browser(), ensure_ascii=False)))

    os.makedirs(os.path.join(BASE, "outputs"), exist_ok=True)
    path = os.path.join(BASE, "outputs", f"TireShop - Radar ML {fecha}.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"Dashboard: {path}")
    return path, html, fecha


def publicar():
    """Modo newsletter: deja el dashboard del dia en docs/ (index + archive),
    listo para commit + push a GitHub Pages. Mismo patron que daily-ia-news."""
    _, html, fecha = generar()
    docs = os.path.join(BASE, "docs")
    os.makedirs(os.path.join(docs, "archive"), exist_ok=True)
    for destino in (os.path.join(docs, "index.html"),
                    os.path.join(docs, "archive", f"{fecha}.html")):
        with open(destino, "w") as f:
            f.write(html)
        print(f"Publicado: {destino}")


if __name__ == "__main__":
    import sys
    if "--publicar" in sys.argv:
        publicar()
    else:
        generar()
