"""
scrapers/utils.py — Funciones de extracción compartidas entre scrapers.
"""
import re
from typing import Tuple


def clasificar_precio_tipo(texto_valor: str, texto_etiqueta: str = "") -> Tuple[str, str]:
    """
    Analiza el valor de descuento/precio e infiere (precio_str, tipo_str).

    tipo_str puede ser:
        "% Descuento"  → descuento porcentual (precio = entero, e.g. "30")
        "Precio promo" → precio en soles  (precio = "S/ X.XX")
        "Beneficio"    → otro tipo de beneficio
    """
    val = texto_valor.strip()
    etiqueta = texto_etiqueta.lower().strip()

    # ── Porcentaje explícito ─────────────────────────────────────────────────
    m_pct = re.search(r'(\d+)\s*%', val)
    if m_pct:
        return m_pct.group(1), "% Descuento"

    # Porcentaje en la etiqueta con número en val
    if re.search(r'desc|dscto|dto\.?|off\b', etiqueta):
        m_num = re.search(r'(\d+)', val)
        if m_num:
            return m_num.group(1), "% Descuento"

    # ── Precio en soles ─────────────────────────────────────────────────────
    m_sol = re.search(r'[Ss]/\.?\s*([\d.,]+)', val)
    if m_sol:
        return f"S/ {m_sol.group(1)}", "Precio promo"

    if re.search(r'precio|superprecio|s[uú]per|oferta', etiqueta):
        m_num = re.search(r'[\d.,]+', val)
        if m_num:
            return f"S/ {m_num.group(0)}", "Precio promo"

    # ── Extrae porcentaje del texto libre ────────────────────────────────────
    m_pct2 = re.search(r'(\d{1,3})\s*%\s*(?:de\s+)?(?:desc|dscto|dto|off)', val, re.IGNORECASE)
    if m_pct2:
        return m_pct2.group(1), "% Descuento"

    # ── Precio extraído de texto libre (e.g. "S/19.90") ─────────────────────
    m_sol2 = re.search(r'[Ss]/\.?\s*([\d.,]+)', val)
    if m_sol2:
        return f"S/ {m_sol2.group(1)}", "Precio promo"

    return val if val else "", "Beneficio"


def extraer_precio_tipo_de_texto(texto: str) -> Tuple[str, str]:
    """
    Intenta extraer precio y tipo directamente de un bloque de texto libre
    (útil para scrapers genéricos que no tienen campos separados).
    """
    # Porcentaje: "30% de descuento", "20% dto", "Hasta 45% off"
    m_pct = re.search(r'(\d{1,3})\s*%\s*(?:de\s+)?(?:desc\w*|dscto\.?|dto\.?|off\b)?', texto, re.IGNORECASE)
    if m_pct:
        return m_pct.group(1), "% Descuento"

    # Precio: "S/ 9.90", "S/9.90", "s/19.90"
    m_sol = re.search(r'[Ss]/\.?\s*([\d.,]+)', texto)
    if m_sol:
        return f"S/ {m_sol.group(1)}", "Precio promo"

    return "", "Beneficio"


def extraer_stock(texto: str) -> str:
    """
    Busca menciones de stock/cantidad máxima/mínima en texto libre.
    Soporta patrones como: "máximo X", "mínimo X", "stock X", "promociones X", etc.
    """
    texto_l = texto.lower()
    
    # Patrones especializados que SÍ retornan número (se verifican PRIMERO)
    patrones_con_numero = [
        # "Hasta agotar stock 500 unidades" (nuevo patrón)
        (r'hasta\s+agotar\s+stock\s+(\d+)\s*(?:unidades?|und\.?)?', 'stock'),
        # "Stock mínimo/máximo de X unidades" (nuevo patrón)
        (r'stock\s+(?:mínimo|máximo|min|max)\s+de\s+(\d+)\s*(?:unidades?|und\.?)?', 'stock'),
        # "Máximo X promociones/unidades por cliente" → extrae el número
        (r'(?:máximo|mínimo|min|max)\s+(\d+)\s*(?:promociones?|unidades?|und\.?|cupos?|lugares?|descuentos?|por\s+cliente)?', 'stock'),
        # "Stock: X" o "Stock de X"
        (r'stock\s*:?\s*(\d+)\s*(?:unidades?|und\.?|disponibles?)?', 'stock'),
        # "X unidades disponibles"
        (r'(\d+)\s*(?:unidades?|und\.?|cupos?|lugares?|descuentos?)\s+(?:disponibles?|máximo)?', 'cantidad'),
        # "X promociones" (cuando aparece en contexto de cantidad)
        (r'(\d+)\s+promociones?\s+(?:por\s+cliente|al\s+día|diarias?)?', 'promociones'),
    ]
    
    for patron, tipo in patrones_con_numero:
        m = re.search(patron, texto_l, re.IGNORECASE)
        if m:
            # Si tiene grupo de captura (número), retorna solo el número
            if m.groups():
                return m.group(1).strip()
    
    # Patrones que NO retornan número (son estado general, no cantidad específica)
    # Se verifican al FINAL para no interferir con patrones que sí tienen números
    patrones_sin_numero = [
        r'sujeto\s+a\s+(?:la\s+)?disponibilidad',
        r'stock\s+limitado',
        r'(?<!agotar\s)(?:mientras)\s+(?:agotar\s+)?(?:el\s+)?stock',
    ]
    
    # Si cuenta con estos patrones sin número específico, retorna vacío
    for patron in patrones_sin_numero:
        if re.search(patron, texto_l, re.IGNORECASE):
            return ""
    
    # Si nada coincidió, retorna vacío
    return ""


def extraer_fechas(texto: str) -> Tuple[str, str]:
    """
    Intenta extraer (fecha_inicio, fecha_fin) de un texto.
    Soporta múltiples formatos: DD/MM/YYYY, DD-MM-YYYY, texto en español, etc.
    Retorna (str, str) — vacío si no se encuentra.
    """
    if not texto:
        return "", ""
    
    texto_l = texto.lower()
    
    # Diccionario de meses en español
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'setiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }
    
    # ── PATRÓN 1: Fechas numéricas en rango "DD/MM/YYYY - DD/MM/YYYY" ──────────────
    m_rango_num = re.search(
        r'(?:del?\s+)?(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{2,4})'
        r'\s*(?:al?|a|[-–]|hasta)\s*'
        r'(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{2,4})',
        texto_l
    )
    if m_rango_num:
        d1, m1, y1, d2, m2, y2 = m_rango_num.groups()
        y1 = f"20{y1}" if len(y1) == 2 else y1
        y2 = f"20{y2}" if len(y2) == 2 else y2
        inicio = f"{d1.zfill(2)}/{m1.zfill(2)}/{y1}"
        fin = f"{d2.zfill(2)}/{m2.zfill(2)}/{y2}"
        return inicio, fin
    
    # ── PATRÓN 2: Fechas en texto español "DD de mes...DD de mes del YYYY" ────────
    # Ejemplo: "desde 01 de enero hasta 30 de junio de 2026" OR "01 enero hasta 30 junio"
    m_texto_es = re.search(
        r'(?:desde\s+el?\s+)?(\d{1,2})\s+(?:de\s+)?(\w+).*?'
        r'(?:hasta\s+el?\s+)?(\d{1,2})\s+(?:de\s+)?(\w+)\s+(?:del?\s+)?(\d{2,4})',
        texto_l
    )
    if m_texto_es:
        d1, mes1, d2, mes2, year = m_texto_es.groups()
        mes1_num = meses.get(mes1.lower(), "")
        mes2_num = meses.get(mes2.lower(), "")
        if mes1_num and mes2_num:
            year = f"20{year}" if len(year) == 2 else year
            inicio = f"{d1.zfill(2)}/{mes1_num}/{year}"
            fin = f"{d2.zfill(2)}/{mes2_num}/{year}"
            return inicio, fin
    
    # ── PATRÓN 3: Variante "Válido desde DD mes hasta DD mes del YYYY" ────────────
    m_valido = re.search(
        r'válid[oa]?\s+(?:desde\s+)?el?\s+(\d{1,2})\s+(?:de\s+)?(\w+).*?'
        r'(?:hasta\s+)?el?\s+(\d{1,2})\s+(?:de\s+)?(\w+)\s+(?:del?\s+)?(\d{2,4})',
        texto_l
    )
    if m_valido:
        d1, mes1, d2, mes2, year = m_valido.groups()
        mes1_num = meses.get(mes1.lower(), "")
        mes2_num = meses.get(mes2.lower(), "")
        if mes1_num and mes2_num:
            year = f"20{year}" if len(year) == 2 else year
            inicio = f"{d1.zfill(2)}/{mes1_num}/{year}"
            fin = f"{d2.zfill(2)}/{mes2_num}/{year}"
            return inicio, fin
    
    # ── PATRÓN 4: Solo fecha fin "hasta DD/MM/YYYY" o "vence DD/MM/YYYY" ────────
    m_fin_num = re.search(
        r'(?:hasta|vence|válido\s+hasta)\s+(?:el?\s+)?(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{2,4})',
        texto_l
    )
    if m_fin_num:
        d, m, y = m_fin_num.groups()
        y = f"20{y}" if len(y) == 2 else y
        fin = f"{d.zfill(2)}/{m.zfill(2)}/{y}"
        return "", fin
    
    # ── PATRÓN 5: Disponible desde/hasta en formato de fecha solo mes/día ────────
    m_mes_dia = re.search(
        r'(?:disponible\s+)?(?:desde|del?)\s+(\d{1,2})[/\.\-](\d{1,2})\s*(?:al?|a|hasta)\s*(\d{1,2})[/\.\-](\d{1,2})',
        texto_l
    )
    if m_mes_dia:
        d1, m1, d2, m2 = m_mes_dia.groups()
        m_year = re.search(r'(\d{4})\b', texto_l)
        year = m_year.group(1) if m_year else "2026"
        inicio = f"{d1.zfill(2)}/{m1.zfill(2)}/{year}"
        fin = f"{d2.zfill(2)}/{m2.zfill(2)}/{year}"
        return inicio, fin
    
    # ── PATRÓN 6: Formato "promoción del 01-10-2025 al 31-12-2025" ──────────────
    m_del_al = re.search(
        r'del?\s+(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\s+al?\s+(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})',
        texto_l
    )
    if m_del_al:
        d1, m1, y1, d2, m2, y2 = m_del_al.groups()
        y1 = f"20{y1}" if len(y1) == 2 else y1
        y2 = f"20{y2}" if len(y2) == 2 else y2
        inicio = f"{d1.zfill(2)}/{m1.zfill(2)}/{y1}"
        fin = f"{d2.zfill(2)}/{m2.zfill(2)}/{y2}"
        return inicio, fin
    
    # ── PATRÓN 7: "Disponible hasta el DD de mes de YYYY" (solo fecha fin) ──────
    # Ejemplo: "Disponible hasta el 31 de marzo de 2027"
    m_disponible_hasta = re.search(
        r'disponible\s+hasta\s+el?\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{2,4})',
        texto_l
    )
    if m_disponible_hasta:
        d, mes, year = m_disponible_hasta.groups()
        mes_num = meses.get(mes.lower(), "")
        if mes_num:
            year = f"20{year}" if len(year) == 2 else year
            fin = f"{d.zfill(2)}/{mes_num}/{year}"
            return "", fin
    
    # ── PATRÓN 8: "desde el DD de mes de YYYY" (solo fecha inicio) ──────────────
    # Ejemplo: "desde el 29 de enero de 2026 o hasta agotar stock"
    m_desde = re.search(
        r'desde\s+el?\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{2,4})',
        texto_l
    )
    if m_desde:
        d, mes, year = m_desde.groups()
        mes_num = meses.get(mes.lower(), "")
        if mes_num:
            year = f"20{year}" if len(year) == 2 else year
            inicio = f"{d.zfill(2)}/{mes_num}/{year}"
            return inicio, ""
    
    # ── PATRÓN 9: "del DD y DD de mes de YYYY" (dos días en mismo mes/año) ──────
    # Ejemplo: "del 16 y 17 de febrero de 2026"
    m_dos_dias = re.search(
        r'del?\s+(\d{1,2})\s+y\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{2,4})',
        texto_l
    )
    if m_dos_dias:
        d1, d2, mes, year = m_dos_dias.groups()
        mes_num = meses.get(mes.lower(), "")
        if mes_num:
            year = f"20{year}" if len(year) == 2 else year
            inicio = f"{d1.zfill(2)}/{mes_num}/{year}"
            fin = f"{d2.zfill(2)}/{mes_num}/{year}"
            return inicio, fin
    
    # ── PATRÓN 10: "Promoción válida del 1 de junio 2026 al 30 de junio de 2026" ──
    # (sin "de" en el primer mes, año solo año sin "de")
    m_valida_del = re.search(
        r'válida?\s+del?\s+(\d{1,2})\s+de?\s+(\w+)\s+(\d{4})\s+al?\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})',
        texto_l
    )
    if m_valida_del:
        d1, mes1, year1, d2, mes2, year2 = m_valida_del.groups()
        mes1_num = meses.get(mes1.lower(), "")
        mes2_num = meses.get(mes2.lower(), "")
        if mes1_num and mes2_num:
            inicio = f"{d1.zfill(2)}/{mes1_num}/{year1}"
            fin = f"{d2.zfill(2)}/{mes2_num}/{year2}"
            return inicio, fin
    
    # Si nada coincidió, retorna vacío
    return "", ""


# ── Extracción de comercio ─────────────────────────────────────────────────────

# Marcas/comercios conocidos en el mercado peruano (orden: más específico primero)
_COMERCIOS_KW = [
    # Fast food / Restaurantes cadena
    r'\bKFC\b', r"\bMcDonald'?s?\b", r'\bBurger\s+King\b', r'\bPizza\s+Hut\b',
    r'\bPopeyes?\b', r'\bTambo\b', r'\bBembos\b', r'\bDunkin\b', r'\bStarbucks\b',
    r'\bCinnabon\b', r"\bFriday'?s?\b", r"\bChili'?s?\b", r'\bTony\s+Roma\b',
    r'\bHard\s+Rock\b', r'\bSushi\s+Pop\b', r'\bLe\s+Pain\b', r'\bDenny\'?s?\b',
    r'\bPapachos\b', r'\bNorky\'?s?\b', r'\bROCKY\'?S?\b', r'\bPardo\'?s?\b',
    r'\bRustika\b', r'\bCaracol\b', r'\bDomino\'?s?\b', r'\bOXXO\b',
    r'\bSubway\b', r'\bPapin\b', r'\bTGI\s+Friday\b',
    # Restaurantes gourmet peruanos
    r'\bLa\s+Mar\b', r'\bAstrid\s+y\s+Gast[oó]n\b', r'\bMaido\b',
    r'\bMalabar\b', r'\bPescados\s+Capitales\b', r'\bJohnny\s+Rockets?\b',
    r'\bCr[eê]pe\s+Company\b', r'\bTanta\b', r'\bPike\s+Market\b',
    r'\bOliva\s+Restaurante\b', r'\bPr[eê]t\s+[aà]\s+Manger\b',
    # Delivery / Apps
    r'\bPedidosYa\b', r'\bRappi\b', r'\bGlovo\b', r'\bUber\s*Eats\b',
    # Movilidad
    r'\bUber\b', r'\bCabify\b', r'\bInDriver\b', r'\bBeat\b',
    # Combustible
    r'\bRepsol\b', r'\bPrimax\b', r'\bPecsa\b', r'\bPetroper[uú]\b', r'\bGrifo\b',
    # Entretenimiento
    r'\bCineplanet\b', r'\bCinemark\b', r'\bUVK\b', r'\bCinestar\b',
    # Retail / Tiendas
    r'\bTottus\b', r'\bRipley\b', r'\bFalabella\b', r'\bOechsle\b', r'\bSaga\b',
    r'\bParis\b', r'\bSuperpet\b', r'\bPlaza\s+Vea\b', r'\bWong\b', r'\bMetro\b',
    # Farma / Salud
    r'\bInkafarma\b', r'\bMifarma\b', r'\bBoticas?\s+Fasa\b', r'\bFarmacias?\s+BTL\b',
    # Hoteles / Viajes
    r'\bCasa\s+Andina\b', r'\bMarriott\b', r'\bHilton\b', r'\bCosta\s+del\s+Sol\b',
    r'\bMiraflores\s+Park\b',
    # Aerolíneas
    r'\bLATAM\b', r'\bSky\s+Airline\b', r'\bAvianca\b',
    # Streaming / Digital
    r'\bNetflix\b', r'\bSpotify\b', r'\bDisney\+?\b', r'\bAmazon\s*Prime\b',
    # Pagos / Fintech
    r'\bIzipay\b', r'\bNiubiz\b', r'\bYape\b', r'\bPlin\b',
    # Bebidas
    r'\bCusque\u00f1a\b', r'\bBackus\b', r'\bCorona\b', r'\bPilsen\b',
]


def _buscar_kw(texto: str) -> str:
    """Devuelve la primera marca de _COMERCIOS_KW encontrada en texto, o ''."""
    for patron in _COMERCIOS_KW:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            return m.group(0).strip()
    return ""


def extraer_comercio(titulo: str, descripcion: str = "") -> str:
    """
    Intenta identificar el nombre del comercio/marca a partir de título y descripción.
    Estrategia:
      1. Busca marcas conocidas (lista _COMERCIOS_KW).
      2. Fallback: extrae "carta de [Nombre]" o "en [NombrePropio]" del título.
    """
    texto = titulo + " " + descripcion
    kw = _buscar_kw(texto)
    if kw:
        return kw

    # Fallback A: "[en/de] la carta de [NombrePropio]"
    # Captura: "carta de Zum", "carta de Johnny Rockets!", "carta de Páprika"
    # Nota: NO usa IGNORECASE → requiere que el nombre empiece en mayúscula,
    # así se filtran automáticamente genéricos como "carta de comida", "carta de carnes".
    m = re.search(
        r'\bcarta\s+de\s+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ&\'\-\w]+'
        r'(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ&\'\w]+){0,3})',
        titulo
    )
    if m:
        nombre = m.group(1).strip().rstrip('! .,;')
        return nombre

    # Fallback B: "en NombrePropio" al final del título  (e.g. "30% en Casa Andina")
    m = re.search(
        r'\ben\s+([A-ZÁÉÍÓÚÑ][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1A-Z]{2,}'
        r'(?:\s+[A-ZÁÉÍÓÚÑ][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1A-Z]{2,})?)',
        titulo
    )
    if m:
        return m.group(1).strip()

    return ""


def extraer_comercio_de_condiciones(texto: str) -> str:
    """
    Extrae el nombre del comercio directamente del texto de Términos y Condiciones.

    Patrones típicos en Plin y Falabella:
      - "en las tiendas físicas de Tambo a nivel nacional"
      - "en las tiendas físicas OXXO a nivel nacional"
      - "en todas las tiendas disponibles de KFC"
      - "en tiendas participantes de Repsol"
      - "en establecimientos de Starbucks"
      - "válido en Cineplanet"
      - "exclusivo en KFC"

    Estrategia:
      0. Busca marcas conocidas (_COMERCIOS_KW) en el texto — captura nombres
         compuestos como "Astrid y Gastón" que los patrones de regex fragmentarían.
      1-4. Patrones de texto legal (alta precisión).
      Fallback: delega a extraer_comercio() sobre las primeras 400 chars.
    """
    if not texto:
        return ""

    # Paso 0: marcas conocidas antes que los patrones regex, para no
    # fragmentar nombres compuestos como "Astrid y Gastón" o "La Mar".
    kw = _buscar_kw(texto)
    if kw:
        return kw

    # Patrón 1: "tiendas [tipo]? de [NombrePropio|SIGLA]"
    # Captura: "tiendas físicas de Tambo", "tiendas disponibles de KFC"
    m = re.search(
        r'tiendas\b[^.]{0,30}?\bde\s+'
        r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ&\w]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\w]+){0,3})',
        texto, re.IGNORECASE
    )
    if m:
        nombre = m.group(1).strip().rstrip('.,;')
        # Filtrar falsos positivos (palabras genéricas)
        if nombre.lower() not in ('nivel', 'todo', 'todos', 'peru', 'perú', 'lima'):
            return nombre

    # Patrón 2: "tiendas [tipo]? [SIGLA-MAYÚSCULAS]"
    # Captura: "tiendas físicas OXXO", "tiendas habilitadas KFC"
    m = re.search(
        r'tiendas\b[^.]{0,20}?\s+([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})?)\b',
        texto
    )
    if m:
        nombre = m.group(1).strip()
        if nombre.lower() not in ('nivel', 'todo', 'todos', 'peru', 'perú', 'lima', 'de', 'la', 'las'):
            return nombre

    # Patrón 3: "[establecimientos/restaurantes/sucursales/locales] de [Nombre]"
    # (?i:...) aplica solo al prefijo; el grupo de captura es sensible a mayúsculas
    # para evitar capturar palabras genéricas como 'participantes'.
    m = re.search(
        r'(?i:(?:establecimientos?|restaurantes?|sucursales?|locales?|puntos?\s+de\s+venta)\s+'
        r'(?:participantes?\s+)?(?:de\s+)?)'
        r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ&\w]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\w]+){0,2})',
        texto
    )
    if m:
        nombre = m.group(1).strip().rstrip('.,;')
        if nombre.lower() not in ('nivel', 'todo', 'todos', 'peru', 'perú', 'lima'):
            return nombre

    # Patrón 4: "[válido/exclusivo/aplica] en [Nombre]"
    # (?i:...) aplica solo al prefijo; captura sensible a mayúsculas.
    m = re.search(
        r'(?i:(?:válido?|exclusivo|aplica|disponible)\s+en\s+)'
        r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ&\w]+(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\w]+){0,2})',
        texto
    )
    if m:
        nombre = m.group(1).strip().rstrip('.,;')
        generico = {'salón', 'salon', 'todo', 'todos', 'nivel', 'peru', 'perú', 'lima',
                    'tiendas', 'establecimientos', 'para'}
        if nombre.lower() not in generico:
            return nombre

    # Fallback: busca marcas conocidas en las primeras 400 chars del texto
    return extraer_comercio(texto[:400])
