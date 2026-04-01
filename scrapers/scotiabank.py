"""
Scraper para Scotiabank Perú - Promociones PLIN
URL: https://www.scotiabank.com.pe/Personas/Canales-digitales/pagos/transferencias-interbancarias-plin

Las promos se presentan como imágenes; el nombre del comercio se extrae del filename.
Los términos y condiciones están en texto en la misma página, de donde se obtienen
precio, tipo, stock y fechas de vigencia.
No requiere Playwright — la página es HTML estático.
"""
import re
import requests
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto, extraer_stock, extraer_fechas
from typing import List, Dict, Tuple


_URL = ("https://www.scotiabank.com.pe/Personas/Canales-digitales"
        "/pagos/transferencias-interbancarias-plin")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Slug del filename → nombre de display canónico
_SLUG_NOMBRE: Dict[str, str] = {
    'beso-frances':         'Beso Francés',
    'burguer-king':         'Burger King',
    'chilis':               "Chili's",
    'cinnabon':             'Cinnabon',
    'fridays':              "Friday's",
    'isushi':               'iSushi',
    'kfc':                  'KFC',
    'little-caesars-pizza': 'Little Caesars Pizza',
    'madam-tusan':          'Madam Tusan',
    'norkys':               "Norky's",
    'papa-johns':           "Papa John's",
    'pikalo':               'Pikalo',
    'pinkberry':            'Pinkberry',
    'pizza-hut':            'Pizza Hut',
    'subway':               'Subway',
    'amphora':              'Ámphora',
    'bata':                 'Bata',
    'oxxo':                 'OXXO',
    'repshop':              'RepShop',
    'repsol':               'Repsol',
    'tambo':                'Tambo',
    'bembos':               'Bembos',
    'montalvo':             'Montalvo',
}

# Alias de slugs con typos en el filename → slug canónico
_SLUG_ALIAS: Dict[str, str] = {
    'isushu': 'isushi',   # typo en filename de Scotiabank
}

# Categoría por defecto para merchants sin imagen activa (HTML comentado)
_SLUG_CATEGORIA_DEFAULT: Dict[str, str] = {
    'bembos':   'Restaurantes',
    'montalvo': 'Salud',
}

# Container ID → categoría
_CAT_POR_ID: Dict[str, str] = {
    'restaurante-content':      'Restaurantes',
    'establecimientos-content': 'Compras',
    'entretenimiento-content':  'Entretenimiento',
    'belleza-content':          'Salud',
    'oportunidades-content':    'Otros',
}

# Meses en español para parsing de fechas en texto
_MESES: Dict[str, str] = {
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
    'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
    'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
}


class ScotiabankScraper(BaseScraper):
    nombre = "Scotiabank"
    url_base = _URL

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Descargando página PLIN...")
        try:
            resp = requests.get(_URL, headers=_HEADERS, timeout=25)
            resp.raise_for_status()
        except Exception as exc:
            print(f"[{self.nombre}] ERROR: {exc}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        imgs_por_slug = _recopilar_imagenes(soup)
        tyc_dict     = _parsear_tyc(soup)
        promociones  = _construir_promociones(imgs_por_slug, tyc_dict,
                                               self.nombre, _URL)
        print(f"[{self.nombre}] {len(promociones)} promociones encontradas.")
        return promociones


# ── Recopilación de imágenes ──────────────────────────────────────────────────

def _recopilar_imagenes(soup: BeautifulSoup) -> Dict[str, List[dict]]:
    """
    Recorre todos los containers [id$="-content"] dentro de section.promos-slider
    y devuelve {slug: [{'img_url': ..., 'categoria': ...}, ...]}.
    """
    result: Dict[str, List[dict]] = {}
    for cont in soup.select('[id$="-content"]'):
        cat_id    = cont.get('id', '')
        categoria = _CAT_POR_ID.get(cat_id, 'General')
        for img in cont.find_all('img', src=re.compile(r'promociones-plin', re.I)):
            src  = img.get('src', '')
            slug = _slug_desde_src(src)
            if not slug:
                continue
            result.setdefault(slug, []).append({'img_url': src, 'categoria': categoria})
    return result


def _slug_desde_src(src: str) -> str:
    """Extrae el slug canónico del comercio del filename: card-{mes}-{slug}-{num}[-v{n}].ext"""
    fname = src.split('/')[-1]
    m = re.match(r'card-\w+?-(.+?)-\d+(?:-v\d+)?\.(?:jpg|png|webp)', fname, re.I)
    raw = m.group(1) if m else ""
    return _SLUG_ALIAS.get(raw, raw)   # normaliza typos de filename


def _slug_a_nombre(slug: str) -> str:
    return _SLUG_NOMBRE.get(slug, slug.replace('-', ' ').title())


# ── Parsing de Términos y Condiciones ─────────────────────────────────────────

def _parsear_tyc(soup: BeautifulSoup) -> Dict[str, List[str]]:
    """
    Parsea el bloque div.legal → {comercio_normalizado: [condicionesText, ...]}.
    Extrae el COMERCIO desde: <button class="desplegable tag-element--surplus"><b>Chillis</b></button>
    Luego asocia cada comercio con sus T&C.
    """
    tyc: Dict[str, List[str]] = {}
    legal = soup.select_one('div.legal')
    if not legal:
        return tyc

    contenedor = legal.select_one('div.mt-3')
    if not contenedor:
        return tyc

    # Paso 1: Extraer nombres de comercios desde los botones desplegables
    comercios_desde_botones = {}
    for btn in legal.find_all('button', class_='desplegable'):
        b_tag = btn.find('b')
        if b_tag:
            comercio_raw = b_tag.get_text(strip=True)
            # Normalizar: buscar en _SLUG_NOMBRE el nombre canónico
            comercio_normalizado = _normalizar_comercio(comercio_raw)
            if comercio_normalizado:
                comercios_desde_botones[comercio_raw] = comercio_normalizado

    # Paso 2: Parsear T&C y asociar con comercios
    seen: set = set()
    for item in contenedor.find_all('div', recursive=False):
        txt = item.get_text(' ', strip=True)
        if not txt:
            continue
        # Clave de deduplicación
        key = ' '.join(txt.split())[:150]
        if key in seen:
            continue
        seen.add(key)
        
        # Intenta identificar comercio desde el texto T&C (fallback)
        comercio = _identificar_comercio_desde_tyc(txt)
        
        if comercio:
            tyc.setdefault(comercio, []).append(txt)

    return tyc


def _normalizar_comercio(texto: str) -> str:
    """Normaliza el nombre del comercio desde el botón desplegable."""
    texto = texto.strip().lower()
    # Busca coincidencia en _SLUG_NOMBRE
    for slug, nombre in _SLUG_NOMBRE.items():
        if nombre.lower() == texto or nombre.lower().replace("'", "") == texto.replace("'", ""):
            return nombre  # Retorna el nombre canónico
    # Si no encuentra coincidencia exacta, retorna el texto normalizado
    return texto.title()


def _identificar_comercio_desde_tyc(texto: str) -> str:
    """Detecta qué comercio corresponde al inicio del texto de TyC."""
    txt_low = texto.lower()
    # Probar nombres display (más largo primero para evitar prefijos cortos)
    for slug, nombre in sorted(_SLUG_NOMBRE.items(), key=lambda x: -len(x[1])):
        variantes = [
            nombre.lower(),
            re.sub(r"['\u00e1-\u00fc]", '', nombre.lower()),  # sin tildes/apóstrofes
            slug.replace('-', ' '),
        ]
        if any(txt_low.startswith(v) for v in variantes):
            return nombre  # Retorna el nombre canónico
    # Casos especiales
    if txt_low.startswith('lttle') or txt_low.startswith('little'):
        return 'Little Caesars Pizza'
    if txt_low.startswith('chillis') or txt_low.startswith("chilli"):
        return "Chili's"
    return ""


def _strip_nombre_tyc(texto: str, comercio_o_slug: str) -> str:
    """Quita el prefijo del nombre del comercio del texto de TyC."""
    # Si es comercio normalizado, usarlo directamente; si es slug, obtener nombre
    nombre = comercio_o_slug if comercio_o_slug and re.search(r'[A-Z]', comercio_o_slug) else _SLUG_NOMBRE.get(comercio_o_slug, comercio_o_slug.replace('-', ' '))
    
    # Variantes a probar
    variantes = [
        nombre,
        re.sub(r"['\u00e1-\u00fc]", '', nombre),  # sin tildes/apóstrofes
        nombre.lower(),
    ]
    
    # Casos especiales
    if 'caesar' in nombre.lower():
        variantes.extend(['lttle caesar', 'little caesar'])
    if 'chili' in nombre.lower():
        variantes.append('chillis')
    
    for prefix in variantes:
        if prefix and texto.lower().startswith(prefix.lower()):
            return texto[len(prefix):].lstrip(' :.-\n')
    return texto


# ── Extracción de fechas en formato texto (DD de mes de YYYY) ──────────────────

def _extraer_fechas_scb(texto: str) -> Tuple[str, str]:
    """Intenta fechas en texto español 'DD de mes del YYYY' y luego numéricas."""
    txt_lower = texto.lower()
    pat_mes = '|'.join(_MESES)
    
    # PATRÓN 1: "desde el DD al DD de mes del YYYY" (ej: "desde el 01 al 31 de marzo del 2026")
    m_rango1 = re.search(
        r'desde\s+el\s+(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+(' + pat_mes + r')'
        r'(?:\s+de(?:l)?\s+(\d{4}))?',
        txt_lower
    )
    if m_rango1:
        dia1, dia2, mes, anio = m_rango1.groups()
        if anio:
            fi = f"{dia1.zfill(2)}/{_MESES[mes]}/{anio}"
            ff = f"{dia2.zfill(2)}/{_MESES[mes]}/{anio}"
            return fi, ff
    
    # PATRÓN 2: "del DD al DD de mes del YYYY" (ej: "del 01 al 31 de marzo del 2026")
    m_rango2 = re.search(
        r'del\s+(\d{1,2})\s+al\s+(\d{1,2})\s+de\s+(' + pat_mes + r')'
        r'(?:\s+de(?:l)?\s+(\d{4}))?',
        txt_lower
    )
    if m_rango2:
        dia1, dia2, mes, anio = m_rango2.groups()
        if anio:
            fi = f"{dia1.zfill(2)}/{_MESES[mes]}/{anio}"
            ff = f"{dia2.zfill(2)}/{_MESES[mes]}/{anio}"
            return fi, ff
    
    # PATRÓN 3: "del DD de mes [del YYYY] al DD de mes del YYYY" (ej: "del 01 de febrero hasta el 31 de marzo")
    m_rango3 = re.search(
        r'(?:del?|desde\s+el?)\s+(\d{1,2})\s+de\s+(' + pat_mes + r')(?:\s+de(?:l)?\s+(\d{4}))?'
        r'\s+(?:al?|hasta\s+el?)\s+(\d{1,2})\s+de\s+(' + pat_mes + r')(?:\s+de(?:l)?\s+(\d{4}))?',
        txt_lower
    )
    if m_rango3:
        dia1, mes1, y1, dia2, mes2, y2 = m_rango3.groups()
        # Si el año no aparece en la primera fecha, heredar del segundo
        y1 = y1 or y2
        if y1 and y2:
            fi = f"{dia1.zfill(2)}/{_MESES[mes1]}/{y1}"
            ff = f"{dia2.zfill(2)}/{_MESES[mes2]}/{y2}"
            return fi, ff

    # PATRÓN 4: "única fecha hasta [el] DD de mes [del YYYY]"
    m_fin = re.search(
        r'(?:hasta|vence\s+el?)\s+(\d{1,2})\s+de\s+(' + pat_mes +
        r')(?:\s+de(?:l)?\s+(\d{4}))?',
        txt_lower
    )
    if m_fin:
        dia, mes, anio = m_fin.groups()
        if anio:
            return "", f"{dia.zfill(2)}/{_MESES[mes]}/{anio}"

    # PATRÓN 5: fechas numéricas (utils.extraer_fechas)
    fi, ff = extraer_fechas(texto)
    # Evitar fecha_inicio == fecha_fin si proviénen del mismo match
    if fi and fi == ff:
        return "", ff
    return fi, ff


def _extraer_promocion_desde_tyc(condiciones: str) -> str:
    """
    Extrae la LÍNEA COMPLETA DE PROMOCIÓN desde los T&C.
    ESTRATEGIA: Busca la PRIMERA línea que contenga "a S/" (precio directo) o patrón de descuento.
    Eso es la verdadera promoción. Luego busca fallbacks.
    
    Maneja patrones como:
    - "3 piezas crispy... a S/25.00"
    - "Promoción incluye 20 makis a sólo S/29.90"
    - "Una (01) Pizza Personal... a S/ 7.50"
    - "20% de Dcto. en los servicios..."
    """
    if not condiciones or len(condiciones) < 10:
        return ''
    
    condiciones = condiciones.strip()
    
    # Dividir por puntos/saltos de línea para obtener oraciones individuales
    lineas = re.split(r'(?<=[.!?;])\s+|\n+', condiciones)
    
def _extraer_promocion_desde_tyc(condiciones: str) -> str:
    """
    Extrae la LÍNEA COMPLETA DE PROMOCIÓN desde los T&C.
    ESTRATEGIA: Busca la PRIMERA línea que contenga "a S/" (precio directo) o patrón de descuento.
    Eso es la verdadera promoción. Luego busca fallbacks.
    
    Maneja patrones como:
    - "3 piezas crispy... a S/25.00"
    - "Promoción incluye 20 makis a sólo S/29.90"
    - "Una (01) Pizza Personal... a S/ 7.50"
    - "20% de Dcto. en los servicios..."
    - "S/2.00 de Dscto. por cada galón..."
    """
    if not condiciones or len(condiciones) < 10:
        return ''
    
    condiciones = condiciones.strip()
    
    # BÚSQUEDA PRIORITARIA 1: "S/X.XX de Dscto/Descuento por cada..." (para Repsol)
    m = re.search(r'S/\s*[\d,.]+\s+de\s+(?:dcto|descuento|dscto|off)\s*\.?\s+(?:por|en)\s+(?:cada|la|en)\s+.+?(?=\s+(?:pagando|válid|$))', condiciones, re.I)
    if m:
        resultado = m.group(0).strip()
        resultado = resultado.rstrip('.')
        if resultado and len(resultado) >= 8:
            return resultado
    
    # BÚSQUEDA PRIORITARIA 2: texto que contiene "a solo S/" después de "Promoción incluye"  (para Norky's)
    m = re.search(r'Promoción\s+incluye\s+(.+?)\s+(?:en|a\s+nivel)', condiciones, re.I)
    if m:
        resultado = m.group(1).strip()
        # Asegurar que contiene precio  
        if 'S/' in resultado or 'a solo' in resultado.lower():
            resultado = resultado.rstrip('.')
            if resultado and len(resultado) >= 5:
                return resultado
    
    # Dividir por puntos/saltos de línea para obtener oraciones individuales
    lineas = re.split(r'(?<=[.!?;])\s+|\n+', condiciones)
    
    # ESTRATEGIA: Buscar PRIORITARIAMENTE la primera línea con precio directo
    # Esto captura "3 piezas... a S/25.00" o "Promoción incluye 20 makis a sólo S/29.90"
    for linea in lineas:
        linea = linea.strip()
        if not linea or len(linea) < 5:
            continue
        
        # PRIORIDAD 1: Línea que contiene "a S/" o "a sólo S/" - esa es la promo de precio
        # Buscar desde el inicio de la línea hasta el precio (S/XXX.XX)
        m = re.search(r'^(.+?)\s+a\s+s[ó]?lo\s+S/\s*[\d,.]+', linea, re.I)
        if not m:
            m = re.search(r'^(.+?)\s+a\s+S/\s*[\d,.]+', linea, re.I)
        
        if m:
            resultado = m.group(0).strip()
            
            # Limpia nombre del comercio + prefijos innecesarios
            # Nombres comunes a buscar (incluyendo variantes sin apóstrofe)
            nombres_comercios = ['Pizza Hut', 'Isushi', 'Cinnabon', 'Chillis', 'Chilis',
                                'Madam Tusan', 'Friday', "Fridays", 'Burger King', 
                                'Little Caesars', 'Bembos', 'Ripley', 'Falabella', 
                                'Kfc', 'KFC', 'Starbucks', 'Thai Wok', 'Tambo',
                                'Bata', 'Beso Francés', 'OXXO', 'Papa John', 'Pikalo',
                                'Pinkberry', 'RepShop', 'Repsol', 'Subway', 'Ámphora',
                                'Montalvo', "Norky's", "Norkys"]
            for nombre in nombres_comercios:
                if resultado.lower().startswith(nombre.lower()):
                    resultado = resultado[len(nombre):].lstrip(' :.-\n')
                    break
            
            # Limpia prefijos de tipo "La promoción incluye"
            resultado = re.sub(r'^(?:la\s+)?(?:promoci[oó]n\s+)?(?:incluye|ofrece)\s*:?\s*', '', resultado, flags=re.I)
            resultado = resultado.strip()
            
            # Limpia guiones y espacios iniciales (para casos como "- 3 Yogurt...")
            resultado = re.sub(r'^[-–—]\s+', '', resultado)
            resultado = resultado.strip()
            
            # Limpia puntos finales
            resultado = resultado.rstrip('.')
            
            if resultado and len(resultado) >= 5:
                return resultado
        
        # PRIORIDAD 2: Porcentaje de descuento al inicio de línea
        if re.search(r'^\d{1,3}%\s+(?:de\s+)?(?:dcto|descuento|off)', linea, re.I):
            m = re.search(r'^(\d{1,3}%\s+(?:de\s+)?(?:dcto|descuento|off)\s+en\s+.+?)(?:\s+pagando|\s+promoci[oó]n\s+v[aá]lid|en\s+tiendas|$)', linea, re.I)
            if m:
                resultado = m.group(1).strip()
            else:
                resultado = linea.strip()
            if resultado and len(resultado) >= 5:
                return resultado
        
        # PRIORIDAD 3: Ofertas como "2x1", "3x2", etc. al inicio
        if re.search(r'^\d+x\d+', linea, re.I):
            m = re.search(r'^(.+?\d+x\d+.+?)(?:\s+a\s+S/\s*[\d,.]+|\s+en\s+|$)', linea, re.I)
            if m:
                resultado = m.group(0).strip()
            else:
                resultado = linea.strip()
            if resultado and len(resultado) >= 5:
                return resultado
        
        # PRIORIDAD 4: "Llévate" al inicio de línea
        if re.search(r'^ll[eé]vate', linea, re.I):
            m = re.search(r'^(ll[eé]vate\s+.+?)(?:\s+(?:en\s+|pagando|a\s+nivel)|\.|$)', linea, re.I)
            if m:
                resultado = m.group(0).strip()
            else:
                resultado = linea.strip()
            if resultado and len(resultado) >= 5:
                return resultado
    
    # Fallback: "Válido para [PROMOCIÓN]" (cuando la promo está en formato "Válido para X")
    m = re.search(r'v[aá]lido\s+para\s+(.+?)(?:\.\s+(?:Precio\s+regular|Stock|Promoci[oó]n\s+v[aá]lid|Válido\s+del|Stock\s+total)|$)', condiciones, re.I)
    if m:
        promo = m.group(1).strip()
        # Limpia sufijos de condiciones
        promo = re.sub(r'\s+(?:pagando\s+con|escaneando|en\s+(?:todas\s+)?las|a\s+nivel).*$', '', promo, flags=re.I).strip()
        if promo and len(promo) >= 5:
            return promo
    
    # Último fallback: Si el T&C dice "Promoción válida [fecha]" pero no especifica QUÉ es la promo,
    # retornar vacío (el título se llenará desde la imagen después)
    return ''


def _extraer_producto_desde_condiciones(condiciones: str) -> str:
    """
    Extrae SOLO el PRODUCTO que se vende desde las condiciones (sin precio).
    Retorna solo los artículos/items, sin precios ni detalles de vigencia.
    
    DEPRECATED: Usar _extraer_promocion_desde_tyc para obtener línea completa.
    """
    if not condiciones or len(condiciones) < 10:
        return ''
    
    condiciones = condiciones.strip()
    
    # Busca específicamente: "incluye", "la promoción incluye", "promoción incluye" y derivadas
    m = re.search(
        r'(?:la\s+)?(?:promoci[oó]n\s+)?incluye\s*:?\s*(.+?)(?:\s+a\s+S/|precio\s+regular|\(\s*precio|v[aá]lid|stock|m[aá]ximo|m[íi]nimo|$)',
        condiciones, re.I
    )
    if m:
        items_text = m.group(1).strip()
        # Quita cantidad inicial (1, 2, 3, etc.) y palabras de relleno
        items_text = re.sub(r'^\d+\s+', '', items_text)
        # Divide por + y limpia cada item
        items = [s.strip() for s in items_text.split('+')]
        items = [s for s in items if s and not re.match(r'^(?:a\s+sólo|solo|por|en|,)', s, re.I)]
        items = [s for s in items if len(s) < 80]  # descarta items demasiado largos
        if items:
            # Capitaliza cada item y limpia
            items_clean = []
            for item in items:
                item = re.sub(r'\s*\(\s*precio.+?\)', '', item, flags=re.I)
                item = item.strip()
                if item and len(item) < 80:
                    items_clean.append(item.title())
            if items_clean:
                return ' + '.join(items_clean[:5])  # máx 5 items
    
    return ''  # No encontró "incluye"


def _extraer_stock_scb(condiciones: str) -> str:
    """
    Extrae SOLO el VALOR NUMÉRICO del stock desde las condiciones.
    Busca múltiples patrones de forma flexible e interpretativa:
    - "Stock [total] [máximo/mínimo] de XXX unidades"
    - "Stock de XXX unidades"
    - "Stock: XXX"
    - "stock disponible XXX"
    - etc.
    
    Retorna solo el número principal, sin unidades ni comas.
    
    Ejemplos:
    - "Stock de 500 unidades" → "500"
    - "Stock total mínimo de 5000 unidades" → "5000"
    - "Stock máximo de 200 promociones" → "200"
    - "Stock de 2,000 promociones" → "2000"
    - "Stock: 100" → "100"
    """
    if not condiciones:
        return ''
    
    condiciones = condiciones.strip()
    
    # Patrón 1: "Stock [total] [máximo/mínimo] de XXX [unidades/promociones/promos]"
    # Captura: "stock de 500", "stock total mínimo de 5000", "stock máximo de 200", etc.
    # "total" es opcional, máximo/mínimo es opcional
    m = re.search(
        r'stock\s+(?:total\s+)?(?:(?:m[aá]ximo|m[íi]nimo|disponible)\s+)?de\s+(\d+(?:[,\.]\d+)?)',
        condiciones, re.I
    )
    if m:
        num = m.group(1).strip()
        num = num.replace(',', '').replace('.', '')
        return num
    
    # Patrón 2: "Stock: XXX" o "Stock xxx XXX" (con dos espacios o específico)
    m = re.search(
        r'stock\s*:?\s*(\d+(?:[,\.]\d+)?)',
        condiciones, re.I
    )
    if m:
        num = m.group(1).strip()
        num = num.replace(',', '').replace('.', '')
        return num
    
    # Patrón 3: "Promociones?: XXX" o "Promociones? de XXX" (sin "stock" explícito)
    m = re.search(
        r'(?:promociones?|promo)\s+(?:de|:)?\s*(\d+(?:[,\.]\d+)?)',
        condiciones, re.I
    )
    if m:
        num = m.group(1).strip()
        num = num.replace(',', '').replace('.', '')
        return num
    
    # Patrón 4: "Disponible(s)? XXX" (patrón muy general, al final)
    m = re.search(
        r'disponible(?:s|\s+)?:?\s*(\d+(?:[,\.]\d+)?)',
        condiciones, re.I
    )
    if m:
        num = m.group(1).strip()
        num = num.replace(',', '').replace('.', '')
        return num
    
    return ''  # No encontró stock


def _titular_desde_condiciones(condiciones: str) -> str:
    """
    Extrae el 'titular' de la promo: LA LÍNEA COMPLETA DE PROMOCIÓN desde T&C.
    Si no encuentra promoción con precio/descuento real, deja que use el nombre del comercio.
    """
    # Intenta extraer la línea completa de promoción
    promocion = _extraer_promocion_desde_tyc(condiciones)
    if promocion:
        return promocion
    
    # Si no hay promoción extraída y el T&C no contiene "a S/" o descuento claro,
    # es porque el T&C solo tiene meta-información, no descripción de promo.
    # Retornar vacío para que use el nombre del comercio.
    if not re.search(r'a\s+S/|%\s+(?:de\s+)?(?:dcto|descuento|off)|2x1|3x2|\d+x\d+', condiciones, re.I):
        return ''
    
    # Fallback: primera oración con contenido relevante que no sea meta-información
    _SKIP = re.compile(
        r'^(?:Promoci[oó]n\s+v[aá]lid[ao]|[Vv][aá]lid[ao]\s+del?|[Ss]tock:|[Vv]igencia|'
        r'\d+\s+Condiciones|[Ll]a\s+promoci[oó]n|Horario|El precio|No\s+(?:aplica|se|acept|'
        r'acumul|cumable|v[aá]lid)|[Mm]?[Áá]ximo|Exclusivo|Sujeto|Imágenes)',
        re.I)
    
    oraciones = re.split(r'(?<=[.!?])\s+', condiciones.strip())
    
    # Busca primera oración que no sea meta-información
    for oracion in oraciones[:10]:
        if not _SKIP.match(oracion) and len(oracion) > 5:
            return oracion.strip().rstrip('.').strip()[:130]
    
    # Si todo falla, retornar string vacío (el comercio usará su nombre como fallback)
    return ''


# ── Construcción de Promociones ───────────────────────────────────────────────

def _construir_promociones(
    imgs_por_slug: Dict[str, List[dict]],
    tyc_dict:      Dict[str, List[str]],
    fuente:        str,
    url:           str,
) -> List[Promocion]:
    """
    Construye promociones mergeando imágenes y T&C.
    Ahora tyc_dict tiene COMERCIOS NORMALIZADOS como claves (desde los botones HTML).
    """
    promociones: List[Promocion] = []
    
    # Paso 1: Mapear slugs a comercios normalizados desde tyc_dict
    # El tyc_dict ahora tiene comercios normalizados como claves
    comercios_procesados = set()
    
    # Procesar por comercios en tyc_dict (fuente de verdad)
    for comercio_normalizado in sorted(tyc_dict.keys()):
        comercios_procesados.add(comercio_normalizado)
        
        # Buscar slug correspondiente desde _SLUG_NOMBRE (búsqueda invertida)
        slug = None
        for s, nombre in _SLUG_NOMBRE.items():
            if nombre == comercio_normalizado:
                slug = s
                break
        
        # Si no encuentra slug desde diccionario, buscar en imgs
        if not slug:
            for s_img in imgs_por_slug.keys():
                nombre_img = _slug_a_nombre(s_img)
                if nombre_img == comercio_normalizado:
                    slug = s_img
                    break
        
        # Obtener datos
        nombre    = comercio_normalizado
        imgs      = imgs_por_slug.get(slug, []) if slug else []
        tyc_items = tyc_dict.get(comercio_normalizado) or [""]
        categoria = imgs[0]['categoria'] if imgs else _SLUG_CATEGORIA_DEFAULT.get(slug, 'General') if slug else 'General'
        
        # Crear promoción por cada T&C
        for i, tyc_raw in enumerate(tyc_items):
            condiciones  = _strip_nombre_tyc(tyc_raw, nombre) if tyc_raw else tyc_raw.strip() if tyc_raw else ''
            precio, tipo = (extraer_precio_tipo_de_texto(condiciones)
                            if condiciones else ("", "Beneficio"))
            stock        = _extraer_stock_scb(condiciones) if condiciones else ''
            fi, ff       = _extraer_fechas_scb(condiciones) if condiciones else ('', '')
            titulo       = (_titular_desde_condiciones(condiciones) or nombre
                            if condiciones else nombre)
            # Imagen: la coincidente por índice, o la primera disponible
            img_url = (imgs[i]['img_url'] if i < len(imgs)
                       else (imgs[0]['img_url'] if imgs else ''))

            promociones.append(Promocion(
                fuente       = fuente,
                categoria    = categoria,
                comercio     = nombre,
                titulo       = titulo,
                descripcion  = "",
                precio       = precio,
                tipo         = tipo,
                fecha_inicio = fi,
                fecha_fin    = ff,
                stock        = stock,
                url          = url,
                imagen_url   = img_url,
                condiciones  = condiciones,
            ))

    return promociones
