import re
import os
import fitz
from typing import List, Optional

from scrapers.base import BaseScraper
from scrapers.models import Promocion

# Regex para detectar precios o descuentos en el texto
_RE_A_SOLO = re.compile(r'a\s+solo\s+(S/[\d\.]+)', re.IGNORECASE)
_RE_PRECIO_REGULAR = re.compile(r'\(?precio\s+regular\s+(S/[\d\.]+)\)?', re.IGNORECASE)
_RE_FECHA = re.compile(r'(?:Del|Vigencia)[^\d]*([\d/]+)\s*al\s*([\d/]+)', re.IGNORECASE)

# Regex mejorados para detectar descuentos variados
_RE_DESCUENTO_SIMPLE = re.compile(r'(\d{1,3}%)\s*(?:de\s+)?(?:descuento|desct\.?|dscto\.?|dto\.?)', re.IGNORECASE)
_RE_DESCUENTO_HASTA = re.compile(r'Hasta\s+(\d{1,3}%)\s*(?:de\s+)?(?:descuento|desct\.?|dscto\.?|dto\.?)', re.IGNORECASE)
_RE_DESCUENTO_CANTIDAD = re.compile(r'(S/[\d\.]+)\s+(?:de\s+)?(?:descuento|desct\.?|dscto\.?|dto\.?)', re.IGNORECASE)
_RE_DESCUENTO_EN = re.compile(r'(\d{1,3}%)\s+(?:de\s+)?desc(?:uento|t\.?|to\.?)\s+(?:en|en la|en toda)', re.IGNORECASE)

# Regex para detectar promociones especiales (combos, 2x1, etc)
_RE_COMBO = re.compile(r'\d+x\d+|combo|pack|oferta|promoción|promo', re.IGNORECASE)
_RE_2X1 = re.compile(r'2x1|compra\s+2', re.IGNORECASE)

# Regex para detectar nombres de comercios
_RE_COMERCIO_FUENTE = re.compile(r'(?:Del|Válido|Valid|Require)[^\d]*', re.IGNORECASE)
_RE_CATEGORIA_VENTA = re.compile(r'(?:Pagos\s+Sin\s+Intereses|PSI|Puntos|pago)', re.IGNORECASE)

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
        """Parsea el PDF local de BBVA optimizado para la estructura de catálogo de beneficios"""
        promociones: List[Promocion] = []
        try:
            doc = fitz.open(pdf_path)
            print(f"[{self.nombre}] PDF con {len(doc)} páginas.")
            
            img_dir = "logos_bbva"
            os.makedirs(img_dir, exist_ok=True)
            
            # Saltamos páginas de índice (1-2) y comenzamos con contenido (3 en adelante)
            for page_idx in range(doc.page_count):
                pagina = page_idx + 1
                
                # Skip índice pages
                if pagina <= 2:
                    continue
                    
                page = doc[page_idx]
                promos_page = self._procesar_pagina_bbva(page, pagina, img_dir)
                promociones.extend(promos_page)
                
        except Exception as e:
            print(f"[{self.nombre}] Error al parsear PDF: {e}")
            import traceback
            traceback.print_exc()

        print(f"[{self.nombre}] {len(promociones)} promociones encontradas en total.")
        return promociones

    def _procesar_pagina_bbva(self, page, pagina: int, img_dir: str) -> List[Promocion]:
        """Procesa una página del catálogo BBVA"""
        promociones = []
        
        try:
            page_dict = page.get_text('dict')
            blocks = page_dict['blocks']
            
            # Extraer imágenes (logos)
            imagenes_data = self._extraer_imagenes(blocks, page, pagina, img_dir)
            
            # Extraer líneas de texto con coordenadas
            lineas_data = self._extraer_lineas(blocks)
            
            # Procesar bloques de promoción basados en la estructura visual
            promos = self._agrupar_y_procesar_promociones(lineas_data, imagenes_data, pagina, img_dir)
            
            promociones.extend(promos)
            
        except Exception as e:
            print(f"[{self.nombre}] Error procesando página {pagina}: {e}")
            
        return promociones

    def _extraer_imagenes(self, blocks, page, pagina: int, img_dir: str) -> List[dict]:
        """Extrae información de imágenes (logos) del PDF"""
        imagenes_data = []
        
        for idx, block in enumerate(blocks):
            if block.get('type') == 1:  # Image block
                try:
                    bbox = block.get('bbox', (0, 0, 0, 0))
                    
                    # Intentar extraer la imagen
                    if 'image' in block:
                        img_bytes = block['image']
                        ext = block.get('ext', 'png')
                        img_path = os.path.join(img_dir, f"logo_p{pagina}_img{idx}.{ext}")
                        
                        # Guardar imagen
                        if not os.path.exists(img_path):
                            with open(img_path, "wb") as f:
                                f.write(img_bytes)
                        
                        imagenes_data.append({
                            'bbox': bbox,
                            'path': img_path,
                            'index': idx
                        })
                except Exception as e:
                    print(f"[{self.nombre}] Error extrayendo imagen {idx}: {e}")
                    
        return imagenes_data

    def _extraer_lineas(self, blocks) -> List[dict]:
        """Extrae líneas de texto con coordenadas"""
        lineas_data = []
        
        for block in blocks:
            if block.get('type') == 0:  # Text block
                for line in block.get('lines', []):
                    text = "".join([span.get('text', '') for span in line.get('spans', [])]).strip()
                    if text:
                        bbox = line.get('bbox', (0, 0, 0, 0))
                        lineas_data.append({
                            'text': text,
                            'x0': bbox[0],
                            'y0': bbox[1],
                            'x1': bbox[2],
                            'y1': bbox[3],
                            'x_center': (bbox[0] + bbox[2]) / 2,
                            'y_center': (bbox[1] + bbox[3]) / 2,
                            'height': bbox[3] - bbox[1]
                        })
        
        # Ordenar por posición vertical (de arriba a abajo)
        lineas_data.sort(key=lambda x: x['y0'])
        return lineas_data

    def _agrupar_y_procesar_promociones(self, lineas_data: List[dict], imagenes_data: List[dict], 
                                        pagina: int, img_dir: str) -> List[Promocion]:
        """Agrupa líneas en bloques de promoción y los procesa"""
        promociones = []
        
        if not lineas_data:
            return promociones
        
        # Estrategia: buscar líneas de fecha como separadores de promociones
        bloques_promo = []
        bloque_actual = []
        
        for i, linea in enumerate(lineas_data):
            bloque_actual.append(linea)
            
            # Una fecha indica el final de una promoción
            if _RE_FECHA.search(linea['text']):
                if len(bloque_actual) > 0:
                    bloques_promo.append(bloque_actual)
                bloque_actual = []
        
        # Añadir el último bloque si existe
        if bloque_actual:
            bloques_promo.append(bloque_actual)
        
        # Procesar cada bloque de promoción
        for bloque in bloques_promo:
            try:
                promo = self._extraer_promocion_de_bloque(bloque, pagina, imagenes_data, img_dir)
                if promo:
                    promociones.append(promo)
            except Exception as e:
                print(f"[{self.nombre}] Error extrayendo promoción: {e}")
        
        return promociones

    def _extraer_promocion_de_bloque(self, bloque: List[dict], pagina: int, 
                                     imagenes_data: List[dict], img_dir: str) -> Optional[Promocion]:
        """Extrae una promoción de un bloque de líneas"""
        if not bloque:
            return None
        
        # Construir texto completo
        texto_completo = " ".join([l['text'] for l in bloque])
        texto_completo = re.sub(r'[\x00-\x1f]', '', texto_completo)
        
        # Intentar obtener el comercio (generalmente primera línea o línea con mayúsculas)
        comercio = self._extraer_comercio_del_bloque(bloque)
        
        # Extraer el tipo y monto de descuento/promoción
        precio, tipo = self._extraer_precio_y_tipo(texto_completo)
        
        # Extraer fechas
        fecha_inicio, fecha_fin = self._extraer_fechas(texto_completo)
        
        # Si no hay precio o descuento detectado, no es una promoción válida
        if not precio and tipo != "Descuento":
            return None
        
        # Extraer descripción (primeras 250 caracteres limpios)
        descripcion = re.sub(r"\s+", " ", texto_completo[:300]).strip()
        
        # Buscar imagen cercana
        imagen_url = self._buscar_imagen_cercana(bloque[0], imagenes_data)
        
        # Obtener categoría según el contexto
        categoria = self._determinar_categoria(texto_completo)
        
        promo = Promocion(
            fuente=self.nombre,
            categoria=categoria,
            titulo=comercio if comercio else bloque[0]['text'],
            descripcion=descripcion,
            comercio=comercio if comercio else "BBVA",
            precio=precio,
            tipo=tipo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            url=self.local_pdf,
            stock="Válido según catálogo",
            condiciones=f"Página {pagina}",
            imagen_url=imagen_url or ""
        )
        
        return promo

    def _extraer_comercio_del_bloque(self, bloque: List[dict]) -> str:
        """Extrae el nombre del comercio de un bloque"""
        # Buscar línea con muchas mayúsculas o que sea muy corta (típicamente nombre de comercio)
        for linea in bloque[:3]:  # Revisar primeras 3 líneas
            texto = linea['text'].strip()
            if len(texto) < 50 and len(texto) > 2:
                # Contar mayúsculas
                mayus = sum(1 for c in texto if c.isupper())
                if mayus / len(texto) > 0.5 or texto.isupper():
                    return texto
        
        return ""

    def _extraer_precio_y_tipo(self, texto: str) -> tuple:
        """Extrae el precio/descuento y su tipo"""
        precio = ""
        tipo = ""
        
        # Buscar "a solo S/XXX"
        m = _RE_A_SOLO.search(texto)
        if m:
            precio = m.group(1)
            tipo = "Precio Especial"
            return precio, tipo
        
        # Buscar "Hasta X% de descuento"
        m = _RE_DESCUENTO_HASTA.search(texto)
        if m:
            precio = f"Hasta {m.group(1)} descuento"
            tipo = "Descuento"
            return precio, tipo
        
        # Buscar "X% de descuento/desct."
        m = _RE_DESCUENTO_EN.search(texto)
        if m:
            precio = f"{m.group(1)} descuento"
            tipo = "Descuento"
            return precio, tipo
        
        # Buscar "X% de desct." (simple)
        m = _RE_DESCUENTO_SIMPLE.search(texto)
        if m:
            precio = f"{m.group(1)} descuento"
            tipo = "Descuento"
            return precio, tipo
        
        # Buscar "S/X de descuento"
        m = _RE_DESCUENTO_CANTIDAD.search(texto)
        if m:
            precio = f"{m.group(1)} descuento"
            tipo = "Descuento por Cantidad"
            return precio, tipo
        
        # Buscar 2x1
        if _RE_2X1.search(texto):
            precio = "2x1"
            tipo = "Promoción Especial"
            return precio, tipo
        
        # Buscar otros combos
        if _RE_COMBO.search(texto):
            precio = "Combo/Oferta"
            tipo = "Promoción Especial"
            return precio, tipo
        
        return precio, tipo

    def _extraer_fechas(self, texto: str) -> tuple:
        """Extrae fechas de inicio y fin"""
        m = _RE_FECHA.search(texto)
        if m:
            fecha_inicio = m.group(1)
            fecha_fin = m.group(2)
            return fecha_inicio, fecha_fin
        
        return "", ""

    def _buscar_imagen_cercana(self, linea: dict, imagenes_data: List[dict]) -> str:
        """Busca la imagen más cercana a una línea"""
        if not imagenes_data:
            return ""
        
        linea_y = linea['y0']
        imagen_mas_cercana = None
        min_dist = float('inf')
        
        for img in imagenes_data:
            img_bbox = img['bbox']
            img_y_bottom = img_bbox[3]
            
            # La imagen debe estar antes (arriba) de la línea
            if img_y_bottom <= linea_y + 50:  # tolerancia
                dist = linea_y - img_y_bottom
                if dist < min_dist:
                    min_dist = dist
                    imagen_mas_cercana = img
        
        return imagen_mas_cercana['path'] if imagen_mas_cercana else ""

    def _determinar_categoria(self, texto: str) -> str:
        """Determina la categoría de la promoción según el contenido"""
        texto_lower = texto.lower()
        
        if any(word in texto_lower for word in ['restaurante', 'comida', 'café', 'pizza', 'pollo', 'bebida']):
            return "Restaurantes y Alimentos"
        elif any(word in texto_lower for word in ['hotel', 'hospedaje', 'alojamiento', 'viaje', 'tour', 'vuelo']):
            return "Viajes y Experiencias"
        elif any(word in texto_lower for word in ['concierto', 'entrada', 'evento', 'show', 'música']):
            return "Conciertos y Eventos"
        elif any(word in texto_lower for word in ['salud', 'médico', 'dental', 'doctor', 'clínica', 'belleza']):
            return "Salud y Belleza"
        elif any(word in texto_lower for word in ['ropa', 'zapato', 'bolso', 'moda', 'accesor']):
            return "Moda y Accesorios"
        elif any(word in texto_lower for word in ['supermercado', 'flores', 'florist']):
            return "Supermercados y Florería"
        elif any(word in texto_lower for word in ['tecnología', 'celular', 'computadora', 'electrónico']):
            return "Tecnología"
        elif any(word in texto_lower for word in ['educación', 'curso', 'clase', 'programa']):
            return "Educación"
        else:
            return "Beneficio Catálogo BBVA"

