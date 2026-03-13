import re
import os
import fitz
from typing import List

from scrapers.base import BaseScraper
from scrapers.models import Promocion

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
            doc = fitz.open(pdf_path)
            print(f"[{self.nombre}] PDF con {len(doc)} paginas.")
            
            img_dir = "logos_bbva"
            os.makedirs(img_dir, exist_ok=True)
            
            for i, page in enumerate(doc):
                pagina = i + 1
                page_dict = page.get_text('dict')
                blocks = page_dict['blocks']
                col_width = page.rect.width / 2

                images = [b for b in blocks if b['type'] == 1]
                
                # Filter for texts, extract lines with coordinates
                lines_data = []
                for b in blocks:
                    if b['type'] == 0:
                        for l in b['lines']:
                            text = "".join([s['text'] for s in l['spans']]).strip()
                            if text:
                                x0, y0, x1, y1 = l['bbox']
                                lines_data.append({
                                    'text': text,
                                    'x_center': (x0 + x1) / 2,
                                    'y_top': y0,
                                    'bbox': l['bbox']
                                })
                
                # Split in columns
                left_lines = [l for l in lines_data if l['x_center'] < col_width]
                right_lines = [l for l in lines_data if l['x_center'] >= col_width]
                
                left_lines.sort(key=lambda x: x['y_top'])
                right_lines.sort(key=lambda x: x['y_top'])

                # Process columns
                promos_left = self._procesar_columna(left_lines, images, pagina, col_width, is_left=True, img_dir=img_dir)
                promos_right = self._procesar_columna(right_lines, images, pagina, col_width, is_left=False, img_dir=img_dir)

                promociones.extend(promos_left)
                promociones.extend(promos_right)
                
        except Exception as e:
            print(f"[{self.nombre}] Error al parsear PDF: {e}")

        print(f"[{self.nombre}] {len(promociones)} promociones encontradas en total.")
        return promociones

    def _procesar_columna(self, lines, images, pagina, col_width, is_left, img_dir) -> List[Promocion]:
        promociones = []
        bloque_actual = []
        imagen_actual_path = ""

        # Function to find the nearest image above a given Y
        def find_closest_image(y_top):
            closest_img = None
            min_dist = float('inf')
            
            for index, img in enumerate(images):
                img_bottom = img['bbox'][3]
                img_width = img['bbox'][2] - img['bbox'][0]
                img_center = (img['bbox'][0] + img['bbox'][2]) / 2
                
                # Consider it valid if it's full width banner (spread across colums)
                # or if it's explicitly in our column
                is_banner = img_width > (col_width * 1.5)
                same_col = (is_left and img_center < col_width) or (not is_left and img_center >= col_width)
                
                if (is_banner or same_col) and img_bottom <= y_top + 15: # small tolerance
                    dist = y_top - img_bottom
                    if dist < min_dist:
                        min_dist = dist
                        closest_img = img
            return closest_img

        def guardar_bloque(bloque, current_img_path):
            if not bloque: return
            texto_completo = " ".join([l['text'] for l in bloque])
            texto_completo = re.sub(r'[\x00-\x1f]', '', texto_completo)

            # Buscar precio de promo
            m_solo = _RE_A_SOLO.search(texto_completo)
            precio = m_solo.group(1) if m_solo else ""

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

            # Para titulo, limpiamos todo y usamos las primeras palabras representativas
            titulo = bloque[0]["text"] # The first line is usually the title or item
            if len(titulo) < 10 and len(bloque) > 1:
                titulo += " " + bloque[1]["text"]
            titulo = re.sub(r'[\x00-\x1f]', '', titulo)
            
            descripcion = re.sub(r"\s+", " ", texto_completo[:250]).strip()

            if precio or tipo == "Descuento":
                promo = Promocion(
                    fuente=self.nombre,
                    categoria="Beneficio Catalogo PDF",
                    titulo=titulo.replace("\n", " ").strip(),
                    descripcion=descripcion,
                    comercio="Logo (Ver Imagen)", # No detectamos OCR, mapeamos imagen
                    precio=precio,
                    tipo=tipo,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    url=self.local_pdf,
                    stock="Ver detalles en PDF",
                    condiciones=f"Pagina {pagina}. {condiciones}".strip(),
                    imagen_url=current_img_path or ""
                )
                promociones.append(promo)

        for l in lines:
            line_text = l['text']
            
            # Asociar imagen actual
            img_dict = find_closest_image(l['y_top'])
            if img_dict:
                # Save the image if we haven't
                idx = images.index(img_dict)
                ext = img_dict.get('ext', 'png') # fall back to png
                img_path = os.path.join(img_dir, f"logo_p{pagina}_img{idx}.{ext}")
                
                # Para evitar doble match / errores, creamos carpeta local
                if not os.path.exists(img_path) and 'image' in img_dict:
                    with open(img_path, "wb") as f:
                        f.write(img_dict['image'])
                        
                # Update current image context path
                imagen_actual_path = img_path
            
            bloque_actual.append(l)
            
            if _RE_FECHA.match(line_text) or "(precio regular" in line_text.lower():
                # End of a promotion block
                if _RE_FECHA.match(line_text):
                    guardar_bloque(bloque_actual, imagen_actual_path)
                    bloque_actual = []

        if bloque_actual:
            guardar_bloque(bloque_actual, imagen_actual_path)

        return promociones
