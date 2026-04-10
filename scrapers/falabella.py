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
    nombre = "FALABELLA"
    url_base = "https://www.bancofalabella.pe/promociones"

    def scrape(self) -> List[Promocion]:
        with sync_playwright() as p:
            # Paso 1: Recopilar todas las tarjetas en una sola sesión
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

            print(f"[{self.nombre}] Recopilando tarjetas...")
            tarjetas = self._recopilar_todas_las_tarjetas(page)
            print(f"[{self.nombre}] {len(tarjetas)} tarjetas recopiladas.")

            context.close()
            browser.close()

            # Paso 2: Procesar detalles en LOTES para evitar memory leaks
            print(f"[{self.nombre}] Extrayendo detalles de cada tarjeta (en lotes)...")
            BATCH_SIZE = 15  # Reiniciar browser cada 15 tarjetas
            sorted_ids = sorted(tarjetas.keys(), key=lambda x: int(x))
            
            for batch_start in range(0, len(sorted_ids), BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, len(sorted_ids))
                batch_ids = sorted_ids[batch_start:batch_end]
                
                print(f"[{self.nombre}] Lote [{batch_start+1}-{batch_end}/{len(sorted_ids)}]...")
                
                # Crear nuevo browser para cada lote
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
                
                # Procesar tarjetas del lote
                for data_id_str in batch_ids:
                    success = False
                    per_card_attempts = 2
                    
                    for attempt in range(per_card_attempts):
                        try:
                            # Si la página está cerrada, cargar nuevamente
                            if page.is_closed():
                                _dbg(f"scrape: página cerrada para {data_id_str}, recargando...")
                                page = context.new_page()
                                self._cargar_inicio(page)
                            
                            self._extraer_detalles_tarjeta(page, data_id_str, tarjetas[data_id_str])
                            success = True
                            break
                        except Exception as e:
                            _dbg(f"scrape: error en {data_id_str} (attempt {attempt+1}/{per_card_attempts}): {e}")
                            time.sleep(0.8)
                    
                    if not success:
                        _dbg(f"scrape: no se pudo procesar {data_id_str}, continuando...")
                
                # Limpiar este lote
                context.close()
                browser.close()
                time.sleep(1)  # Pequeña pausa entre lotes

        # Convertir a Promocion usando datos básicos + detalles extraídos
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
                fecha_inicio=info.get('fecha_inicio', ''),
                fecha_fin=info.get('fecha_fin', ''),
                stock=info.get('stock', ''),
                url=self.url_base,
                imagen_url=info['imagen_url'],
                condiciones=info.get('condiciones', ''),
            ))

        print(f"[{self.nombre}] {len(promociones)} promociones procesadas.")
        return promociones

    def _extraer_detalles_tarjeta(self, page, data_id_str: str, entry: dict) -> None:
        """
        Extrae información de una tarjeta específica.
        
        Flujo:
        1. Scrollear lentamente desde el inicio hasta encontrar el card específico
        2. Hacer click en el card para entrar a su página de detalle
        3. Esperar a que cargue la página de detalle
        4. Extraer información (fechas, stock, condiciones)
        5. Navegar a URL base para volver al listado
        6. Repetir con el siguiente card
        """
        try:
            # Paso 0: Resetear scroll a inicio
            try:
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(0.5)
            except Exception as e:
                _dbg(f"_extraer_detalles: error reseteando scroll para {data_id_str}: {e}")
            
            # Paso 1: Scrollear lentamente hasta encontrar la tarjeta específica
            # (mismo ritmo que en _recopilar_todas_las_tarjetas para permitir carga progresiva)
            max_scroll_attempts = 120
            card = None
            
            for scroll_attempt in range(max_scroll_attempts):
                card = page.query_selector(f'[data-id="{data_id_str}"]')
                if card:
                    _dbg(f"_extraer_detalles: data-id={data_id_str} encontrado en attempt {scroll_attempt}")
                    break
                
                # Scrollear hacia abajo (mismos parámetros que recopilar)
                try:
                    page.evaluate("""
                        window.scrollTo(0, document.documentElement.scrollHeight);
                        var nextDiv = document.getElementById('__next');
                        if(nextDiv) { nextDiv.scrollTop = nextDiv.scrollHeight; }
                    """)
                    time.sleep(0.5)  # IMPORTANTE: esperar tiempo suficiente para cargas
                except Exception:
                    pass
            
            if not card:
                _dbg(f"_extraer_detalles: data-id={data_id_str} NO ENCONTRADO tras {max_scroll_attempts} intentos")
                return
            
            # Paso 2: Hacer visible el card y hacer click
            try:
                page.evaluate(f"""
                    const card = document.querySelector('[data-id="{data_id_str}"]');
                    if (card) {{ card.scrollIntoView({{ behavior: 'smooth', block: 'center' }}); }}
                """)
                time.sleep(1.0)  # Esperar a que se centre en viewport
                
                _dbg(f"_extraer_detalles: haciendo click en data-id={data_id_str}")
                page.locator(f'[data-id="{data_id_str}"]').click(timeout=5000)
                time.sleep(2.0)  # Esperar a que navegue a página de detalle
                
            except Exception as e:
                _dbg(f"_extraer_detalles: error en click/navegación para {data_id_str}: {e}")
                return
            
            # Paso 3: Extraer información de la página de detalle
            try:
                _dbg(f"_extraer_detalles: extrayendo datos de data-id={data_id_str}")
                html_page = page.locator('body').inner_html()
                soup_page = BeautifulSoup(html_page, 'html.parser')
                
                # Extraer comercio desde <h2 class="CardImage_commerce-name__...">
                commerce_h2 = soup_page.select_one('h2[class*="commerce-name"]')
                if commerce_h2:
                    comercio_extraido = commerce_h2.get_text(strip=True)
                    if comercio_extraido:
                        entry['info']['comercio'] = comercio_extraido
                        _dbg(f"_extraer_detalles: comercio encontrado para {data_id_str}: {comercio_extraido}")
                
                # Buscar fechas (mantener lógica existente)
                texto_completo = soup_page.get_text(separator=' ')
                fecha_pattern = r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b'
                fechas = re.findall(fecha_pattern, texto_completo)
                
                if fechas:
                    fechas_validas = [f for f in fechas if len(f) >= 8]
                    if fechas_validas:
                        entry['info']['fecha_inicio'] = fechas_validas[0]
                        entry['info']['fecha_fin'] = fechas_validas[-1] if len(fechas_validas) > 1 else fechas_validas[0]
                        _dbg(f"_extraer_detalles: fechas encontradas para {data_id_str}: {entry['info']['fecha_inicio']} - {entry['info']['fecha_fin']}")
                
                # Buscar stock en el párrafo legal con clase "discounts-detail_legal-text"
                legal_p = soup_page.select_one('p[class*="legal-text"]')
                if legal_p:
                    texto_legal = legal_p.get_text(separator=' ')
                    
                    # Patrones mejorados para extraer stock:
                    # "stock de X unidades", "hasta agotar stock de X", "X unidades", etc.
                    stock_patterns = [
                        r'stock\s+de\s+(\d+(?:[.,]\d{3})*(?:[.,]\d+)?)\s+unidades',
                        r'agotar\s+stock\s+de\s+(\d+(?:[.,]\d{3})*(?:[.,]\d+)?)',
                        r'disponibles:\s+(\d+(?:[.,]\d{3})*(?:[.,]\d+)?)\s+unidades',
                        r'máximo\s+(\d+(?:[.,]\d{3})*(?:[.,]\d+)?)\s+unidades',
                        r'stock\s+sujeto\s+a\s+disponibilidad',  # Indica stock limitado
                    ]
                    
                    stock_encontrado = None
                    for pattern in stock_patterns:
                        match = re.search(pattern, texto_legal, re.IGNORECASE)
                        if match:
                            stock_encontrado = match.group(1) if match.lastindex else "Limitado"
                            break
                    
                    # Si encontramos stock numérico, normalizarlo
                    if stock_encontrado and stock_encontrado != "Limitado":
                        # Reemplazar comas/puntos por separadores si es necesario
                        stock_val = stock_encontrado.replace('.', '').replace(',', '')
                        entry['info']['stock'] = stock_val
                        _dbg(f"_extraer_detalles: stock encontrado para {data_id_str}: {stock_val} unidades")
                    elif "stock sujeto a disponibilidad" in texto_legal.lower():
                        entry['info']['stock'] = "Limitado"
                        _dbg(f"_extraer_detalles: stock limitado detectado para {data_id_str}")
                
            except Exception as e:
                _dbg(f"_extraer_detalles: error extrayendo datos para {data_id_str}: {e}")
            
            # Paso 4: Navegar a URL base para volver al listado
            try:
                _dbg(f"_extraer_detalles: navegando a URL base {self.url_base} para {data_id_str}")
                # Usar wait_until="domcontentloaded" (menos restrictivo que networkidle)
                page.goto(self.url_base, wait_until="domcontentloaded", timeout=60000)
                time.sleep(1.0)
                _dbg(f"_extraer_detalles: regreso a URL base completado para {data_id_str}")
            except Exception as e:
                _dbg(f"_extraer_detalles: error navegando a URL base para {data_id_str}: {e}")
                # Fallback: recargando con wait_until menos estricto
                try:
                    page.goto(self.url_base, wait_until="load", timeout=40000)
                    time.sleep(1.0)
                except Exception as e2:
                    _dbg(f"_extraer_detalles: fallback también falló para {data_id_str}: {e2}")
            
            _dbg(f"_extraer_detalles: completado para data-id={data_id_str}")
            
        except Exception as e:
            _dbg(f"_extraer_detalles: error general en {data_id_str}: {e}")

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
                    
                    # Inicializar campos que serán llenados por _extraer_detalles_tarjeta
                    if 'condiciones' not in info:
                        info['condiciones'] = ''
                    if 'fecha_inicio' not in info:
                        info['fecha_inicio'] = ''
                    if 'fecha_fin' not in info:
                        info['fecha_fin'] = ''
                    if 'stock' not in info:
                        info['stock'] = ''
                    
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

        # Buscar el contenedor top-content específico
        top_content = soup.select_one('[class*="top-content"]')
        
        # Extraer título desde <h2> dentro del top-content
        if top_content:
            title_el = top_content.select_one('h2[class*="title"]')
        else:
            title_el = soup.select_one('h2[class*="title"]')
        
        titulo = (title_el.get_text(strip=True) if title_el
                  else img_el.get("alt", "").strip())
        if not titulo:
            _dbg("_parsear_card_soup: sin título → {}")
            return {}

        # Extraer descripción desde <p> dentro del top-content
        if top_content:
            desc_el = top_content.select_one('p[class*="description"]')
        else:
            desc_el = soup.select_one('p[class*="description"]')
        
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
