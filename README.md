# meli-radar-uy — Radar de competencia en MercadoLibre Uruguay

Monitorea los precios de la competencia para los neumáticos de TireShop,
comparando **siempre por medida** contra el segmento **chino/equivalente**
(las marcas premium quedan como referencia secundaria).

## Qué hace

1. Lee las 27 medidas de `../Neumaticos_etapa1_margen_ML.csv` (fuente de verdad).
2. Busca cada medida en la **API de catálogo** de ML UY (`/products/search`)
   y baja las ofertas activas de cada producto (`/products/{id}/items`).
3. Guarda todo en `data/meli.db` (histórico por fecha de captura).
4. Calcula veredictos: barato / alineado / caro (±8% vs promedio equivalente),
   nivel de competencia y oportunidad.
5. **Oportunidades UY↔BR** (`oportunidades.py`): best-sellers reales por categoría
   (`/highlights/MLU/category/{id}`) + precio del equivalente en ML Brasil
   (match por nombre = aproximado, el dashboard lo marca "a validar").
   Regla: de Brasil NO se traen neumáticos; el costo BR es el precio tal cual.
6. **Scraper browser** (`scraper.py`, corre EN LA MAC): accesorios (publicaciones
   sin catalogar que la API no ve) + señal de demanda "+X vendidos" del detalle.
   Publica `docs/data/browser.csv` al repo vía `gh api`; el dashboard lo integra.
7. Exporta Excel + dashboard HTML en `outputs/` (y a `docs/` para GitHub Pages).

## Qué corre dónde (¡importante!)

| Componente | Dónde | Cuándo | Por qué |
|---|---|---|---|
| `radar.py`, `oportunidades.py`, `dashboard.py` | VPS (cron 06:30) | diario | usan la API (el VPS es dueño del refresh_token) |
| `scraper.py` | **Mac, manual** (~semanal) | cuando Rodrigo quiera | ML bloquea el browser desde IPs de datacenter (account-verification desde Hetzner; verificado 05-jul con 3 variantes, stealth incluido). Desde IP residencial pasa sin fricción |

El repo git canónico vive en el VPS; la copia de Drive en la Mac NO es git.
Flujo de cambios: editar en Mac → scp al VPS → probar → commit/push desde el VPS.
El cron hace `git pull --rebase` antes de correr para traer el `browser.csv`
que la Mac pushea por su lado.

## Uso

```bash
# En el VPS (o local con la db):
python3 radar.py                    # captura completa (27 medidas, ~10-15 min)
python3 radar.py 265/70R16          # solo algunas medidas
python3 oportunidades.py            # best-sellers UY + match Brasil
python3 export.py                   # Excel del ranking + ofertas + oportunidades
python3 dashboard.py                # dashboard HTML autocontenido

# En la Mac (browser, IP residencial):
python3 scraper.py --publicar       # accesorios + neumáticos (~20 min) y sube el CSV
python3 scraper.py accesorios       # solo accesorios
python3 scraper.py 175/70R13        # solo esas medidas
```

## Credenciales

En `~/.config/meli-radar-uy/.env` (fuera de Drive, no mover):
client_id/secret de la app **Radar TireShop UY** + tokens. El access token
dura 6 h; el cliente lo renueva solo con el refresh_token y reescribe el .env
(el refresh de ML es de un solo uso).

## Limitaciones (leer antes de decidir con esto)

- **`/sites/MLU/search` está cerrado** para apps no certificadas (403).
  Se usa la API de catálogo: solo ve **publicaciones catalogadas**. Los
  chinos genéricos publicados "sueltos" (sin catálogo) NO aparecen acá.
  Por eso cada medida trae la bandera `cobertura_baja` (menos de 3 ofertas
  equivalentes): en esos casos manda el dato del scraper browser.
- `sold_quantity` ya no existe en la API: la señal de ventas reales viene
  del scraper ("+X vendidos" del detalle), solo para los primeros ~3
  relevantes por medida. El resto sigue siendo proxy por oferta/competencia.
- El match UY↔BR de oportunidades es **por nombre**: tiene falsos positivos
  frecuentes (quedó documentado con ejemplos el 05-jul). Nunca decidir por el
  precio BR sin abrir los dos links.
- Los precios comparados de neumáticos son solo USD; los accesorios se
  comparan en la moneda dominante del listado (casi siempre $U).
- La fecha del bloque "browser" del dashboard es propia (corrida manual de la
  Mac): puede ser más vieja que la captura API del día.

## Historia

- 2026-07-05 (fase 2): oportunidades UY↔BR (highlights + match MLB) y scraper
  browser en la Mac (accesorios + vendidos; el VPS quedó descartado para
  scraping por bloqueo de IP de ML). Dashboard con 2 secciones nuevas.
- 2026-07-05: primera versión. Solo neumáticos; los accesorios (tazas,
  tornillos) casi no están catalogados en ML → pendiente fallback browser.
