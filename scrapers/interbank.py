"""
Scraper para Interbank Perú — Liferay Portal + Cloudflare bypass vía playwright-stealth
URL: https://interbank.pe/promociones-catalogo
API: Liferay portlet INSTANCE_PMFRgZtSWE0U, endpoints /filter y /promos (JSON)
Estrategia: stealth Chrome, 15s espera para CF session, paginar todas las páginas,
            visitar cada página de detalle para obtener categoría y fechas.
"""
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import Stealth
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto, extraer_stock, extraer_fechas
from typing import List, Optional
import json, re, time, math


_BASE = "https://interbank.pe"
_PORTLET_BASE = (
    "https://interbank.pe/promociones-catalogo"
    "?p_p_id=pe_com_ibk_halcon_promotions_internal_PromotionCataloguePortlet_INSTANCE_PMFRgZtSWE0U"
    "&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view&p_p_cacheability=cacheLevelPage"
)
_FILTER_URL = _PORTLET_BASE + "&p_p_resource_id=%2Ffilter"
_PROMOS_URL = _PORTLET_BASE + "&p_p_resource_id=%2Fpromos"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class InterbankScraper(BaseScraper):
    nombre = "IBK"
    url_base = "https://interbank.pe/promociones-catalogo"

    def scrape(self) -> List[Promocion]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel="chrome")
            context = browser.new_context(user_agent=_UA)
            page = context.new_page()

            # Aplicar stealth ANTES del goto para bypasear Cloudflare Bot Management
            Stealth().apply_stealth_sync(page)

            print(f"[{self.nombre}] Cargando página principal ...")
            try:
                page.goto(self.url_base, wait_until="load", timeout=60000)
            except PlaywrightTimeout:
                print(f"[{self.nombre}] Timeout en goto, continuando...")

            # Espera crítica: el JS challenge de Cloudflare necesita ~10-15s
            print(f"[{self.nombre}] Esperando sesión Cloudflare (15s)...")
            time.sleep(15)

            # ── Obtener todas las promos paginando ────────────────────────────
            all_promos = self._fetch_all_promos(page)
            if not all_promos:
                print(f"[{self.nombre}] No se obtuvieron promos del API. Abortando.")
                browser.close()
                return []

            print(f"[{self.nombre}] {len(all_promos)} promos en listing. Visitando detalles...")

            promociones: List[Promocion] = []
            for i, promo_data in enumerate(all_promos, 1):
                link = promo_data.get("link", "")
                if not link:
                    continue
                if i % 20 == 0:
                    print(f"[{self.nombre}] Procesando {i}/{len(all_promos)}...")
                promo = self._parse_detail(page, link, promo_data)
                if promo:
                    promociones.append(promo)
                time.sleep(0.5)

            browser.close()

        print(f"[{self.nombre}] {len(promociones)} promociones encontradas.")
        return promociones

    # ── API helpers ───────────────────────────────────────────────────────────

    def _fetch_page(self, page, page_num: int) -> dict:
        """Llama al endpoint /promos para la página dada vía fetch() en el contexto del browser."""
        url = _PROMOS_URL + f"&page={page_num}&itemsPerPage=6"
        result = page.evaluate(
            """async (url) => {
                const r = await fetch(url);
                return { status: r.status, body: await r.text() };
            }""",
            url,
        )
        if result["status"] != 200:
            raise RuntimeError(f"API /promos page={page_num} → HTTP {result['status']}")
        return json.loads(result["body"])

    def _fetch_all_promos(self, page) -> list:
        """Pagina el endpoint /promos hasta obtener todas las promociones."""
        try:
            data = self._fetch_page(page, 1)
        except Exception as e:
            print(f"[{self.nombre}] Error en primera página: {e}")
            return []

        total = data.get("total_promotions", 0)
        items_per_page = data.get("items_per_page", 6) or 6
        total_pages = math.ceil(total / items_per_page)
        all_promos = list(data.get("promotions", []))

        print(f"[{self.nombre}] Total: {total} promos, {total_pages} páginas.")

        for p_num in range(2, total_pages + 1):
            try:
                page_data = self._fetch_page(page, p_num)
                all_promos.extend(page_data.get("promotions", []))
            except Exception as e:
                print(f"[{self.nombre}] Error en página {p_num}: {e}")
            time.sleep(0.3)

        return all_promos

    # ── Detail page ───────────────────────────────────────────────────────────

    def _parse_detail(self, page, href: str, listing: dict) -> Optional[Promocion]:
        """Visita la página de detalle y extrae categoría, fechas, stock y descripción completa."""
        url = _BASE + href if href.startswith("/") else href
        try:
            page.goto(url, wait_until="load", timeout=30000)
            time.sleep(1.5)  # Esperar a que cargue todo el contenido
        except PlaywrightTimeout:
            print(f"[{self.nombre}] Timeout en detalle: {url}")
            # Usar los datos del listing como fallback
            return self._promo_desde_listing(listing, url)

        soup = BeautifulSoup(page.content(), "lxml")

        # Categoría: primer chip de la cabecera
        cat_el = soup.select_one("a.a-promo-header__chips span.g-title")
        categoria = cat_el.get_text(strip=True) if cat_el else "General"

        # Descripción: primer <p> del bloque principal con clase in-promo
        desc_el = soup.select_one("div.a-html-content.in-promo div.a-html-content__wrapper p")
        descripcion_extraida = desc_el.get_text(strip=True) if desc_el else listing.get("description", "")

        # ── EXTRACCIÓN DE FECHAS ──────────────────────────────────────────
        fecha_inicio, fecha_fin = "", ""
        
        # Buscar fechas en múltiples ubicaciones en orden de prioridad
        locations_to_search = []
        
        # 1. En la lista de condiciones (li) de la descripción principal
        main_content = soup.select_one("div.a-html-content.in-promo div.a-html-content__wrapper")
        if main_content:
            for li in main_content.find_all("li"):
                txt = li.get_text(" ", strip=True)
                locations_to_search.append(txt)
        
        # 2. En la sección de Condiciones del acordión
        for item in soup.select("div.m-accordion-item"):
            header = item.select_one("div.m-accordion-item__header p")
            if not header:
                continue
            header_txt = header.get_text(strip=True).lower()
            if header_txt == "condiciones":
                content = item.select_one("div.m-accordion-item__content div.a-html-content__wrapper")
                if content:
                    txt = content.get_text(" ", strip=True)
                    locations_to_search.append(txt)
                    break
        
        # Buscar fechas en las ubicaciones encontradas
        for location_text in locations_to_search:
            inicio, fin = extraer_fechas(location_text)
            if inicio or fin:
                fecha_inicio, fecha_fin = inicio, fin
                break
        
        # ── EXTRACCIÓN DE STOCK ───────────────────────────────────────────
        stock = ""
        
        # Buscar stock en múltiples ubicaciones
        stock_locations = []
        
        # 1. En la descripción principal
        if main_content:
            txt = main_content.get_text(" ", strip=True)
            stock_locations.append(txt)
        
        # 2. En Condiciones
        for item in soup.select("div.m-accordion-item"):
            header = item.select_one("div.m-accordion-item__header p")
            if not header:
                continue
            header_txt = header.get_text(strip=True).lower()
            if header_txt in ("condiciones", "restricciones"):
                content = item.select_one("div.m-accordion-item__content div.a-html-content__wrapper")
                if content:
                    txt = content.get_text(" ", strip=True)
                    stock_locations.append(txt)
        
        # Buscar stock en las ubicaciones encontradas
        for location_text in stock_locations:
            extracted_stock = extraer_stock(location_text)
            if extracted_stock:
                stock = extracted_stock
                break
        
        # ── EXTRACCIÓN DE CONDICIONES ───────────────────────────────────────────
        condiciones_parts = []
        for item in soup.select("div.m-accordion-item"):
            header = item.select_one("div.m-accordion-item__header p")
            if not header:
                continue
            header_txt = header.get_text(strip=True).lower()
            if header_txt in ("condiciones", "restricciones"):
                content = item.select_one("div.m-accordion-item__content")
                if content:
                    condiciones_parts.append(content.get_text(" ", strip=True))
        condiciones = " | ".join(condiciones_parts)

        comercio = listing.get("title", "")
        precio, tipo = extraer_precio_tipo_de_texto(descripcion_extraida)

        if fecha_inicio or fecha_fin or stock:
            print(f"[{self.nombre}] ✅ Fechas: {fecha_inicio} → {fecha_fin} | Stock: {stock}")
        else:
            print(f"[{self.nombre}] ⚠️ No se extrajeron fechas/stock para: {comercio}")

        return Promocion(
            fuente=self.nombre,
            categoria=categoria,
            titulo=descripcion_extraida,
            descripcion="",
            comercio=comercio,
            precio=precio,
            tipo=tipo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            stock=stock,
            url=url,
            imagen_url=listing.get("img", ""),
            condiciones=condiciones,
        )

    def _promo_desde_listing(self, listing: dict, url: str) -> Optional[Promocion]:
        """Fallback cuando no se puede acceder a la página de detalle."""
        descripcion_extraida = listing.get("description", "")
        precio, tipo = extraer_precio_tipo_de_texto(descripcion_extraida)
        return Promocion(
            fuente=self.nombre,
            categoria="General",
            titulo=descripcion_extraida,
            descripcion="",
            comercio=listing.get("title", ""),
            precio=precio,
            tipo=tipo,
            fecha_inicio="",
            fecha_fin="",
            stock=extraer_stock(descripcion_extraida),
            url=url,
            imagen_url=listing.get("img", ""),
            condiciones="",
        )
