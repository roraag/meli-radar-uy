"""Dashboard HTML autocontenido del radar.

Salida: outputs/TireShop - Radar ML <fecha>.html
Los datos van embebidos como JSON (placeholders + .replace, nunca f-strings
con JS adentro). Filtros por segmento / prioridad / veredicto en el cliente.
"""

import json
import os

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
</div>
<script>
const RANKING = __RANKING__;
const OFERTAS = __OFERTAS__;

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

opciones();
pintar();
</script>
</body>
</html>
"""


CAMPOS_PRIVADOS = ("costo_usd", "margen_bruto_usd")  # nunca al HTML publicado


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
            .replace("__OFERTAS__", json.dumps(ofertas_json, ensure_ascii=False)))

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
