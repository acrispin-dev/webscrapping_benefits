"""
Scraper para Movistar Perú — Club Movistar
URL: https://www.movistar.com.pe/club-movistar
"""
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto, extraer_stock, extraer_fechas, extraer_comercio
from typing import List
import time


class MovistarScraper(BaseScraper):
    nombre = "Movistar"
    url_base = "https://www.movistar.com.pe/club-movistar"

    def scrape(self) -> List[Promocion]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            print(f"[{self.nombre}] Cargando {self.url_base} ...")
            try:
                page.goto(self.url_base, wait_until="networkidle", timeout=35000)
            except PlaywrightTimeout:
                print(f"[{self.nombre}] Timeout, usando lo disponible...")

            try:
                page.wait_for_selector(
                    "[class*='benefit'], [class*='promo'], [class*='club'], [class*='card'], article",
                    timeout=12000
                )
            except PlaywrightTimeout:
                pass

            for _ in range(5):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(0.8)

            html = page.content()
            context.close()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        promociones = self._parsear(soup)
        print(f"[{self.nombre}] {len(promociones)} promociones encontradas.")
        return promociones

    def _parsear(self, soup: BeautifulSoup) -> List[Promocion]:
        promociones: List[Promocion] = []

        selectores = [
            "[class*='benefit']",
            "[class*='Benefit']",
            "[class*='club']",
            "[class*='Club']",
            "[class*='promo']",
            "[class*='Promo']",
            "[class*='card']",
            "[class*='Card']",
            "article",
            "li[class]",
        ]

        tarjetas = []
        for selector in selectores:
            candidatos = soup.select(selector)
            candidatos = [t for t in candidatos if t.get_text(strip=True)]
            if len(candidatos) >= 2:
                tarjetas = candidatos
                print(f"[{self.nombre}] Selector: '{selector}' → {len(tarjetas)} tarjetas")
                break

        if not tarjetas:
            print(f"[{self.nombre}] No se encontraron tarjetas, guardando debug.")
            with open("output/debug_movistar.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            return []

        for tarjeta in tarjetas:
            titulo = _texto(tarjeta, ["h2", "h3", "h4", "[class*='title']", "[class*='Title']", "[class*='name']"])
            descripcion = _texto(tarjeta, ["p", "[class*='desc']", "[class*='text']", "[class*='detail']"])
            descuento = _texto(tarjeta, ["[class*='discount']", "[class*='benefit']", "[class*='offer']", "strong", "b"])
            categoria = _texto(tarjeta, ["[class*='categ']", "[class*='tag']", "[class*='type']"])
            fecha = _texto(tarjeta, ["[class*='date']", "[class*='valid']", "[class*='vigencia']", "[class*='fecha']", "time"])
            imagen = tarjeta.select_one("img")
            img_url = imagen.get("src", "") or imagen.get("data-src", "") if imagen else ""
            if img_url and img_url.startswith("//"):
                img_url = "https:" + img_url
            enlace = tarjeta.select_one("a")
            href = enlace.get("href", "") if enlace else ""
            if href and href.startswith("/"):
                href = "https://www.movistar.com.pe" + href

            texto_completo = f"{titulo} {descripcion} {descuento}"
            precio, tipo = extraer_precio_tipo_de_texto(texto_completo)
            stock = extraer_stock(texto_completo)
            fecha_inicio, fecha_fin_d = extraer_fechas(fecha)
            if not fecha_fin_d:
                fecha_fin_d = fecha

            if titulo:
                promociones.append(Promocion(
                    fuente=self.nombre,
                    categoria=categoria or "Club Movistar",
                    titulo=titulo or "Sin título",
                    descripcion=descripcion or "",
                    comercio=extraer_comercio(titulo, descripcion or ""),
                    precio=precio,
                    tipo=tipo,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin_d,
                    stock=stock,
                    url="https://www.movistar.com.pe/club-movistar",
                    imagen_url=img_url,
                ))

        return promociones


def _texto(tag, selectores: list) -> str:
    for selector in selectores:
        try:
            el = tag.select_one(selector)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        except Exception:
            continue
    return ""
