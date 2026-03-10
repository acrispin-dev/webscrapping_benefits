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
    Parsea el bloque div.legal → {slug: [condicionesText, ...]}.
    Cada div hijo de 'div.mt-3' empieza con el nombre del comercio.
    """
    tyc: Dict[str, List[str]] = {}
    legal = soup.select_one('div.legal')
    if not legal:
        return tyc

    contenedor = legal.select_one('div.mt-3')
    if not contenedor:
        return tyc

    seen: set = set()
    for item in contenedor.find_all('div', recursive=False):
        txt = item.get_text(' ', strip=True)
        if not txt:
            continue
        # Clave de deduplicación: ignorar diferencias triviales de espaciado
        key = ' '.join(txt.split())[:150]
        if key in seen:
            continue
        seen.add(key)
        slug = _identificar_slug(txt)
        if slug:
            tyc.setdefault(slug, []).append(txt)

    return tyc


def _identificar_slug(texto: str) -> str:
    """Detecta qué slug corresponde al inicio del texto de TyC."""
    txt_low = texto.lower()
    # Probar nombres display (más largo primero para evitar prefijos cortos)
    for slug, nombre in sorted(_SLUG_NOMBRE.items(), key=lambda x: -len(x[1])):
        variantes = [
            nombre.lower(),
            re.sub(r"['\u00e1-\u00fc]", '', nombre.lower()),  # sin tildes/apóstrofes
            slug.replace('-', ' '),
        ]
        if any(txt_low.startswith(v) for v in variantes):
            return slug
    # Casos especiales del texto de TyC (typos de Scotiabank)
    if txt_low.startswith('lttle') or txt_low.startswith('little'):
        return 'little-caesars-pizza'
    if txt_low.startswith('chillis') or txt_low.startswith("chilli"):
        return 'chilis'
    return ""


def _strip_nombre_tyc(texto: str, slug: str) -> str:
    """Quita el prefijo del nombre del comercio del texto de TyC."""
    nombre = _SLUG_NOMBRE.get(slug, slug.replace('-', ' '))
    for prefix in [nombre, re.sub(r"['\u00e1-\u00fc]", '', nombre), slug.replace('-', ' '),
                   'lttle caesar', 'little caesar', 'chillis']:
        if texto.lower().startswith(prefix.lower()):
            return texto[len(prefix):].lstrip(' :.-\n')
    return texto


# ── Extracción de fechas en formato texto (DD de mes de YYYY) ──────────────────

def _extraer_fechas_scb(texto: str) -> Tuple[str, str]:
    """Intenta fechas en texto español 'DD de mes del YYYY' y luego numéricas."""
    # Patrón 1: rango explícito "del DD de mes [del YYYY] al DD de mes del YYYY"
    pat_mes = '|'.join(_MESES)
    m_rango = re.search(
        r'(?:del?\s+)?(\d{1,2})\s+de\s+(' + pat_mes + r')(?:\s+de(?:l)?\s+(\d{4}))?'
        r'\s+al?\s+(\d{1,2})\s+de\s+(' + pat_mes + r')(?:\s+de(?:l)?\s+(\d{4}))?',
        texto.lower()
    )
    if m_rango:
        dia1, mes1, y1, dia2, mes2, y2 = m_rango.groups()
        # Si el año no aparece en la primera fecha, heredar del segundo
        y1 = y1 or y2
        if y1 and y2:
            fi = f"{dia1.zfill(2)}/{_MESES[mes1]}/{y1}"
            ff = f"{dia2.zfill(2)}/{_MESES[mes2]}/{y2}"
            return fi, ff

    # Patrón 2: "única fecha hasta [el] DD de mes [del YYYY]"
    m_fin = re.search(
        r'(?:hasta|vence\s+el?)\s+(\d{1,2})\s+de\s+(' + pat_mes +
        r')(?:\s+de(?:l)?\s+(\d{4}))?',
        texto.lower()
    )
    if m_fin:
        dia, mes, anio = m_fin.groups()
        if anio:
            return "", f"{dia.zfill(2)}/{_MESES[mes]}/{anio}"

    # Patrón 3: fechas numéricas (utils.extraer_fechas)
    fi, ff = extraer_fechas(texto)
    # Evitar fecha_inicio == fecha_fin si proviénen del mismo match
    if fi and fi == ff:
        return "", ff
    return fi, ff


def _titular_desde_condiciones(condiciones: str) -> str:
    """Extrae el 'titular' de la promo: primera oración con precio o producto.
    Retorna '' si todas las oraciones son solo de validez/fechas (el caller usa nombre como fallback)."""
    _SKIP = re.compile(
        r'^(?:Promoci[oó]n\s+v[aá]lid[ao]|[Vv][aá]lid[ao]\s+del?|[Ss]tock:|[Vv]igencia)',
        re.I)
    _KEEP = re.compile(r'S/\s*\d|%\s*de?\s*d(?:escuento|cto|to)|incluye|ll[eé]vate|v[aá]lido\s+para', re.I)
    oraciones = re.split(r'(?<=[.!?])\s+', condiciones.strip())
    # Prioridad 1: oración con precio/producto que no sea solo de validez
    for oracion in oraciones[:6]:
        if not _SKIP.match(oracion) and _KEEP.search(oracion):
            return oracion.strip().rstrip('.').strip()[:160]
    # Prioridad 2: cualquier oración que no sea de validez/stock
    for oracion in oraciones[:6]:
        if not _SKIP.match(oracion):
            return oracion.strip()[:130]
    return ''   # caller usará el nombre del comercio como título


# ── Construcción de Promociones ───────────────────────────────────────────────

def _construir_promociones(
    imgs_por_slug: Dict[str, List[dict]],
    tyc_dict:      Dict[str, List[str]],
    fuente:        str,
    url:           str,
) -> List[Promocion]:
    promociones: List[Promocion] = []
    slugs = set(imgs_por_slug) | set(tyc_dict)

    for slug in sorted(slugs):
        nombre    = _slug_a_nombre(slug)
        imgs      = imgs_por_slug.get(slug, [])
        tyc_items = tyc_dict.get(slug) or [""]   # al menos una pasada vacía

        # Categoría: desde imagen activa o fallback por slug
        if imgs:
            categoria = imgs[0]['categoria']
        else:
            categoria = _SLUG_CATEGORIA_DEFAULT.get(slug, 'General')

        for i, tyc_raw in enumerate(tyc_items):
            condiciones  = _strip_nombre_tyc(tyc_raw, slug) if tyc_raw else ''
            precio, tipo = (extraer_precio_tipo_de_texto(condiciones)
                            if condiciones else ("", "Beneficio"))
            stock        = extraer_stock(condiciones) if condiciones else ''
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
