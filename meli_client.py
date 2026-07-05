"""Cliente de la API de MercadoLibre para meli-radar-uy.

Maneja el token de usuario guardado en ~/.config/meli-radar-uy/.env:
- Usa MELI_ACCESS_TOKEN para las llamadas.
- Si vence (401), lo renueva con MELI_REFRESH_TOKEN y reescribe el .env
  (el refresh_token de ML es de un solo uso: cada renovación entrega uno nuevo).

Nota de negocio: /sites/MLU/search está cerrado para apps no certificadas.
La vía de datos es la API de catálogo:
  - /products/search  -> productos de catálogo por keyword
  - /products/{id}/items -> ofertas reales (precio, seller, envío) por producto
"""

import os
import time

import requests

ENV_PATH = os.path.expanduser("~/.config/meli-radar-uy/.env")
API = "https://api.mercadolibre.com"
PAUSA_ENTRE_LLAMADAS = 0.15  # segundos; el límite es 18.000/h, esto es holgado


def _leer_env():
    env = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
    return env


def _escribir_env(env):
    with open(ENV_PATH, "w") as f:
        for k, v in env.items():
            f.write(f"{k}={v}\n")
    os.chmod(ENV_PATH, 0o600)


class MeliClient:
    def __init__(self):
        self.env = _leer_env()
        faltantes = [k for k in ("MELI_CLIENT_ID", "MELI_CLIENT_SECRET",
                                 "MELI_ACCESS_TOKEN", "MELI_REFRESH_TOKEN")
                     if k not in self.env]
        if faltantes:
            raise RuntimeError(f"Faltan claves en {ENV_PATH}: {faltantes}")

    def _refrescar_token(self):
        print("  [token vencido, renovando...]")
        r = requests.post(f"{API}/oauth/token", data={
            "grant_type": "refresh_token",
            "client_id": self.env["MELI_CLIENT_ID"],
            "client_secret": self.env["MELI_CLIENT_SECRET"],
            "refresh_token": self.env["MELI_REFRESH_TOKEN"],
        }, timeout=30)
        r.raise_for_status()
        d = r.json()
        self.env["MELI_ACCESS_TOKEN"] = d["access_token"]
        self.env["MELI_REFRESH_TOKEN"] = d["refresh_token"]  # el viejo ya no sirve
        _escribir_env(self.env)
        print("  [token renovado y .env actualizado]")

    def get(self, path, params=None, _reintento=True):
        """GET autenticado con renovación automática y tolerancia a rate limit."""
        time.sleep(PAUSA_ENTRE_LLAMADAS)
        headers = {"Authorization": f"Bearer {self.env['MELI_ACCESS_TOKEN']}"}
        try:
            r = requests.get(f"{API}{path}", params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            print(f"  [error de red en {path}: {e} — reintento único en 5s]")
            time.sleep(5)
            r = requests.get(f"{API}{path}", params=params, headers=headers, timeout=30)

        if r.status_code == 401 and _reintento:
            self._refrescar_token()
            return self.get(path, params, _reintento=False)
        if r.status_code == 429:
            print("  [rate limit — pausa 30s]")
            time.sleep(30)
            return self.get(path, params, _reintento=False)
        return r

    # ---- endpoints del radar ----

    def buscar_productos(self, keyword, limit=20, offset=0):
        """Productos de catálogo MLU para una keyword. Devuelve (total, results)."""
        r = self.get("/products/search", {
            "status": "active", "site_id": "MLU",
            "q": keyword, "limit": limit, "offset": offset,
        })
        if r.status_code != 200:
            return 0, []
        d = r.json()
        return d.get("paging", {}).get("total", 0), d.get("results", [])

    def ofertas_de_producto(self, product_id):
        """Ofertas activas de un producto de catálogo.
        404 = producto sin ofertas en MLU (normal, se devuelve lista vacía)."""
        r = self.get(f"/products/{product_id}/items")
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
