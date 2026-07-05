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
5. Exporta Excel + dashboard HTML en `outputs/`.

## Uso

```bash
python3 radar.py                    # captura completa (27 medidas, ~10-15 min)
python3 radar.py 265/70R16          # solo algunas medidas
python3 export.py                   # Excel del ranking + ofertas
python3 dashboard.py                # dashboard HTML autocontenido
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
  equivalentes): en esos casos, validar a mano o con browser antes de decidir.
- `sold_quantity` ya no existe en la API: la "demanda" es un proxy por
  cantidad de oferta y competencia, no ventas reales.
- Los precios comparados son solo USD (así se publican los neumáticos en UY).

## Historia

- 2026-07-05: primera versión. Solo neumáticos; los accesorios (tazas,
  tornillos) casi no están catalogados en ML → pendiente fallback browser.
