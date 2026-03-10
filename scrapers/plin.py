"""
Scraper para Plin
URL: https://plin.pe/promociones/

Plin usa WordPress con paginación HTTP estática (?pg=N) — no hay JS que
renderice el contenido, por lo que requests + BeautifulSoup es suficiente
y mucho más rápido que Playwright.

Estructura de cada tarjeta (.promo-item):
  <div class="promo-item">
    <div class="text">
      <h3>Título <strong>S/Precio o %dto</strong></h3>
      <p>Descripción</p>
      <a class="link" href="...">Ver más</a>
    </div>
    <img ...>
    <div class="category">Categoría</div>   ← a veces
  </div>
"""
import re
import time
import calendar
import requests
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_comercio_de_condiciones
from typing import List, Tuple

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Meses en español para parsing de fechas
_MESES = {
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
    'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
    'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
    'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04',
    'jun': '06', 'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10',
    'nov': '11', 'dic': '12',
}

_TIPO_DESCUENTO = "% Descuento"

_CATEGORIAS_KW = [
    ("Restaurantes",    r'kfc|burger|pizza|pollo|nuggets|tambo|donut|whopper|comida|restaurante|pedidosya|delivery|bembos|menú|menu|gaseosa'),
    ("Combustible",     r'galón|galon|gasolina|repsol|combustible|grifo'),
    ("Movilidad",       r'cabify|uber|taxi|scooter'),
    ("Entretenimiento", r'cine|concierto|entrada|show|evento|teatro'),
    ("Compras",         r'tottus|ripley|tienda|compras|retail|mall|superpet|mascota|pet'),
    ("Salud",           r'botica|farmacia|salud|medicament|clínica|clinica|dental'),
    ("Finanzas",        r'membresía|membresia|sueldo|cuotas|intereses|tarjeta|crédito|débito'),
    ("Viajes",          r'hotel|vuelo|viaje|hospedaje'),
]


class PlinScraper(BaseScraper):
    nombre = "Plin"
    url_base = "https://plin.pe/promociones/"

    def scrape(self) -> List[Promocion]:
        promociones: List[Promocion] = []
        page_num = 1

        while page_num <= 50:
            url = f"{self.url_base}?pg={page_num}"
            print(f"[{self.nombre}] Página {page_num}: {url}")

            soup = self._fetch_soup(url)
            if soup is None:
                break

            items = soup.find_all("div", class_="promo-item")
            if not items:
                print(f"[{self.nombre}] Sin tarjetas en página {page_num}, fin.")
                break

            for item in items:
                promo = self._parsear_item(item)
                if promo:
                    promociones.append(promo)

            print(f"[{self.nombre}]   {len(items)} tarjetas en página {page_num} "
                  f"(total: {len(promociones)})")

            if not self._hay_pagina_siguiente(soup):
                print(f"[{self.nombre}] Última página alcanzada.")
                break

            page_num += 1
            time.sleep(0.8)

        # ── Fase 2: enriquecer con términos y condiciones de cada detalle ────────
        self._fase2_enriquecer(promociones)

        print(f"[{self.nombre}] {len(promociones)} promociones procesadas.")
        return promociones

    def _fase2_enriquecer(self, promociones: List[Promocion]) -> None:
        """Visita la página de detalle de cada promo para obtener condiciones, stock y fechas."""
        total = len(promociones)
        print(f"[{self.nombre}] Fase 2: cargando detalle de {total} promos...")
        for i, promo in enumerate(promociones, 1):
            if promo.url and promo.url != self.url_base:
                self._enriquecer_detalle(promo)
                if i % 10 == 0 or i == total:
                    print(f"[{self.nombre}]   {i}/{total} detalles cargados")
                time.sleep(0.5)

    def _fetch_soup(self, url: str) -> BeautifulSoup | None:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
        except Exception as e:
            print(f"[{self.nombre}] Error de red: {e}")
            return None
        if resp.status_code != 200:
            print(f"[{self.nombre}] HTTP {resp.status_code}, deteniendo.")
            return None
        return BeautifulSoup(resp.content, "lxml")

    @staticmethod
    def _hay_pagina_siguiente(soup: BeautifulSoup) -> bool:
        next_link = soup.find("a", class_=re.compile(r'arrow.+next|next.+arrow'))
        return bool(next_link and next_link.get("href"))

    def _parsear_item(self, item: BeautifulSoup) -> Promocion | None:
        titulo, valor_raw = _extraer_titulo_y_valor(item)
        if not titulo:
            return None

        img_url     = _extraer_img(item)
        descripcion = _extraer_descripcion(item, titulo, valor_raw)
        href        = _extraer_href(item)
        comercio    = titulo   # en Plin, el h3 ES el nombre del comercio (ej: "Tambo")
        categoria   = _extraer_categoria(item, titulo, descripcion)
        precio, tipo = _clasificar_valor(valor_raw, titulo + " " + descripcion)
        fecha_inicio, fecha_fin = _extraer_fechas_item(descripcion, item)
        stock       = _extraer_stock(titulo + " " + descripcion)

        return Promocion(
            fuente=self.nombre,
            categoria=categoria,
            comercio=comercio,
            titulo=titulo,
            descripcion=descripcion,
            precio=precio,
            tipo=tipo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            stock=stock,
            url=href or self.url_base,
            imagen_url=img_url,
            condiciones="",
        )

    def _enriquecer_detalle(self, promo: Promocion) -> None:
        """Visita la página de detalle y extrae condiciones, stock y fechas precisas."""
        soup = self._fetch_soup(promo.url)
        if not soup:
            return

        section = soup.find("section", id="promo-content")
        if not section:
            return

        condiciones = section.get_text(separator=" ", strip=True)
        condiciones = re.sub(
            r'^T[eé]rminos\s+y\s+[Cc]ondiciones\s*:\s*', '', condiciones
        ).strip()
        condiciones = condiciones.replace('\xa0', ' ')   # normalizar espacios HTML
        promo.condiciones = condiciones

        # Imagen en mayor resolución desde el div.image (background-image CSS)
        img_div = soup.find("div", class_=re.compile(r'\bimage\b'))
        if img_div and not promo.imagen_url:
            bg = img_div.get("data-bg-image") or img_div.get("style") or ""
            m_img = re.search(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', bg)
            if m_img:
                promo.imagen_url = m_img.group(1)

        # Stock más preciso que el inferido desde el listado
        stock_det = _extraer_stock_detalle(condiciones)
        if stock_det:
            promo.stock = stock_det

        # Fechas más precisas desde el texto legal completo
        fi, ff = _extraer_fechas_detalle(condiciones)
        if fi or ff:
            promo.fecha_inicio = fi
            promo.fecha_fin = ff

        # Comercio desde el texto legal (más preciso que inferencia por título)
        comercio_det = extraer_comercio_de_condiciones(condiciones)
        if comercio_det:
            promo.comercio = comercio_det


# ── Helpers de parseo de item ────────────────────────────────────────────────

def _extraer_titulo_y_valor(item: BeautifulSoup) -> Tuple[str, str]:
    h3 = item.find("h3")
    if not h3:
        return "", ""
    strong = h3.find("strong")
    valor_raw = ""
    if strong:
        valor_raw = strong.get_text(strip=True)
        strong.extract()
    return h3.get_text(strip=True), valor_raw


def _extraer_img(item: BeautifulSoup) -> str:
    img_el = item.find("img")
    if not img_el:
        return ""
    return img_el.get("src") or img_el.get("data-src") or ""


def _extraer_descripcion(item: BeautifulSoup, titulo: str, valor_raw: str) -> str:
    text_div = item.find("div", class_="text")
    if not text_div:
        return ""
    parrafos = text_div.find_all("p")
    desc = " ".join(p.get_text(strip=True) for p in parrafos if p.get_text(strip=True))
    if desc:
        return desc
    raw = text_div.get_text(separator=" ", strip=True)
    return raw.replace(titulo, "", 1).replace(valor_raw, "", 1).strip()


def _extraer_href(item: BeautifulSoup) -> str:
    link_el = item.find("a", class_="link") or item.find("a")
    return link_el.get("href", "") if link_el else ""


def _extraer_categoria(item: BeautifulSoup, titulo: str, descripcion: str) -> str:
    cat_el = item.find(class_=re.compile(r'categ|tag|type', re.I))
    cat_raw = cat_el.get_text(strip=True) if cat_el else ""
    return cat_raw or _inferir_categoria(titulo + " " + descripcion)


def _extraer_fechas_item(descripcion: str, item: BeautifulSoup) -> Tuple[str, str]:
    fecha_el = item.find(class_=re.compile(r'date|valid|fecha|vigencia', re.I))
    fecha_raw = fecha_el.get_text(strip=True) if fecha_el else ""
    if not fecha_raw:
        fecha_raw = _buscar_fecha_en_texto(descripcion)
    return _extraer_fechas(fecha_raw)


def _extraer_stock_detalle(texto: str) -> str:
    """Extrae stock del texto legal de Términos y Condiciones."""
    # "Stock máximo de 3000 promociones"
    m = re.search(r'stock\s+máximo\s+de\s+([\d,.]+)\s*(\w+)?', texto, re.IGNORECASE)
    if m:
        unidad = (m.group(2) or "unidades").rstrip('.')
        return f"{m.group(1)} {unidad}"

    # "máximo de X cupos/unidades/promociones"
    m = re.search(r'máximo\s+de\s+([\d,.]+)\s+(\w+)', texto, re.IGNORECASE)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    # "X unidades/cupos disponibles"
    m = re.search(r'([\d,.]+)\s+(\w+)\s+disponibles?', texto, re.IGNORECASE)
    if m:
        return f"{m.group(1)} {m.group(2)}"

    if re.search(r'hasta agotar\s+stock', texto, re.IGNORECASE):
        return "Hasta agotar stock"
    if re.search(r'sujeto a\s+(?:stock|disponibilidad)', texto, re.IGNORECASE):
        return "Sujeto a disponibilidad"
    return ""


def _extraer_fechas_detalle(texto: str) -> Tuple[str, str]:
    """Extrae (fecha_inicio, fecha_fin) del texto legal de Términos y Condiciones.

    Patrones soportados (en orden de especificidad):
      1. del DD de MES [de YYYY] al DD de MES [de YYYY]
      2. del DD al DD de MES [de YYYY]          (mismo mes)
      3. válida de DíaSem a DíaSem de MES YYYY  (semanal recurrente → mes completo)
      4. hasta el DD de MES [de YYYY]
      5. Fallback: primer mes+año mencionado    → mes completo
    """
    meses_pat = (
        r'(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre|'
        r'ene|feb|mar|abr|jun|jul|ago|sep|oct|nov|dic)'
    )
    pat_dma = rf'\d{{1,2}}\s+de\s+{meses_pat}\s+(?:del?\s+)?\d{{4}}'
    pat_dm  = rf'\d{{1,2}}\s+de\s+{meses_pat}'

    # 1. del DD de MES [YYYY] al DD de MES [YYYY]
    m = re.search(
        rf'del?\s+({pat_dma}|{pat_dm})\s+al\s+({pat_dma}|{pat_dm})',
        texto, re.IGNORECASE
    )
    if m:
        fi = _norm_fecha(m.group(1))
        ff = _norm_fecha(m.group(2))
        # Propagar el año de ff a fi si fi no lo tiene
        if fi and ff and fi.count('/') == 1 and ff.count('/') == 2:
            fi = fi + '/' + ff.rsplit('/', 1)[1]
        return fi, ff

    # 2. del DD al DD de MES [YYYY]  (rango dentro del mismo mes)
    m = re.search(
        rf'del?\s+(\d{{1,2}})\s+al\s+(\d{{1,2}})\s+de\s+({meses_pat})'
        rf'(?:\s+(?:del?\s+)?(\d{{4}}))?',
        texto, re.IGNORECASE
    )
    if m:
        mes  = _MESES.get(m.group(3).lower(), m.group(3))
        anio = m.group(4) or ""
        suf  = f"/{anio}" if anio else ""
        return f"{m.group(1).zfill(2)}/{mes}{suf}", f"{m.group(2).zfill(2)}/{mes}{suf}"

    # 3. "válida de Lunes a Domingo de Marzo del 2026" → mes completo
    m = re.search(
        rf'válid[ao]\s+de\s+\w+\s+a\s+\w+\s+de\s+({meses_pat})\s+del?\s+(\d{{4}})',
        texto, re.IGNORECASE
    )
    if m:
        mes_num = int(_MESES.get(m.group(1).lower(), "1"))
        anio    = int(m.group(2))
        _, ultimo = calendar.monthrange(anio, mes_num)
        mp = str(mes_num).zfill(2)
        return f"01/{mp}/{anio}", f"{ultimo:02d}/{mp}/{anio}"

    # 4. hasta el DD de MES [YYYY]  o  hasta el DD/MM/YYYY
    m = re.search(
        rf'hasta\s+(?:el\s+)?({pat_dma}|{pat_dm})',
        texto, re.IGNORECASE
    )
    if m:
        return "", _norm_fecha(m.group(1))
    m = re.search(r'hasta\s+(?:el\s+)?(\d{1,2}/\d{1,2}/\d{4})', texto, re.IGNORECASE)
    if m:
        return "", m.group(1)

    # 5. Fallback: primer mes+año → mes completo
    m = re.search(rf'({meses_pat})\s+(?:del?\s+)?(\d{{4}})', texto, re.IGNORECASE)
    if m:
        mes_num = int(_MESES.get(m.group(1).lower(), "1"))
        anio    = int(m.group(2))
        _, ultimo = calendar.monthrange(anio, mes_num)
        mp = str(mes_num).zfill(2)
        return f"01/{mp}/{anio}", f"{ultimo:02d}/{mp}/{anio}"

    return "", ""


# ── Helpers generales ─────────────────────────────────────────────────────────

def _inferir_categoria(texto: str) -> str:
    t = texto.lower()
    for cat, patron in _CATEGORIAS_KW:
        if re.search(patron, t):
            return cat
    return "General"


def _clasificar_valor(valor: str, contexto: str) -> Tuple[str, str]:
    """Infiere (precio_str, tipo_str) del valor extraído del <strong> y el contexto."""
    v = valor.strip()
    ctx = contexto.lower()

    m_pct = re.search(r'(\d+)\s*%', v)
    if m_pct:
        return m_pct.group(1), _TIPO_DESCUENTO

    m_sol = re.search(r'[Ss]/\.?\s*([\d.,]+)', v)
    if m_sol:
        return f"S/ {m_sol.group(1)}", "Precio promo"

    # Buscar en el contexto si el valor solo es un número
    m_num = re.match(r'^(\d+)$', v)
    if m_num and re.search(r'%|desc|dscto|dto', ctx):
        return m_num.group(1), _TIPO_DESCUENTO

    # Buscar precio en el título/descripción cuando valor está vacío
    if not v:
        m_pct2 = re.search(r'(\d{1,3})\s*%', ctx)
        if m_pct2:
            return m_pct2.group(1), _TIPO_DESCUENTO
        m_sol2 = re.search(r'[Ss]/\.?\s*([\d.,]+)', ctx)
        if m_sol2:
            return f"S/ {m_sol2.group(1)}", "Precio promo"

    return v, "Beneficio"


def _buscar_fecha_en_texto(texto: str) -> str:
    """Extrae la primera mención de fecha que encuentre en el texto."""
    m = re.search(
        r'(?:hasta|vigente?|válido?)\s+(?:el\s+)?'
        r'(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}\s+de\s+\w+(?:\s+de\s+\d{4})?)',
        texto, re.IGNORECASE
    )
    return m.group(1) if m else ""


def _extraer_fechas(texto: str) -> Tuple[str, str]:
    """Extrae (fecha_inicio, fecha_fin) de un texto de vigencia."""
    if not texto:
        return "", ""

    meses_pat = (r'(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
                 r'septiembre|octubre|noviembre|diciembre|'
                 r'ene|feb|mar|abr|jun|jul|ago|sep|oct|nov|dic)')

    # dd/mm/yyyy al dd/mm/yyyy
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s+al\s+(\d{1,2}/\d{1,2}/\d{4})',
                  texto, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)

    # del dd de mes [de yyyy] al dd de mes [de yyyy]
    pat_fecha = rf'\d{{1,2}}\s+(?:de\s+)?{meses_pat}(?:\s+(?:de\s+)?\d{{4}})?'
    m = re.search(rf'del?\s+({pat_fecha})\s+al\s+({pat_fecha})', texto, re.IGNORECASE)
    if m:
        return _norm_fecha(m.group(1)), _norm_fecha(m.group(2))

    # hasta el dd/mm/yyyy
    m = re.search(r'hasta\s+(?:el\s+)?(\d{1,2}/\d{1,2}/\d{4})', texto, re.IGNORECASE)
    if m:
        return "", m.group(1)

    # hasta el dd de mes [yyyy]
    m = re.search(rf'hasta\s+(?:el\s+)?({pat_fecha})', texto, re.IGNORECASE)
    if m:
        return "", _norm_fecha(m.group(1))

    # dd/mm/yyyy suelto
    m = re.search(r'\d{1,2}/\d{1,2}/\d{4}', texto)
    if m:
        return "", m.group(0)

    return "", texto   # devolver el texto crudo como fecha_fin si no parseamos


def _norm_fecha(s: str) -> str:
    s = s.strip()
    m = re.match(r'(\d{1,2})\s+(?:de\s+)?(\w+)(?:\s+(?:de\s+)?(\d{4}))?', s, re.IGNORECASE)
    if m:
        dia  = m.group(1).zfill(2)
        mes  = _MESES.get(m.group(2).lower(), m.group(2))
        anio = m.group(3) or ""
        return f"{dia}/{mes}/{anio}" if anio else f"{dia}/{mes}"
    return s


def _extraer_stock(texto: str) -> str:
    t = texto.lower()
    m = re.search(
        r'stock\s*(?:mínimo|minimo|de)?\s*:?\s*(\d[\d,.]*)\s*(?:unidades?|cupos?)?', t
    )
    if m:
        return texto[t.index(m.group(0)): t.index(m.group(0)) + len(m.group(0))].strip()
    if re.search(r'hasta agotar|sujeto a stock|sujeto a disponibilidad', t):
        return "Sujeto a disponibilidad"
    return ""
