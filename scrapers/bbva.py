import re
import os
import io
import requests
import pdfplumber
from typing import List

from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto

# Regex para detectar precios o descuentos en el texto
_RE_A_SOLO = re.compile(r'a\s+solo\s+(S/[\d\.]+)', re.IGNORECASE)
_RE_PRECIO_REGULAR = re.compile(r'\(?precio\s+regular\s+(S/[\d\.]+)\)?', re.IGNORECASE)
_RE_FECHA = re.compile(r'(?:Del|Vigencia)[^\d]*([\d/]+)\s*al\s*([\d/]+)', re.IGNORECASE)
_RE_DESCUENTO = re.compile(r'(\d{1,3}%)\s*(?:de\s+)?(?:descuento|dscto\.?|dto\.?)', re.IGNORECASE)

class BBVAScraper(BaseScraper):
    nombre = "BBVA"
    url_base = "https://www.bbva.pe/personas/beneficios-y-promociones.html"
    local_pdf = "CatalogoDePromocionesLima.pdf"

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Iniciando scraping...")
        if os.path.exists(self.local_pdf):
            print(f"[{self.nombre}] Archivo local encontrado: {self.local_pdf}")
            return self._parsear_pdf_local(self.local_pdf)
        else:
            print(f"[{self.nombre}] Archivo local no encontrado. Se necesita {self.local_pdf}")
            return []

    def _parsear_pdf_local(self, pdf_path: str) -> List[Promocion]:
        promociones: List[Promocion] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                print(f"[{self.nombre}] PDF con {len(pdf.pages)} páginas.")
                for i, page in enumerate(pdf.pages):
                    # Dividimos la pagina en dos columnas (izquierda y derecha)
                    left = page.crop((0, 0, page.width/2, page.height))
                    right = page.crop((page.width/2, 0, page.width, page.height))
                    
                    text_left = left.extract_text()
                    text_right = right.extract_text()
                    
                    if text_left:
                        promociones.extend(self._procesar_text_columna(text_left, pagina=i+1))
                    
                    if text_right:
                        promociones.extend(self._procesar_text_columna(text_right, pagina=i+1))

        except Exception as e:
            print(f"[{self.nombre}] Error al parsear PDF: {e}")
        
        print(f"[{self.nombre}] {len(promociones)} promociones encontradas en total.")
        return promociones

    def _procesar_text_columna(self, text: str, pagina: int) -> List[Promocion]:
        lineas = [l.strip() for l in text.split('\n') if l.strip()]
        
        promociones = []
        bloque_actual = []
        
        def guardar_bloque(bloque):
            if not bloque: return
            texto_completo = " ".join(bloque)
            
            # Buscar precio de promo (a solo S/...)
            m_solo = _RE_A_SOLO.search(texto_completo)
            precio = m_solo.group(1) if m_solo else ""
            
            # Si no hay precio "a solo", buscamos porcentaje
            tipo = ""
            if not precio:
                m_desc = _RE_DESCUENTO.search(texto_completo)
                if m_desc:
                    precio = m_desc.group(1)
                    tipo = "Descuento"
            else:
                tipo = "Precio Especial"
                
            m_reg = _RE_PRECIO_REGULAR.search(texto_completo)
            condiciones = f"Precio Regular: {m_reg.group(1)}" if m_reg else ""
            
            m_fecha = _RE_FECHA.search(texto_completo)
            fecha_inicio = m_fecha.group(1) if m_fecha else ""
            fecha_fin = m_fecha.group(2) if m_fecha else ""
            
            # Comercio: al ser un PDF visual, los logos no se extraen en texto.
            comercio = "Ver Logo (No Detectado)" 
            
            descripcion = texto_completo[:200]
            
            if precio or tipo == "Descuento":
                promo = Promocion(
                    fuente=self.nombre,
                    categoria="Beneficio Catálogo PDF",
                    titulo="Promoción BBVA",
                    descripcion=descripcion,
                    comercio=comercio,
                    precio=precio,
                    tipo=tipo,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    url=self.local_pdf,
                    stock="",
                    condiciones=f"Página {pagina}. {condiciones}".strip(),
                    imagen_url=""
                )
                promociones.append(promo)

        for linea in lineas:
            bloque_actual.append(linea)
            if _RE_FECHA.match(linea) or "(precio regular" in linea.lower():
                # Si matcheo 'precio regular', aguardamos una linea más por si es fecha
                if _RE_FECHA.match(linea):
                    guardar_bloque(bloque_actual)
                    bloque_actual = []
            
        if bloque_actual:
            guardar_bloque(bloque_actual)
            
        return promociones
