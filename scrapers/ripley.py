"""
Scraper para Banco Ripley Perú — Promociones
URL: https://www.bancoripley.com.pe/promociones/default.html

La página carga las promos vía Firebase Realtime Database (JS).
Se necesita Playwright para renderizar el contenido.
Cada categoría carga su data cuando el tab correspondiente es activado.
La estructura de cada tarjeta está en div.fixMarginMovileNP con data-attributes.
"""
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto
from typing import List

_URL  = "https://www.bancoripley.com.pe/promociones/default.html"
_BASE = "https://www.bancoripley.com.pe/promociones"
_UA   = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# data-category del tab → categoría display
_CAT_DISPLAY = {
    'restofans':       'RestoFans (Jueves)',
    'restaurantes':    'Restaurantes',
    'supermercados':   'Supermercados',
    'entretenimiento': 'Entretenimiento',
    'viajaydisfruta':  'Automotriz y Viajes',
    'mallaventura':    'Mall Aventura',
    'bienestar':       'Bienestar',
}


class RipleyScraper(BaseScraper):
    nombre   = "Banco Ripley"
    url_base = _URL

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Cargando {_URL} ...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_UA)

            try:
                page.goto(_URL, wait_until='load', timeout=45000)
            except PlaywrightTimeout:
                print(f"[{self.nombre}] Timeout en goto, continuando...")

            # Esperar primer lote de tarjetas (categoría activa por defecto: restofans)
            try:
                page.wait_for_selector('.fixMarginMovileNP', timeout=25000)
                print(f"[{self.nombre}] Primera categoría cargada.")
            except PlaywrightTimeout:
                print(f"[{self.nombre}] No aparecieron tarjetas. Guardando debug.")
                with open("output/debug_ripley.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                browser.close()
                return []

            # Obtener lista de categorías desde el DOM
            tab_cats: list = page.evaluate("""
                () => Array.from(
                    document.querySelectorAll('a.action-tab[data-category]'),
                    t => t.getAttribute('data-category')
                )
            """)
            print(f"[{self.nombre}] Tabs: {tab_cats}")

            # Activar cada tab via JS para que Firebase cargue sus datos
            for cat in tab_cats:
                try:
                    page.evaluate(f"""
                        () => {{
                            const t = document.querySelector(
                                'a.action-tab[data-category="{cat}"]'
                            );
                            if (t) t.click();
                        }}
                    """)
                    page.wait_for_timeout(2500)
                except Exception:
                    pass

            # Espera adicional para que terminen las últimas llamadas a Firebase
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        promociones = _parsear(soup, self.nombre)
        print(f"[{self.nombre}] {len(promociones)} promociones encontradas.")
        return promociones


# ── Parsing del HTML renderizado ──────────────────────────────────────────────

def _parsear(soup: BeautifulSoup, fuente: str) -> List[Promocion]:
    """
    Recorre todas las secciones de contenido (content*-{cat_key}) y
    extrae una Promocion por cada tarjeta .fixMarginMovileNP.
    """
    promos: List[Promocion] = []
    seen_urls: set = set()

    for section in soup.find_all(id=re.compile(r'^content[A-Za-z]+-[a-z]+')):
        sec_id = section.get('id', '')
        if 'Title' in sec_id or 'pagination' in sec_id.lower():
            continue

        m = re.search(r'-([a-z]+)$', sec_id)
        cat_key   = m.group(1) if m else sec_id
        categoria = _CAT_DISPLAY.get(cat_key, cat_key.title())

        for card in section.select('.fixMarginMovileNP'):
            promo = _parse_card(card, fuente, categoria, seen_urls)
            if promo:
                promos.append(promo)

    return promos


def _parse_card(
    card, fuente: str, categoria: str, seen_urls: set
) -> 'Promocion | None':
    comercio = _texto(card, '.fontTitlePromoBottom').strip()
    if not comercio:
        return None

    precio_txt = re.sub(r'\s+', ' ',
                        _texto(card, '.fontTitlePromoBottomPrice')).strip()
    descripcion = _texto(card, '.fontDescripcionPromoBottom').strip()
    img_url     = _bg_url(card)

    link = card.select_one('a[href]')
    href = link['href'] if link else ''
    if href and not href.startswith('http'):
        href = _BASE + '/' + href.lstrip('/')

    if href and href in seen_urls:
        return None
    if href:
        seen_urls.add(href)

    texto_full = f"{comercio} {precio_txt} {descripcion}"
    precio, tipo = extraer_precio_tipo_de_texto(texto_full)
    tipo  = tipo or 'Beneficio'
    titulo = f"{comercio} — {precio_txt}" if precio_txt else comercio

    return Promocion(
        fuente       = fuente,
        categoria    = categoria,
        titulo       = titulo,
        descripcion  = descripcion,
        comercio     = comercio,
        precio       = precio,
        tipo         = tipo,
        fecha_inicio = '',
        fecha_fin    = '',
        stock        = '',
        url          = href or _URL,
        imagen_url   = img_url,
        condiciones  = '',
    )


def _texto(tag, selector: str) -> str:
    el = tag.select_one(selector)
    return el.get_text(' ', strip=True) if el else ''


def _bg_url(card) -> str:
    """Extrae la URL de imagen del estilo background: url(...) del div imagen."""
    div = card.select_one('.boxContainerNewPromoTopChild2')
    if not div:
        return ''
    style = div.get('style', '')
    m = re.search(r'url\(["\']?([^"\')\s]+)["\']?\)', style)
    return m.group(1) if m else ''


