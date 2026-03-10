"""
Scraper para Banco Falabella Perú
URL: https://www.bancofalabella.pe/promociones

Flujo:
1. Carga la página principal y hace scroll para cargar todas las tarjetas.
2. Parsea info básica de cada tarjeta (data-id, título, precio, tipo, categoría).
3. Entra a cada promoción individualmente → extrae texto legal.
4. Del texto legal extrae fechas de vigencia y stock.
5. Regresa al listado y continúa con la siguiente tarjeta.
"""
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_comercio, extraer_comercio_de_condiciones
from typing import List, Dict, Tuple
import re
import time

# Activar para ver logs detallados de cada paso del scraping
DEBUG = True


def _dbg(msg: str) -> None:
    if DEBUG:
        print(f"    [DBG] {msg}")


# ── Mapa de categorías por palabras clave (título + descripción) ─────────────
_CATEGORIAS_KW = [
    ("Restaurantes",    r'kfc|burger|pizza|pollo|nuggets|papa\s+reg|tambo|donut|whopper|cheese\s+jr|croissant|comida|restaurante|pedidosya|delivery|bembos|piqueo|nugget|filete|menú|menu|gaseosa|inca\s+kola|coca\s+cola|ensalada'),
    ("Combustible",     r'galón|galon|gasolina|repsol|combustible|grifo|petróleo'),
    ("Movilidad",       r'cabify|uber|taxi|scooter'),
    ("Entretenimiento", r'inmersive|pimpinela|concierto|entrada|cine|show|evento|teatro|espectáculo|lfc'),
    ("Compras",         r'tottus|ripley|tienda|compras|retail|mall|falabella\.com|saga|superpet|mascota|pet|universal'),
    ("Salud",           r'botica|farmacia|salud|medicament|clínica|clinica|dental'),
    ("Finanzas",        r'membresía|membresia|cmr|sueldo|cuotas\s+sin|intereses|tarjeta|crédito|débito|costo\s+cero|educaci'),
    ("Viajes",          r'hotel|vuelo|viaje|hospedaje|aerolínea'),
]

# Valores del bloque discount que son puramente informativos (no precio real)
_VALS_NO_PRECIO = {"descubre", "más info", "mas info", "ver más", "ver mas"}
_BOTS_NO_PRECIO = {"más info", "mas info", "más aquí", "mas aqui", "ver más", "ver mas"}

# Meses en español para parsing de fechas
_MESES = {
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
    'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
    'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
    'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04',
    'jun': '06', 'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10',
    'nov': '11', 'dic': '12',
}


class FalabellaScraper(BaseScraper):
    nombre = "Banco Falabella"
    url_base = "https://www.bancofalabella.pe/promociones"

    def scrape(self) -> List[Promocion]:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                extra_http_headers={"Accept-Language": "es-PE,es;q=0.9"},
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()
            self._cargar_inicio(page)

            # ── FASE 1: un único scroll continuo por el listado ───────────────
            # Recogemos info básica + href de cada tarjeta mientras pasa por el
            # viewport.  El listado NUNCA navega → el infinite scroll no se
            # interrumpe y no hay límite artificial de ~45 tarjetas.
            print(f"[{self.nombre}] Fase 1: recopilando tarjetas...")
            tarjetas = self._recopilar_todas_las_tarjetas(page)
            print(f"[{self.nombre}] Fase 1 completada: {len(tarjetas)} tarjetas.")

            # ── FASE 2: extraer texto legal abriendo cada detalle en nueva pestaña
            print(f"[{self.nombre}] Fase 2: extrayendo detalles...")
            promociones: List[Promocion] = []
            for data_id_str, entry in sorted(tarjetas.items(), key=lambda x: int(x[0])):
                info      = entry['info']
                href      = entry['href']
                data_id   = int(data_id_str)

                print(f"[{self.nombre}] Detalle data-id={data_id}: {info.get('titulo','?')[:50]}")

                fecha_inicio = ""
                fecha_fin    = info.get('dias', '')
                stock        = ""
                condiciones  = ""
                detail_url   = href or self.url_base
                detail_soup  = None

                if href and '/detalle/' in href:
                    try:
                        detail_pg = context.new_page()
                        try:
                            detail_pg.goto(href, wait_until="domcontentloaded",
                                           timeout=30000)
                            try:
                                detail_pg.wait_for_selector(
                                    '[class*="discounts-detail_legal-text"]',
                                    timeout=10000
                                )
                            except PlaywrightTimeout:
                                _dbg(f"data-id={data_id}: legal-text no apareció")
                            detail_soup = BeautifulSoup(detail_pg.content(), "lxml")
                            legal_el = detail_soup.select_one(
                                '[class*="discounts-detail_legal-text"]'
                            )
                            condiciones = (legal_el.get_text(separator=" ", strip=True)
                                           if legal_el else "")
                            _dbg(f"data-id={data_id}: condiciones[0:120]= "
                                 f"'{condiciones[:120]}'")
                        finally:
                            detail_pg.close()
                    except Exception as e:
                        print(f"[{self.nombre}]   ERROR detalle data-id={data_id}: "
                              f"{type(e).__name__}: {e}")
                else:
                    _dbg(f"data-id={data_id}: sin href, saltando detalle")

                f_ini, f_fin = _extraer_fechas(condiciones)
                _dbg(f"data-id={data_id}: fechas → inicio='{f_ini}' fin='{f_fin}'")
                if f_ini or f_fin:
                    fecha_inicio = f_ini
                    fecha_fin    = f_fin

                if info['tipo'] != "% Descuento":
                    stock = _extraer_stock_legal(condiciones)

                # Refinar comercio: primero desde los elementos del detalle de la página
                comercio = (
                    (_extraer_comercio_detalle_page(detail_soup) if detail_soup else None)
                    or extraer_comercio_de_condiciones(condiciones)
                    or info.get('comercio', '')
                )

                promociones.append(Promocion(
                    fuente=self.nombre,
                    categoria=info['categoria'],
                    comercio=comercio,
                    titulo=info['titulo'],
                    descripcion=info['descripcion'],
                    precio=info['precio'],
                    tipo=info['tipo'],
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    stock=stock,
                    url=detail_url,
                    imagen_url=info['imagen_url'],
                    condiciones=condiciones,
                ))

            context.close()
            browser.close()

        print(f"[{self.nombre}] {len(promociones)} promociones procesadas.")
        return promociones

    def _recopilar_todas_las_tarjetas(self, page) -> dict:
        """
        Scrollea el listado de principio a fin en un ÚNICO pase continuo.

        Para cada card que aparezca en el DOM:
          - Parsea su info básica (título, precio, tipo, etc.)
          - Extrae el href <a> para abrir el detalle después

        Usa scrollBy (relativo) desde posición 0 para no interrumpir el
        infinite scroll. Para cuando el max data-id no sube en STABLE_STEPS
        pasos → el servidor ya no tiene más tarjetas.

        Retorna dict: { 'data_id_str': {'info': {...}, 'href': '...'} }
        """
        STABLE_STEPS = 20   # pasos sin nuevos cards → fin real (~7 s)

        JS_SNAPSHOT = """
            () => {
                const result = {};
                document.querySelectorAll('[data-id]').forEach(el => {
                    const id = el.getAttribute('data-id');
                    if (id === null) return;
                    const a = el.tagName === 'A' ? el
                            : (el.closest('a') || el.querySelector('a'));
                    result[id] = a ? (a.href || '') : '';
                });
                return result;
            }
        """

        tarjetas   = {}   # data_id_str → {'info': {}, 'href': ''}
        prev_max   = -1
        stable     = 0

        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)

        step = 0
        while True:
            # Capturar snapshot de todos los [data-id] visibles ahora
            snapshot = page.evaluate(JS_SNAPSHOT)   # {id_str: href_str}
            for id_str, href in snapshot.items():
                if id_str in tarjetas:
                    # Actualizar href si antes estaba vacío
                    if not tarjetas[id_str]['href'] and href:
                        tarjetas[id_str]['href'] = href
                    continue
                # Card nuevo: parsear su info
                try:
                    card_el  = page.query_selector(f'[data-id="{id_str}"]')
                    card_html = card_el.inner_html() if card_el else ""
                    soup_card = BeautifulSoup(
                        f'<div class="card_root">{card_html}</div>', "lxml"
                    )
                    info = self._parsear_card_soup(soup_card)
                except Exception as e:
                    _dbg(f"recopilar data-id={id_str}: error parseando: {e}")
                    info = {}
                if info:
                    tarjetas[id_str] = {'info': info, 'href': href}
                    _dbg(f"recopilar: guardado data-id={id_str} "
                         f"href={'OK' if href else 'VACIO'} "
                         f"titulo='{info.get('titulo','?')[:40]}'")

            # Calcular max_id y decidir si seguimos
            max_id = max((int(k) for k in tarjetas if k.isdigit()), default=-1)
            if max_id > prev_max:
                _dbg(f"recopilar step#{step}: max_id subió {prev_max}→{max_id} "
                     f"(total={len(tarjetas)})")
                prev_max = max_id
                stable   = 0
            else:
                stable += 1
                _dbg(f"recopilar step#{step}: max_id={max_id} estable "
                     f"({stable}/{STABLE_STEPS}, total={len(tarjetas)})")
                if stable >= STABLE_STEPS:
                    _dbg(f"recopilar: FIN REAL — max_id={max_id}")
                    break

            page.evaluate("window.scrollBy(0, window.innerHeight)")
            time.sleep(0.35)
            step += 1

        return tarjetas


    def _cargar_inicio(self, page) -> None:
        """Navega a la página y espera que aparezcan los primeros cards."""
        print(f"[{self.nombre}] Cargando página...")
        try:
            page.goto(self.url_base, wait_until="networkidle", timeout=45000)
        except PlaywrightTimeout:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=20000)
            except PlaywrightTimeout:
                pass

        try:
            page.wait_for_selector('[class*="BenefitsCard_card"]', timeout=20000)
        except PlaywrightTimeout:
            print(f"[{self.nombre}] WARN: cards no encontrados tras carga inicial.")

        # Cerrar el modal/popup publicitario si aparece
        try:
            close_btn = page.wait_for_selector(
                '[class*="ModalAdvertising_icon-close"]', timeout=5000
            )
            close_btn.click()
            time.sleep(0.4)
        except PlaywrightTimeout:
            pass

    def _parsear_card_soup(self, soup: BeautifulSoup) -> dict:
        """Parsea una sola tarjeta a partir de su BeautifulSoup. Retorna {} si inválida."""
        img_el = soup.select_one('[class*="wrapper-image"] img')
        if not img_el:
            _dbg("_parsear_card_soup: sin imagen → {}")
            return {}
        img_url = img_el.get("src", "")

        title_el = soup.select_one('[class*="title"]')
        titulo = (title_el.get_text(strip=True) if title_el
                  else img_el.get("alt", "").strip())
        if not titulo:
            _dbg("_parsear_card_soup: sin título → {}")
            return {}

        desc_el = soup.select_one('[class*="description"]')
        descripcion = desc_el.get_text(strip=True) if desc_el else ""

        elite_el = soup.select_one('[class*="tag-elite"]')
        if elite_el:
            elite_txt = elite_el.get_text(strip=True)
            if elite_txt:
                descripcion = (f"{descripcion} [{elite_txt}]".strip()
                               if descripcion else f"[{elite_txt}]")

        disc_block = soup.select_one('[class*="discount"]')
        precio, tipo, top_ctx = _extraer_precio_tipo(disc_block)

        if top_ctx and top_ctx.lower() not in ("", "costo"):
            descripcion = (f"{descripcion} ({top_ctx})".strip()
                           if descripcion else top_ctx)

        time_el = soup.select_one('[class*="time"]')
        if time_el:
            for badge in time_el.select('[class*="badge"], [class*="new-badge"]'):
                badge.decompose()
        dias = time_el.get_text(strip=True) if time_el else ""

        categoria = _inferir_categoria(titulo + " " + descripcion)

        return {
            'titulo': titulo,
            'descripcion': descripcion,
            'precio': precio,
            'tipo': tipo,
            'imagen_url': img_url,
            'categoria': categoria,
            'comercio': extraer_comercio(titulo, descripcion),
            'dias': dias,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _inferir_categoria(texto: str) -> str:
    """Infiere la categoría a partir de palabras clave en título + descripción."""
    texto_l = texto.lower()
    for cat, patron in _CATEGORIAS_KW:
        if re.search(patron, texto_l):
            return cat
    return "General"


def _extraer_precio_tipo(disc_block) -> Tuple[str, str, str]:
    """Dado el bloque discount de Falabella devuelve (precio, tipo, top_texto)."""
    if not disc_block:
        return "", "Beneficio", ""

    val_el = disc_block.select_one('[class*="text-uppercase"]')
    bot_el = disc_block.select_one('[class*="text-bottom"]')
    top_el = disc_block.select_one('[class*="text-top"]')

    val = val_el.get_text(strip=True) if val_el else ""
    bot = bot_el.get_text(strip=True) if bot_el else ""
    top = top_el.get_text(strip=True) if top_el else ""

    precio, tipo = clasificar_valor(val, bot, top)
    return precio, tipo, top


def clasificar_valor(val: str, etiqueta: str, top: str = "") -> Tuple[str, str]:
    """
    Clasifica el bloque de descuento de la tarjeta Falabella.
    Retorna (precio_str, tipo_str):
      "% Descuento"  → precio = número entero (ej. "30")
      "Precio promo" → precio = "S/ X.XX"
      "Beneficio"    → precio = ""
    """
    val = val.strip()
    etiqueta_lower = etiqueta.lower()

    if val.lower() in _VALS_NO_PRECIO or etiqueta_lower in _BOTS_NO_PRECIO or not val:
        return "", "Beneficio"

    m_pct = re.search(r'(\d+)\s*%', val)
    if m_pct:
        return m_pct.group(1), "% Descuento"

    m_sol = re.search(r'[Ss]/\s*([\d.,]+)', val)
    if m_sol:
        return f"S/ {m_sol.group(1)}", "Precio promo"

    if re.search(r'desc|dscto|dto\.?', etiqueta_lower):
        return val, "% Descuento"

    if re.search(r'precio|superprecio|s[uú]per', etiqueta_lower):
        return val, "Precio promo"

    if "sin tope" in etiqueta_lower:
        return val, "% Descuento"

    if "ahorra" in top.lower() and val:
        return val, "Precio promo"

    return val, "Beneficio"


def _extraer_fechas(texto: str) -> Tuple[str, str]:
    """
    Extrae (fecha_inicio, fecha_fin) del texto legal de Falabella.

    Patrones soportados:
      "del 01/03/2026 al 31/03/2026"
      "del 15 de agosto [de 2026] al 31 de diciembre [de 2026]"
      "hasta el 31/03/2026"
      "hasta el 31 de diciembre [de 2026]"
    """
    meses = (r'(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
             r'septiembre|octubre|noviembre|diciembre|'
             r'ene|feb|mar|abr|jun|jul|ago|sep|oct|nov|dic)')
    pat_esfecha = rf'\d{{1,2}}\s+(?:de\s+)?{meses}(?:\s+(?:de\s+)?\d{{4}})?'

    # dd/mm/yyyy al dd/mm/yyyy
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s+al\s+(\d{1,2}/\d{1,2}/\d{4})',
                  texto, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)

    # del dd de mes [de yyyy] al dd de mes [de yyyy]
    m = re.search(
        rf'(?:del?\s+)({pat_esfecha})\s+al\s+({pat_esfecha})',
        texto, re.IGNORECASE
    )
    if m:
        return _norm_fecha_es(m.group(1)), _norm_fecha_es(m.group(2))

    # hasta el dd/mm/yyyy
    m = re.search(r'hasta\s+(?:el\s+|la\s+)?(\d{1,2}/\d{1,2}/\d{4})',
                  texto, re.IGNORECASE)
    if m:
        return "", m.group(1)

    # hasta el dd de mes [de yyyy]
    m = re.search(rf'hasta\s+(?:el\s+|la\s+)?({pat_esfecha})',
                  texto, re.IGNORECASE)
    if m:
        return "", _norm_fecha_es(m.group(1))

    return "", ""


def _norm_fecha_es(fecha_str: str) -> str:
    """Normaliza '15 de agosto de 2026' → '15/08/2026' o '15 agosto' → '15/08'."""
    s = fecha_str.strip()
    m = re.match(r'(\d{1,2})\s+(?:de\s+)?(\w+)(?:\s+(?:de\s+)?(\d{4}))?',
                 s, re.IGNORECASE)
    if m:
        dia = m.group(1).zfill(2)
        mes_n = m.group(2).lower()
        anio = m.group(3) or ""
        mes_num = _MESES.get(mes_n, mes_n)
        return f"{dia}/{mes_num}/{anio}" if anio else f"{dia}/{mes_num}"
    return s


def _extraer_stock_legal(texto: str) -> str:
    """
    Extrae información de stock del texto legal de una promoción de precio/beneficio.

    - "Stock mínimo 1000 unidades"      → "Stock mínimo 1000 unidades"
    - "Sujeto a disponibilidad de stock" (sin número) → "Sujeto a disponibilidad"
    - Sin mención de stock              → ""
    """
    t = texto.lower()

    # Stock con número explícito: "stock mínimo 500 unidades", "stock: 1000"
    m = re.search(
        r'stock\s+(?:mínimo|minimo|máximo|maximo|de\s+|disponible\s+)?'
        r':?\s*(\d[\d,.]*)\s*(?:unidades?|und\.?|piezas?|cupos?|productos?)?',
        t
    )
    if m:
        start = t.index(m.group(0))
        return texto[start: start + len(m.group(0))].strip()

    # Número de unidades en el texto aunque no diga "stock" antes
    m = re.search(r'(\d[\d,.]+)\s+(?:unidades?|cupos?)', t)
    if m:
        start = t.index(m.group(0))
        return texto[start: start + len(m.group(0))].strip()

    # Mención de stock sin número → sujeto a disponibilidad
    if re.search(
        r'sujeto\s+a\s+disponibilidad.*?stock|'
        r'hasta\s+agotar\s+(?:el\s+)?stock|'
        r'sujeto\s+a\s+stock',
        t
    ):
        return "Sujeto a disponibilidad"

    return ""


def _extraer_comercio_detalle_page(detail_soup: BeautifulSoup) -> str:
    """
    Extrae el nombre del comercio desde la página de detalle de Falabella usando:
      1. CardInfo_title → <h1><b>Disfruta de tu promoción en Burger King</b></h1>
      2. DetailBanner_wrapper-content → <li><p>Acércate a tu local de Burger King...</p></li>

    Estrategia:
      a) Busca marcas conocidas (_COMERCIOS_KW) en el texto combinado.
      b) Regex: "en NombreComercio" al final del título de la card.
      c) Regex: "tu local de NombreComercio" en los ítems del banner.
    """
    texts: list = []

    title_el = detail_soup.select_one('[class*="CardInfo_title"]')
    if title_el:
        texts.append(title_el.get_text(strip=True))

    banner_el = detail_soup.select_one('[class*="DetailBanner_wrapper-content"]')
    if banner_el:
        for p_el in banner_el.select('li p')[:6]:
            t = p_el.get_text(strip=True)
            if t:
                texts.append(t)

    if not texts:
        return ""

    combined = " ".join(texts)

    # Intento 1: marcas conocidas (captura KFC, Burger King, etc.)
    kw = extraer_comercio(combined)
    if kw:
        return kw

    # Intento 2: "en NombreComercio" al final el título de la card
    # e.g. "Disfruta de tu promoción en Burguer King"
    if texts:
        m = re.search(
            r'\ben\s+'
            r'((?:[A-Z\u00C0-\u00DC][A-Za-z\u00C0-\u00FF&\'\-\w]+)'
            r'(?:\s+[A-Z\u00C0-\u00DC&][\w\'\-]+){0,4})'
            r'\s*$',
            texts[0]
        )
        if m:
            return m.group(1).strip()

    # Intento 3: "tu local de NombreComercio" en los ítems del banner
    for text in texts[1:]:
        m = re.search(
            r'\btu\s+local\s+de\s+'
            r'((?:[A-Z\u00C0-\u00DC][A-Za-z\u00C0-\u00FF&\'\-\w]+)'
            r'(?:\s+[A-Z\u00C0-\u00DC&][\w\'\-]+){0,4})',
            text
        )
        if m:
            name = m.group(1).strip()
            name = re.sub(
                r'\s+(?:favorito|cercano|participante)[\w\s]*$', '',
                name, flags=re.IGNORECASE
            ).strip()
            if name:
                return name

    return ""
