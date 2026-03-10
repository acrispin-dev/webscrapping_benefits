"""
Scraper para BBVA Perú — Catálogo de Promociones (PDF)
URL: https://www.bbva.pe/content/dam/public-web/peru/documents/personas/catalogo-promociones/CatalogoDePromocionesLima.pdf

Descarga el PDF y extrae el texto con pdfplumber.
"""
import requests
import pdfplumber
import io
import re
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto, extraer_stock, extraer_fechas, clasificar_precio_tipo, extraer_comercio
from typing import List

PDF_URL = (
    "https://www.bbva.pe/content/dam/public-web/peru/documents/personas/"
    "catalogo-promociones/CatalogoDePromocionesLima.pdf"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
    "Referer": "https://www.bbva.pe/",
}

_RE_DESCUENTO = re.compile(r'\d{1,3}%\s*(?:de\s+)?(?:descuento|dscto\.?|dto\.?)', re.IGNORECASE)
_RE_FECHA = re.compile(
    r'(?:vigencia|válido|hasta|vigente)\s*[:\-]?\s*[\d/\.\-]+(?:\s*[al\-]\s*[\d/\.\-]+)?',
    re.IGNORECASE
)


class BBVAScraper(BaseScraper):
    nombre = "BBVA"
    url_base = "https://www.bbva.pe/personas/beneficios-y-promociones.html"

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Descargando PDF desde {PDF_URL} ...")
        try:
            resp = requests.get(PDF_URL, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            pdf_bytes = io.BytesIO(resp.content)
            promociones = self._parsear_pdf(pdf_bytes)
        except Exception as e:
            print(f"[{self.nombre}] PDF no disponible ({e}). Usando fallback web...")
            promociones = self._scrape_web_fallback()

        print(f"[{self.nombre}] {len(promociones)} promociones encontradas.")
        return promociones

    def _parsear_pdf(self, pdf_bytes: io.BytesIO) -> List[Promocion]:
        promociones: List[Promocion] = []
        try:
            with pdfplumber.open(pdf_bytes) as pdf:
                print(f"[{self.nombre}] PDF con {len(pdf.pages)} páginas.")
                for i, page in enumerate(pdf.pages):
                    texto = page.extract_text() or ""
                    if not texto.strip():
                        continue
                    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
                    promo = self._parsear_bloque(lineas, pagina=i + 1)
                    if promo:
                        promociones.append(promo)
        except Exception as e:
            print(f"[{self.nombre}] Error al parsear PDF: {e}")
        return promociones

    def _parsear_bloque(self, lineas: List[str], pagina: int) -> "Promocion | None":
        if not lineas:
            return None

        titulo = ""
        descripcion_partes = []
        val_descuento = ""
        fecha_raw = ""

        for linea in lineas:
            if not titulo and len(linea) > 3:
                titulo = linea
                continue
            m_desc = _RE_DESCUENTO.search(linea)
            if m_desc and not val_descuento:
                val_descuento = m_desc.group(0)
            m_fecha = _RE_FECHA.search(linea)
            if m_fecha and not fecha_raw:
                fecha_raw = m_fecha.group(0)
            if len(descripcion_partes) < 3:
                descripcion_partes.append(linea)

        descripcion = " ".join(descripcion_partes)
        texto_completo = titulo + " " + descripcion + " " + val_descuento
        precio, tipo = extraer_precio_tipo_de_texto(val_descuento or texto_completo)
        stock = extraer_stock(texto_completo)
        fecha_inicio, fecha_fin = extraer_fechas(fecha_raw)
        if not fecha_fin:
            fecha_fin = fecha_raw

        if titulo and (val_descuento or len(descripcion) > 20):
            return Promocion(
                fuente=self.nombre,
                categoria="General",
                titulo=titulo,
                descripcion=descripcion,
                comercio=extraer_comercio(titulo, descripcion),
                precio=precio,
                tipo=tipo,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                stock=stock,
                url=self.url_base,
                imagen_url="",
                condiciones=f"Página {pagina} del catálogo PDF",
            )
        return None

    def _scrape_web_fallback(self) -> List[Promocion]:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        from bs4 import BeautifulSoup
        import time

        promociones: List[Promocion] = []

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
            print(f"[{self.nombre}] Fallback web: {self.url_base}")
            try:
                page.goto(self.url_base, wait_until="networkidle", timeout=30000)
            except PlaywrightTimeout:
                pass
            for _ in range(4):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(0.8)
            html = page.content()
            context.close()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        tarjetas = []
        for selector in ["[class*='promo']", "[class*='Promo']", "[class*='card']", "article"]:
            candidatos = [t for t in soup.select(selector) if t.get_text(strip=True)]
            if len(candidatos) >= 2:
                tarjetas = candidatos
                break

        if not tarjetas:
            with open("output/debug_bbva.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            return []

        for tarjeta in tarjetas:
            titulo  = _texto(tarjeta, ["h2", "h3", "h4", "[class*='title']"])
            desc    = _texto(tarjeta, ["p", "[class*='desc']", "[class*='text']"])
            val_raw = _texto(tarjeta, ["[class*='discount']", "[class*='offer']", "strong", "b"])
            cat_raw = _texto(tarjeta, ["[class*='categ']", "[class*='tag']"])
            fecha   = _texto(tarjeta, ["[class*='date']", "[class*='valid']", "time"])
            imagen  = tarjeta.select_one("img")
            img_url = imagen.get("src", "") if imagen else ""

            texto_completo = f"{titulo} {desc} {val_raw}"
            precio, tipo = extraer_precio_tipo_de_texto(texto_completo)
            stock = extraer_stock(texto_completo)
            fecha_inicio, fecha_fin = extraer_fechas(fecha)
            if not fecha_fin:
                fecha_fin = fecha

            if titulo:
                promociones.append(Promocion(
                    fuente=self.nombre,
                    categoria=cat_raw or "General",
                    titulo=titulo,
                    descripcion=desc,
                    comercio=extraer_comercio(titulo, desc),
                    precio=precio,
                    tipo=tipo,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    stock=stock,
                    url=self.url_base,
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

PDF_URL = (
    "https://www.bbva.pe/content/dam/public-web/peru/documents/personas/"
    "catalogo-promociones/CatalogoDePromocionesLima.pdf"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
    "Referer": "https://www.bbva.pe/",
}

# Patrones comunes en catálogos PDF peruanos
_RE_DESCUENTO = re.compile(r'\d{1,2}%\s*(?:de\s+)?(?:descuento|dscto\.?|dto\.?)', re.IGNORECASE)
_RE_FECHA = re.compile(
    r'(?:vigencia|válido|hasta|vigente)\s*[:\-]?\s*[\d/\.\-]+(?:\s*[al\-]\s*[\d/\.\-]+)?',
    re.IGNORECASE
)


class BBVAScraper(BaseScraper):
    nombre = "BBVA"
    url_base = PDF_URL

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Descargando PDF desde {self.url_base} ...")
        try:
            resp = requests.get(self.url_base, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"[{self.nombre}] Error al descargar PDF: {e}")
            print(f"[{self.nombre}] Intentando URL alternativa del listado...")
            return self._scrape_web_fallback()

        pdf_bytes = io.BytesIO(resp.content)
        promociones = self._parsear_pdf(pdf_bytes)
        print(f"[{self.nombre}] {len(promociones)} promociones encontradas en PDF.")
        return promociones

    def _parsear_pdf(self, pdf_bytes: io.BytesIO) -> List[Promocion]:
        """Extrae promociones del PDF página por página."""
        promociones: List[Promocion] = []

        try:
            with pdfplumber.open(pdf_bytes) as pdf:
                print(f"[{self.nombre}] PDF con {len(pdf.pages)} páginas.")
                for i, page in enumerate(pdf.pages):
                    texto = page.extract_text() or ""
                    if not texto.strip():
                        continue

                    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
                    promo = self._parsear_bloque(lineas, pagina=i + 1)
                    if promo:
                        promociones.append(promo)

        except Exception as e:
            print(f"[{self.nombre}] Error al parsear PDF: {e}")

        return promociones

    def _parsear_bloque(self, lineas: List[str], pagina: int) -> "Promocion | None":
        """Extrae una Promocion de un bloque de líneas (una página del PDF)."""
        if not lineas:
            return None

        # Primera línea no vacía = título candidato
        titulo = ""
        descripcion_partes = []
        descuento = ""
        fecha = ""
        categoria = ""

        for linea in lineas:
            if not titulo and len(linea) > 3:
                titulo = linea
                continue

            m_desc = _RE_DESCUENTO.search(linea)
            if m_desc and not descuento:
                descuento = m_desc.group(0)

            m_fecha = _RE_FECHA.search(linea)
            if m_fecha and not fecha:
                fecha = m_fecha.group(0)

            # Acumula descripción (máx 3 líneas adicionales)
            if len(descripcion_partes) < 3:
                descripcion_partes.append(linea)

        descripcion = " ".join(descripcion_partes)

        # Solo agregar si encontramos algo útil
        if titulo and (descuento or len(descripcion) > 20):
            return Promocion(
                fuente=self.nombre,
                categoria=categoria or "General",
                titulo=titulo,
                descripcion=descripcion,
                descuento=descuento,
                fecha_fin=fecha,
                url=PDF_URL,
                imagen_url="",
                condiciones=f"Página {pagina} del catálogo PDF",
            )
        return None

    def _scrape_web_fallback(self) -> List[Promocion]:
        """Fallback: si el PDF no descarga, intenta la web de BBVA."""
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        from bs4 import BeautifulSoup
        import time

        url_web = "https://www.bbva.pe/personas/beneficios-y-promociones.html"
        promociones: List[Promocion] = []

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
            print(f"[{self.nombre}] Fallback web: {url_web}")
            try:
                page.goto(url_web, wait_until="networkidle", timeout=30000)
            except PlaywrightTimeout:
                pass

            for _ in range(4):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(0.8)

            html = page.content()
            context.close()
            browser.close()

        soup = BeautifulSoup(html, "lxml")
        selectores = [
            "[class*='promo']", "[class*='Promo']",
            "[class*='card']", "[class*='Card']",
            "article",
        ]
        tarjetas = []
        for selector in selectores:
            candidatos = [t for t in soup.select(selector) if t.get_text(strip=True)]
            if len(candidatos) >= 2:
                tarjetas = candidatos
                break

        if not tarjetas:
            with open("output/debug_bbva.html", "w", encoding="utf-8") as f:
                f.write(str(soup))
            return []

        for tarjeta in tarjetas:
            titulo = _texto(tarjeta, ["h2", "h3", "h4", "[class*='title']", "[class*='name']"])
            descripcion = _texto(tarjeta, ["p", "[class*='desc']", "[class*='text']"])
            descuento = _texto(tarjeta, ["[class*='discount']", "[class*='offer']", "strong", "b"])
            categoria = _texto(tarjeta, ["[class*='categ']", "[class*='tag']"])
            fecha = _texto(tarjeta, ["[class*='date']", "[class*='valid']", "time"])
            imagen = tarjeta.select_one("img")
            img_url = imagen.get("src", "") if imagen else ""
            enlace = tarjeta.select_one("a")
            href = enlace.get("href", "") if enlace else ""
            if href and href.startswith("/"):
                href = "https://www.bbva.pe" + href

            if titulo:
                promociones.append(Promocion(
                    fuente=self.nombre,
                    categoria=categoria or "General",
                    titulo=titulo or "Sin título",
                    descripcion=descripcion,
                    descuento=descuento,
                    fecha_fin=fecha,
                    url=href,
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
