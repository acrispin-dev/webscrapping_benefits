"""
main.py — Runner principal.
Ejecuta los scrapers habilitados y genera output/index.html
"""
import os
import sys

# Asegura que el directorio de salida exista
os.makedirs("output", exist_ok=True)

from scrapers.falabella import FalabellaScraper
from scrapers.plin import PlinScraper
from scrapers.scotiabank import ScotiabankScraper
from scrapers.interbank import InterbankScraper
from scrapers.bbva import BBVAScraper
from scrapers.ripley import RipleyScraper
from scrapers.movistar import MovistarScraper
from html_generator import generar_html

# ── Lista de scrapers activos ─────────────────────────────────────────────────
# Comenta cualquier línea para deshabilitar un scraper individual.
SCRAPERS = [
    # FalabellaScraper(),
    # PlinScraper(),
    ScotiabankScraper()
    # InterbankScraper(),
    # BBVAScraper(),
    # RipleyScraper(),
    # MovistarScraper()
]
# ─────────────────────────────────────────────────────────────────────────────

def main():
    todas_las_promos = []
    errores = []

    for scraper in SCRAPERS:
        print(f"\n{'='*50}")
        print(f"  Scraping: {scraper.nombre}")
        print(f"{'='*50}")
        try:
            promos = scraper.scrape()
            todas_las_promos.extend(promos)
        except Exception as e:
            print(f"[ERROR] {scraper.nombre}: {e}")
            errores.append((scraper.nombre, str(e)))

    print(f"\n{'='*50}")
    print(f"  TOTAL: {len(todas_las_promos)} promociones obtenidas")
    if errores:
        print(f"  ERRORES en: {', '.join(n for n,_ in errores)}")
    print(f"{'='*50}\n")

    generar_html(todas_las_promos, ruta_salida="output/index.html")

    if todas_las_promos:
        print("\n✅ Listo. Abre output/index.html en tu navegador.")
    else:
        print("\n⚠️  No se obtuvieron promociones. Revisa output/debug_*.html para inspeccionar las páginas.")


if __name__ == "__main__":
    main()
