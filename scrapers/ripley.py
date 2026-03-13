"""
Scraper para Banco Ripley Perú  Promociones
URL: https://www.bancoripley.com.pe/promociones/default.html

Obtiene la data directamente desde su Firebase Realtime Database
para mayor estabilidad y rapidez, omitiendo Playwright.
"""
import requests
import re
from typing import List

from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto

_FIREBASE_URL = "https://cms-wl-prd.firebaseio.com/beneficios.json"
_DETAIL_BASE_URL = "https://www.bancoripley.com.pe/promociones/detalle-promocion.html"

_CAT_DISPLAY = {
    'restofans':       'RestoFans (Jueves)',
    'restaurantes':    'Restaurantes',
    'supermercados':   'Supermercados',
    'entretenimiento': 'Entretenimiento',
    'viajaydisfruta':  'Automotriz y Viajes',
    'mallaventura':    'Mall Aventura',
    'bienestar':       'Bienestar',
    'belleza':         'Belleza',
    'salud':           'Salud',
    'educacion':       'Educación',
    'hogar':           'Hogar',
    'moda':            'Moda'
}

_IGNORE_CATS = {'configBeneficios', 'tyc', 'pruebas'}

class RipleyScraper(BaseScraper):
    nombre   = "Banco Ripley"
    url_base = "https://www.bancoripley.com.pe/promociones/default.html"

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Consumiendo API Firebase...")
        promociones = []
        
        try:
            r = requests.get(_FIREBASE_URL, timeout=15)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            print(f"[{self.nombre}] Error al conectar con Firebase: {e}")
            return []

        for cat_key, cat_data in data.items():
            if cat_key in _IGNORE_CATS or not isinstance(cat_data, dict):
                continue
                
            items = cat_data.get('items', {})
            if not isinstance(items, dict):
                if isinstance(items, list):
                    items = {str(i): v for i, v in enumerate(items) if v}
                else:
                    continue

            categoria_display = _CAT_DISPLAY.get(cat_key, cat_key.capitalize())
            
            for promo_key, promo_data in items.items():
                if not isinstance(promo_data, dict):
                    continue
                    
                config = promo_data.get('config', {})
                if not config.get('active', False):
                    continue
                    
                promo = self._parsear_promo(cat_key, categoria_display, promo_key, promo_data)
                if promo:
                    promociones.append(promo)
                    
        print(f"[{self.nombre}] {len(promociones)} promociones activas encontradas.")
        return promociones

    def _parsear_promo(self, cat_key: str, categoria: str, promo_key: str, data: dict) -> 'Promocion | None':
        def get_val(field: str) -> str:
            val = data.get(field, {}).get('value', '')
            return str(val).strip() if val else ''

        comercio = get_val('nombreEmpresa')
        if not comercio:
            return None
            
        dcto_html = get_val('dctoCard1')
        dcto_clean = re.sub(r'<[^>]+>', ' ', dcto_html)
        dcto_clean = re.sub(r'\s+', ' ', dcto_clean).strip()
        
        descripcion = get_val('detalleDctoCard1')
        condiciones = get_val('legalBeneficio')
        img_url = get_val('imgCard1')
        
        link = get_val('cardLink1')
        if not link or 'bancoripley.cl' in link or not link.startswith('http'):
            link = f"{_DETAIL_BASE_URL}?{cat_key}={promo_key}"
            
        config = data.get('config', {})
        fecha_inicio = config.get('programar', {}).get('fechaInicioProgramacion', {}).get('value', '').split(' ')[0]
        fecha_fin = config.get('programar', {}).get('fechaFinProgramacion', {}).get('value', '').split(' ')[0]
        
        stock = ""
        m_stock = re.search(r'stock.*?([\d,\.]+)\s*(?:canjes|promociones|unidades|paquetes|platos|dsctos|descuentos)?', condiciones, re.IGNORECASE)
        if m_stock:
            stock = m_stock.group(0).strip()
            
        texto_full = f"{comercio} {dcto_clean} {descripcion}"
        precio, tipo = extraer_precio_tipo_de_texto(texto_full)
        tipo = tipo or 'Beneficio'
        
        titulo = f"{comercio}  {dcto_clean}" if dcto_clean else comercio
        
        return Promocion(
            fuente=self.nombre,
            categoria=categoria,
            titulo=titulo,
            descripcion=descripcion,
            comercio=comercio,
            precio=precio,
            tipo=tipo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            url=link,
            stock=stock,
            condiciones=condiciones,
            imagen_url=img_url
        )
