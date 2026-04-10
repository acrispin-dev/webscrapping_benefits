"""
Scraper para Movistar PerÃº â€” Club Movistar
URL: https://www.movistar.com.pe/club-movistar
"""
import requests
import re
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto, extraer_stock, extraer_fechas, extraer_comercio
from typing import List

class MovistarScraper(BaseScraper):
    nombre = "MOVISTAR"
    url_base = "https://www.movistar.com.pe/club-movistar"

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Cargando {self.url_base} de forma estática...")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        }
        
        try:
            resp = requests.get(self.url_base, headers=headers, timeout=30)
            resp.raise_for_status()
            resp.encoding = 'utf-8'  # Asegurar decodificación correcta
            html = resp.text
        except Exception as e:
            print(f"[{self.nombre}] Error cargando HTML: {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
        promociones = self._parsear(soup)
        print(f"[{self.nombre}] {len(promociones)} promociones encontradas.")
        return promociones

    def _parsear(self, soup: BeautifulSoup) -> List[Promocion]:
        promociones: List[Promocion] = []

        # En la version actual de la pagina de Movistar, las tarjetas se encuentran en
        # contenedores con la clase "stefa-tabs-club-movistar__card"
        tarjetas = soup.select('.stefa-tabs-club-movistar__card')
        
        if not tarjetas:
            print(f"[{self.nombre}] No se encontraron tarjetas con el selector especializado, usando fallback...")
            return self._parsear_fallback(soup)

        for tarjeta in tarjetas:
            comercio_el = tarjeta.select_one('.stefa-tabs-club-movistar__card--body__title, h2, h3, [class*="title"]')
            titulo_el = tarjeta.select_one('.stefa-tabs-club-movistar__card--body__text, p:not(.stefa-tabs-club-movistar__card--body__title)')
            badge_el = tarjeta.select_one('.stefa-tabs-club-movistar__card--header__bagde, [class*="discount"]')
            img_el = tarjeta.select_one('img')
            
            comercio = re.sub(r'\s+', ' ', comercio_el.get_text(separator=' ', strip=True)) if comercio_el else ""
            descripcion = re.sub(r'\s+', ' ', titulo_el.get_text(separator=' ', strip=True)) if titulo_el else ""
            descuento = re.sub(r'\s+', ' ', badge_el.get_text(separator=' ', strip=True)) if badge_el else ""
            
            # En Movistar el texto descriptivo funciona mucho mejor como título de la promo:
            titulo = descripcion if descripcion else comercio
            
            img_url = img_el.get('src') or img_el.get('data-src') or "" if img_el else ""
            if img_url and img_url.startswith("//"):
                img_url = "https:" + img_url
                
            texto_completo = f"{titulo} {comercio} {descuento}"
            precio, tipo = extraer_precio_tipo_de_texto(texto_completo)
                
            # Movistar no publica fechas ni stock en su web publica
            fecha_inicio = ""
            fecha_fin_d = ""
            stock = "Stock no disponible"
            
            if comercio or titulo:
                promociones.append(Promocion(
                    fuente=self.nombre,
                    categoria="Club Movistar",
                    titulo=titulo,
                    descripcion=descripcion,
                    comercio=comercio if comercio else extraer_comercio(titulo, descripcion),
                    precio=precio,
                    tipo=tipo,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin_d,
                    stock=stock,
                    url=self.url_base,
                    imagen_url=img_url,
                ))

        return promociones

    def _parsear_fallback(self, soup: BeautifulSoup) -> List[Promocion]:
        promociones: List[Promocion] = []
        selectores = [
            "[class*='benefit']",
            "[class*='club']",
            "[class*='promo']",
            "[class*='card']",
            "article"
        ]

        tarjetas = []
        for selector in selectores:
            candidatos = soup.select(selector)
            candidatos = [t for t in candidatos if t.get_text(strip=True)]
            if len(candidatos) >= 2:
                tarjetas = candidatos
                break

        for tarjeta in tarjetas:
            comercio = re.sub(r'\s+', ' ', self._texto(tarjeta, ["h2", "h3", "h4", "[class*='title']", "[class*='name']"]))
            descripcion = re.sub(r'\s+', ' ', self._texto(tarjeta, ["[class*='text']", "[class*='desc']", "p:not([class*='title'])", "p"]))
            descuento = re.sub(r'\s+', ' ', self._texto(tarjeta, ["[class*='discount']", "[class*='benefit']", "strong", "b"]))
            categoria = re.sub(r'\s+', ' ', self._texto(tarjeta, ["[class*='categ']", "[class*='tag']", "[class*='type']"]))
            fecha = re.sub(r'\s+', ' ', self._texto(tarjeta, ["[class*='date']", "[class*='valid']", "[class*='vigencia']", "time"]))
            imagen = tarjeta.select_one("img")
            img_url = imagen.get("src", "") or imagen.get("data-src", "") if imagen else ""
            if img_url and img_url.startswith("//"):
                img_url = "https:" + img_url
            enlace = tarjeta.select_one("a")
            href = enlace.get("href", "") if enlace else ""
            if href and href.startswith("/"):
                href = "https://www.movistar.com.pe" + href

            titulo = descripcion if descripcion else comercio

            texto_completo = f"{titulo} {comercio} {descuento}"
            precio, tipo = extraer_precio_tipo_de_texto(texto_completo)
            
            # Movistar no publica fechas ni stock en su web publica
            fecha_inicio = ""
            fecha_fin_d = ""
            stock = "Stock no disponible"

            if comercio or titulo:
                promociones.append(Promocion(
                    fuente=self.nombre,
                    categoria=categoria or "Club Movistar",
                    titulo=titulo or "Sin título",
                    descripcion=descripcion or "",
                    comercio=comercio if comercio else extraer_comercio(titulo, descripcion),
                    precio=precio,
                    tipo=tipo,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin_d or fecha,
                    stock=stock,
                    url=self.url_base,
                    imagen_url=img_url,
                ))

        return promociones

    def _texto(self, tag, selectores: list) -> str:
        for selector in selectores:
            try:
                el = tag.select_one(selector)
                if el and el.get_text(strip=True):
                    return el.get_text(strip=True)
            except Exception:
                continue
        return ""