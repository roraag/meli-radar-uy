#!/bin/bash
# Corrida diaria del radar en el VPS (cron). Mismo patron que DAILY-IA-NEWS:
# captura -> dashboard -> docs/ -> push a GitHub Pages.
# Cron sugerido (06:30, despues del daily-ia-news de 06:00):
#   30 6 * * * /home/openclaw/meli-radar-uy/run-daily-vps.sh >> /home/openclaw/meli-radar-uy/cron.log 2>&1

set -e
export PATH=/usr/local/bin:/usr/bin:/bin

REPO=/home/openclaw/meli-radar-uy
cd "$REPO"

echo "=== radar $(date '+%Y-%m-%d %H:%M') ==="

# traer lo que haya pusheado la Mac (docs/data/browser.csv del scraper);
# sin esto el push de abajo rompe apenas el remoto tenga commits nuevos
/usr/bin/git pull --rebase origin main

/usr/bin/python3 radar.py
# best-sellers UY + match BR; si highlights falla un dia, el radar sale igual
/usr/bin/python3 oportunidades.py || echo "oportunidades fallo — sigo sin esa seccion"
/usr/bin/python3 dashboard.py --publicar

/usr/bin/git add docs/
/usr/bin/git -c user.name="radar-bot" -c user.email="radar@tireshop.local" \
    commit -m "radar $(date '+%Y-%m-%d')" || echo "sin cambios que commitear"
/usr/bin/git push origin main

echo "=== fin ==="
