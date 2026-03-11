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
from scrapers.utils import extraer_comercio
from typing import List, Tuple
import csv
import os
import re
import time
import difflib

# Activar para ver logs detallados de cada paso del scraping
DEBUG = True

# ── Merchants desde comercios.csv para matching de logo-slug ─────────────────
def _load_merchants() -> List[str]:
    csv_path = os.path.join(os.path.dirname(__file__), 'comercios.csv')
    try:
        # Usar utf-8-sig para ignorar transparentemente el BOM (\xef\xbb\xbf)
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            return [r['companycd'].strip() for r in csv.DictReader(f)
                    if r.get('companycd', '').strip()]
    except Exception as e:
        print(f"Error cargando comercios: {e}")
        return []

_MERCHANTS: List[str] = _load_merchants()
# Precalcular versión normalizada (solo letras minúsculas) para matching rápido
_MERCHANTS_NORM: List[Tuple[str, str]] = [
    (re.sub(r'[^a-z]', '', m.lower()), m) for m in _MERCHANTS
]


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

            # Único pase de scroll: captura las 151 tarjetas sin abrir pestañas extra.
            print(f"[{self.nombre}] Recopilando tarjetas...")
            tarjetas = self._recopilar_todas_las_tarjetas(page)
            print(f"[{self.nombre}] {len(tarjetas)} tarjetas recopiladas.")

            context.close()
            browser.close()

        # Convertir a Promocion usando solo los datos de la card (sin visitar detalles)
        promociones: List[Promocion] = []
        for data_id_str, entry in sorted(tarjetas.items(), key=lambda x: int(x[0])):
            info = entry['info']

            # Comercio: logo slug → CSV  o fallback
            logo_slug = info.get('logo_slug', '')
            comercio = _comercio_desde_logo_slug(logo_slug)
            
            if not comercio:
                comercio = info.get('comercio', '') # utils.extraer_comercio fallback
                
            if not comercio and logo_slug:
                # Fallback como en el script de ejemplo
                comercio = logo_slug.replace('_', ' ').replace('-', ' ').title()
                
            if not comercio:
                comercio_final = "Falabella"
            else:
                comercio_final = _normalizar_comercio_final(comercio)

            promociones.append(Promocion(
                fuente=self.nombre,
                categoria=info['categoria'],
                comercio=comercio_final,
                titulo=info['titulo'],
                descripcion=info['descripcion'],
                precio=info['precio'],
                tipo=info['tipo'],
                fecha_inicio="",
                fecha_fin=info.get('dias', ''),
                stock="",
                url=self.url_base,
                imagen_url=info['imagen_url'],
                condiciones="",
            ))

        print(f"[{self.nombre}] {len(promociones)} promociones procesadas.")
        return promociones

    def _get_total_esperado(self, page) -> int:
        """Lee la cantidad total de promos del encabezado de la página (ej. 'Todos (151)')."""
        try:
            el = page.query_selector('[class*="SectionTitle_heading"] small')
            if el:
                m = re.search(r'\d+', el.inner_text())
                if m:
                    return int(m.group(0))
        except Exception:
            pass
        return 0

    def _recopilar_todas_las_tarjetas(self, page) -> dict:
        """
        Scrollea el listado de principio a fin en un ÚNICO pase continuo.

        Para cada card que aparezca en el DOM:
          - Parsea su info básica (título, precio, tipo, etc.)
          - Construye el href usando el logo_slug si no se encuentra <a>

        Se detiene cuando alcanza el total esperado (leído del encabezado)
        O bien cuando el max data-id no sube en STABLE_STEPS pasos.

        Retorna dict: { 'data_id_str': {'info': {...}, 'href': '...'} }
        """
        STABLE_STEPS = 40   # pasos sin nuevos cards → fin real (~14 s)

        # Las cards de Falabella son <div data-id=...> sin <a> hijos;
        # el JS_SNAPSHOT intenta capturar href de <a> como fallback por si
        # en el futuro la web vuelve a usar anclas.
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

        total_esperado = self._get_total_esperado(page)
        if total_esperado:
            print(f"[{self.nombre}] Total esperado desde la página: {total_esperado}")
        else:
            print(f"[{self.nombre}] WARN: no se pudo leer el total esperado; usando STABLE_STEPS={STABLE_STEPS}")

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
                    # Actualizar href si antes estaba vacío (ej. <a> apareció tarde)
                    if not tarjetas[id_str]['href'] and href:
                        tarjetas[id_str]['href'] = href
                    continue
                # Card nuevo: parsear su info
                try:
                    card_el   = page.query_selector(f'[data-id="{id_str}"]')
                    card_html = card_el.inner_html() if card_el else ""
                    soup_card = BeautifulSoup(
                        f'<div class="card_root">{card_html}</div>', "lxml"
                    )
                    info = self._parsear_card_soup(soup_card)
                except Exception as e:
                    _dbg(f"recopilar data-id={id_str}: error parseando: {e}")
                    info = {}
                if info:
                    # Si el JS no encontró <a> (caso habitual en Falabella),
                    # construir la URL de detalle desde el logo_slug.
                    if not href and info.get('logo_slug'):
                        href = f"{self.url_base}/{info['logo_slug']}"
                    tarjetas[id_str] = {'info': info, 'href': href}
                    _dbg(f"recopilar: guardado data-id={id_str} "
                         f"href={'OK' if href else 'VACIO'} "
                         f"titulo='{info.get('titulo','?')[:40]}'")

            # ── Condición de parada: total alcanzado ─────────────────────────
            if total_esperado and len(tarjetas) >= total_esperado:
                _dbg(f"recopilar: FIN — alcanzado total esperado ({len(tarjetas)}/{total_esperado})")
                break

            # Validar si creció la cantidad de tarjetas recopiladas
            current_count = len(tarjetas)
            if current_count > prev_max:
                _dbg(f"recopilar step#{step}: tarjetas subió {prev_max}→{current_count}")
                prev_max = current_count
                stable   = 0
            else:
                stable += 1
                _dbg(f"recopilar step#{step}: conteo={current_count} estable "
                     f"({stable}/{STABLE_STEPS})")
                if stable >= STABLE_STEPS:
                    _dbg(f"recopilar: FIN REAL — conteo final={current_count}")
                    break

            page.evaluate("""
                window.scrollTo(0, document.documentElement.scrollHeight);
                var nextDiv = document.getElementById('__next');
                if(nextDiv) { nextDiv.scrollTop = nextDiv.scrollHeight; }
            """)
            time.sleep(0.5)
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

        # Logica del script de ejemplo para la extracción del comercio (título/logo)
        logo_el = soup.find('img', class_=lambda c: c and ('NewCardBenefits_logo' in c or 'partner-logo' in c))
        img_url = ""
        logo_slug = ""
        alt_text = ""
        if logo_el:
            img_url = logo_el.get('srcset', '') or logo_el.get('src', '')
            alt_text = logo_el.get('alt', '')
            
            # regex mejorada desde el script de ejemplo (soporta logo_ o card_logo_)
            m_slug = re.search(r'(?:card_)?logo_([^\.]+)', img_url)
            if m_slug:
                raw_name = m_slug.group(1)
                if '?' in raw_name:
                    raw_name = raw_name.split('?')[0]
                logo_slug = raw_name
            else:
                if alt_text.startswith('logo-'):
                    logo_slug = alt_text.replace('logo-', '').strip()
                elif len(alt_text) < 50:
                    logo_slug = alt_text.strip()
                    
        if logo_slug:
            _dbg(f"_parsear_card_soup: logo_slug='{logo_slug}'")

        categoria = _inferir_categoria(titulo + " " + descripcion)

        return {
            'titulo': titulo,
            'descripcion': descripcion,
            'precio': precio,
            'tipo': tipo,
            'imagen_url': img_url,
            'categoria': categoria,
            'comercio': extraer_comercio(titulo, descripcion),
            'logo_slug': logo_slug,
            'dias': dias,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalizar_comercio_final(nombre_crudo: str) -> str:
    """Intenta emparejar el nombre extraído con la lista maestra en CSV usando similitud."""
    if not nombre_crudo or not _MERCHANTS:
        return nombre_crudo

    crudo_clean = nombre_crudo.strip()
    crudo_lower = crudo_clean.lower()
    
    # 1. Match exacto case-insensitive
    for m in _MERCHANTS:
        if m.lower() == crudo_lower:
            return m
            
    # 2. Match parcial fuerte: si el nombre del comercio (del CSV) está contenido en el crudo
    # Ej: "kfc_familiar" -> "KFC", "burger_king_promo" -> "Burger King"
    # Ordenamos por longitud de mayor a menor para buscar primero los nombres más específicos
    for m in sorted(_MERCHANTS, key=len, reverse=True):
        m_lower = m.lower()
        if len(m_lower) >= 3 and m_lower in crudo_lower:
            return m
            
    # 3. Match parcial inverso: si la palabra cruda está contenida en el comercio (CSV)
    # Ej: "bembos" in "Bembos Peru"
    for m in _MERCHANTS:
        m_lower = m.lower()
        if len(crudo_lower) >= 4 and crudo_lower in m_lower:
            return m
            
    # 4. Búsqueda de similitud estricta con difflib (para typos: "Burguer King" -> "Burger King")
    nombres_csv_lower = {m.lower(): m for m in _MERCHANTS}
    matches = difflib.get_close_matches(crudo_lower, list(nombres_csv_lower.keys()), n=1, cutoff=0.7)
    
    if matches:
        return nombres_csv_lower[matches[0]]

    # Si todo falla, normalizamos estéticamente la salida reemplazando _ o - por espacios
    crudo_clean = crudo_clean.replace('_', ' ').replace('-', ' ').title()
    return crudo_clean

def _comercio_desde_logo_slug(slug: str) -> str:
    """
    Dado un slug extraído del src del logo (ej. 'repsoldto3'), lo normaliza
    (sólo letras, sin dígitos al final) y busca el mejor match en _MERCHANTS.

    Estrategia: el slug suele comenzar con el nombre del comercio seguido de
    una abreviatura de la oferta (ej. 'dto3', '25off', etc.).
    Retorna el nombre canónico del CSV o '' si no hay coincidencia suficiente.
    """
    if not slug or not _MERCHANTS_NORM:
        return ""

    # Normalizar slug: minúsculas, quitar dígitos del final, solo letras
    slug_norm = re.sub(r'\d+$', '', slug.lower())
    slug_norm = re.sub(r'[^a-z]', '', slug_norm)

    if len(slug_norm) < 3:
        return ""

    best_name  = ""
    best_score = 0
    for m_norm, m_name in _MERCHANTS_NORM:
        if not m_norm or len(m_norm) < 3:
            continue
        # El slug empieza con el nombre del comercio O coincide exactamente
        if slug_norm.startswith(m_norm) or m_norm == slug_norm:
            score = len(m_norm)
            if score > best_score:
                best_score = score
                best_name  = m_name

    return best_name if best_score >= 3 else ""


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
