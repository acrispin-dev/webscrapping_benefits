"""
Scraper para OH Beneficios (SIP)
URL: https://beneficios.sip.pe

Extrae promociones de todas las categorías:
- Restaurantes
- Fast Food  
- Moda y belleza
- Entretenimiento
- Transporte y Automotriz
- Viajes
- Educación
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from scrapers.models import Promocion
from scrapers.utils import extraer_precio_tipo_de_texto, extraer_comercio
import time
import re
from typing import List

class OhScraper(BaseScraper):
    nombre = "OH"
    url_base = "https://beneficios.sip.pe"
    
    # URLs de cada categoría
    CATEGORIAS = {
        "Restaurantes": "/promociones-y-descuentos/restaurantes-view",
        "Fast Food": "/promociones-y-descuentos/fast-food",
        "Moda y belleza": "/promociones-y-descuentos/moda-belleza",
        "Entretenimiento": "/promociones-y-descuentos/entretenimiento",
        "Transporte y Automotriz": "/promociones-y-descuentos/transporte-automotriz",
        "Viajes": "/promociones-y-descuentos/viajes",
        "Educación": "/promociones-y-descuentos/educacion",
        "Salud": "/promociones-y-descuentos/salud",
        "Mascotas": "/promociones-y-descuentos/mascotas",
        "Otros": "/promociones-y-descuentos/otros",
    }

    def scrape(self) -> List[Promocion]:
        print(f"[{self.nombre}] Iniciando scraping de todas las categorías...")
        all_promociones = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            for categoria, url_path in self.CATEGORIAS.items():
                try:
                    print(f"[{self.nombre}] Cargando categoría: {categoria}...")
                    url = self.url_base + url_path
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)
                    
                    # Aceptar cookies automáticamente
                    self._aceptar_cookies(page)
                    
                    # Hacer scroll y click en botones "Ver Más"
                    self._cargar_todas_promociones(page)
                    
                    html = page.content()
                    promos_categoria = self._parsear(html, categoria, page)
                    print(f"[{self.nombre}] {len(promos_categoria)} promociones encontradas en {categoria}")
                    all_promociones.extend(promos_categoria)
                    
                except Exception as e:
                    print(f"[{self.nombre}] Error en categoría {categoria}: {e}")
                    continue
            
            context.close()
            browser.close()
        
        print(f"[{self.nombre}] Total: {len(all_promociones)} promociones encontradas.")
        return all_promociones

    def _aceptar_cookies(self, page):
        """Intenta aceptar cookies automáticamente"""
        try:
            # Buscar botón de aceptar cookies por diferentes selectores
            selectors = [
                'button:has-text("Aceptar")',
                'button:has-text("Accept")',
                '[class*="cookie"] button',
                'button[data-action="accept"]',
                'button.accept-cookies',
                'button:contains("Aceptar")',
            ]
            
            for selector in selectors:
                try:
                    button = page.locator(selector).first
                    if button.is_visible():
                        print(f"[{self.nombre}] Aceptando cookies...")
                        button.click(timeout=5000)
                        time.sleep(1)
                        return
                except:
                    continue
            
            # Si no encontró botón específico, intenta click en cualquier botón visible con "Aceptar"
            buttons = page.locator('button')
            for i in range(buttons.count()):
                btn = buttons.nth(i)
                if btn.is_visible():
                    text = btn.inner_text()
                    if "aceptar" in text.lower() or "accept" in text.lower():
                        btn.click(timeout=5000)
                        time.sleep(1)
                        return
        except Exception as e:
            print(f"[{self.nombre}] No se pudo aceptar cookies (puede que no exista): {e}")

    def _cargar_todas_promociones(self, page):
        """Scroll completo y hace click en botones 'Ver Más' para cargar todas las promociones"""
        intentos = 0
        max_intentos = 50
        ultima_altura = 0
        
        while intentos < max_intentos:
            try:
                # Scroll hacia abajo
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)
                
                nueva_altura = page.evaluate("document.body.scrollHeight")
                
                # Si no hay cambio de altura, intentar hacer click en "Ver Más"
                if nueva_altura == ultima_altura:
                    if self._hacer_click_ver_mas(page):
                        print(f"[{self.nombre}] Click en 'Ver Más', continuando carga...")
                        time.sleep(2)
                        # Actualizar altura después del click
                        ultima_altura = page.evaluate("document.body.scrollHeight")
                        intentos = 0  # Resetear contador
                        continue
                    else:
                        # No hay más botones "Ver Más", salir
                        print(f"[{self.nombre}] Todas las promociones cargadas")
                        break
                
                ultima_altura = nueva_altura
                intentos += 1
                
            except Exception as e:
                print(f"[{self.nombre}] Error durante carga: {e}")
                break

    def _hacer_click_ver_mas(self, page) -> bool:
        """
        Busca y hace click en botón 'Ver Más'
        Retorna True si encontró y clickeó, False si no hay más
        """
        try:
            # Selectores posibles para botones "Ver Más"
            selectors = [
                'button:has-text("Ver más")',
                'button:has-text("Load more")',
                '[class*="load-more"] button',
                '[class*="ver-mas"] button',
                'button[class*="pagination"]',
                'a:has-text("Ver más")',
                'button:text("Ver más")',
            ]
            
            for selector in selectors:
                try:
                    button = page.locator(selector).first
                    if button.is_visible():
                        print(f"[{self.nombre}] Encontrado botón 'Ver más', haciendo click...")
                        button.click(timeout=5000)
                        return True
                except:
                    continue
            
            # Alternativa: buscar por texto en todos los botones
            buttons = page.locator('button, a')
            for i in range(buttons.count()):
                btn = buttons.nth(i)
                try:
                    if btn.is_visible():
                        text = btn.inner_text().lower()
                        if "ver más" in text or "load more" in text or "cargar más" in text:
                            print(f"[{self.nombre}] Encontrado botón 'Ver más' con texto: {text}")
                            btn.click(timeout=5000)
                            return True
                except:
                    continue
            
            return False
        except Exception as e:
            print(f"[{self.nombre}] Error buscando botón 'Ver más': {e}")
            return False

    def _parsear(self, html: str, categoria: str, page=None) -> List[Promocion]:
        soup = BeautifulSoup(html, "lxml")
        promociones = []
        
        # Buscar específicamente las tarjetas de promociones (oh-card-promotion)
        cards = soup.select('oh-card-promotion div.card-promotion')
        
        # PASO 1: Extraer primero todos los datos de las tarjetas
        tarjetas_data = []
        seen = set()
        
        for card in cards:
            try:
                # Obtener el contenedor principal de la tarjeta (que tiene el enlace)
                link_elem = card.select_one('a.card-promotion__card')
                if not link_elem:
                    continue
                
                # Extraer URL del href
                enlace = link_elem.get('href', '')
                if enlace and not enlace.startswith('http'):
                    enlace = self.url_base + enlace
                
                # Extraer el precio/descuento del elemento <p class="oh-text-title-lg">
                precio_elem = card.select_one('p.oh-text-title-lg')
                precio_raw = precio_elem.get_text(strip=True) if precio_elem else ""
                
                # Extraer tipo basado en el contenido ORIGINAL (antes de limpiar)
                tipo = self._determinar_tipo(precio_raw)
                
                # Limpiar y normalizar precio_dto
                precio_dto = self._limpiar_precio_dto(precio_raw)
                
                # Extraer comercio (del elemento p.oh-text-title-md)
                comercio_elem = card.select_one('p.oh-text-title-md')
                comercio = comercio_elem.get_text(strip=True) if comercio_elem else ""
                
                # Extraer título (del elemento h2.oh-text-body-md)
                titulo_elem = card.select_one('h2.oh-text-body-md')
                titulo = titulo_elem.get_text(strip=True) if titulo_elem else ""
                
                # Extraer imagen
                img_elem = card.select_one('img.card-promotion__image__img')
                imagen_url = img_elem.get('src', '') if img_elem else ""
                
                # Extraer descripción (alt del imagen o primeras palabras de título)
                descripcion = titulo if titulo else comercio
                
                # Crear clave única para evitar duplicados
                clave_unica = f"{comercio}_{titulo}_{precio_dto}"
                if clave_unica in seen:
                    continue
                seen.add(clave_unica)
                
                # Solo agregar si tenemos los campos necesarios
                if comercio and titulo and precio_dto:
                    tarjetas_data.append({
                        'enlace': enlace,
                        'titulo': titulo,
                        'descripcion': descripcion,
                        'comercio': comercio,
                        'precio': precio_dto,
                        'tipo': tipo,
                        'imagen_url': imagen_url,
                    })
            except Exception as e:
                print(f"[{self.nombre}] Error procesando tarjeta: {e}")
                continue
        
        # PASO 2: Para cada tarjeta, navegar directamente a su href extraído
        for tarjeta in tarjetas_data:
            try:
                fecha_inicio = ""
                fecha_fin = ""
                stock = ""
                promocion_detalle = tarjeta['titulo']
                comercio_detalle = tarjeta['comercio']
                
                print(f"[{self.nombre}] Comercio de tarjeta original: {comercio_detalle}")
                
                if page and tarjeta['enlace']:
                    print(f"[{self.nombre}] Extrayendo detalles de {tarjeta['titulo']}...")
                    fecha_inicio, fecha_fin, stock, promocion_det, comercio_det = self._extraer_detalles_promo(page, tarjeta['enlace'])
                    
                    # Usar valores extraídos de la página de detalle si están disponibles
                    if promocion_det:
                        promocion_detalle = promocion_det
                    if comercio_det:
                        comercio_detalle = comercio_det
                        print(f"[{self.nombre}] Comercio actualizado del detalle: {comercio_det}")
                
                promociones.append(Promocion(
                    fuente=self.nombre,
                    categoria=categoria,
                    titulo=promocion_detalle,
                    descripcion=promocion_detalle,
                    comercio=comercio_detalle,
                    precio=tarjeta['precio'],
                    tipo=tarjeta['tipo'],
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    stock=stock,
                    url=tarjeta['enlace'],
                    imagen_url=tarjeta['imagen_url'],
                ))
            except Exception as e:
                print(f"[{self.nombre}] Error en promoción {tarjeta.get('titulo', 'desconocida')}: {e}")
                continue
        
        return promociones
    
    def _limpiar_precio_dto(self, precio_text: str) -> str:
        """Limpia el texto de precio, extrayendo solo número (sin símbolos extras)"""
        if not precio_text:
            return ""
        
        precio_text = precio_text.strip()
        
        # Si contiene %, extraer solo el número (sin %)
        if "%" in precio_text:
            # Extrae solo dígitos del texto
            match = re.search(r'(\d+)', precio_text)
            if match:
                return match.group(1)  # Retorna solo el número, HTML agrega %
        
        # Si contiene S/, extraer el número con S/
        if "S/" in precio_text:
            match = re.search(r'S/\s*([\d.,]+)', precio_text)
            if match:
                return "S/ " + match.group(1)  # Formato consistente con utils
        
        return precio_text
    
    def _determinar_tipo(self, precio_text: str) -> str:
        """Determina el tipo de promoción basado en el texto de precio"""
        precio_text = precio_text.upper() if precio_text else ""
        
        if "%" in precio_text:
            return "% Descuento"
        elif "S/" in precio_text:
            return "Precio promo"
        else:
            return "Beneficio"
    
    def _extraer_detalles_promo(self, page, url: str) -> tuple:
        """
        Navega directamente al URL de una promoción usando el href extraído y 
        extrae información detallada de la página de promoción.
        Retorna (fecha_inicio, fecha_fin, stock, promocion, comercio)
        """
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # ESPERAR a que el contenido Angular se renderice
            # Esperar a que aparezca el título principal (h1.oh-text-headline-md)
            try:
                page.wait_for_selector('h1.oh-text-headline-md', timeout=5000)
            except:
                print(f"[{self.nombre}] Timeout esperando h1.oh-text-headline-md, continuando...")
                pass
            
            time.sleep(1.5)  # Esperar 1.5 segundos adicionales para que cargue completamente la página
            
            html = page.content()
            soup = BeautifulSoup(html, "lxml")
            
            # Inicializar variables
            fecha_inicio = ""
            fecha_fin = ""
            stock = ""
            promocion = ""
            comercio = ""
            
            # EXTRACTOR 1: Comercio desde <h2 class="oh-text-body-lg">
            comercio_elem = soup.select_one('h2.oh-text-body-lg')
            if comercio_elem:
                comercio = comercio_elem.get_text(strip=True)
                print(f"[{self.nombre}] Comercio encontrado (h2): {comercio}")
            else:
                # Intenta alternativas si h2 no funciona
                # Buscar en promotion__details o cualquier otro contenedor
                for selector in ['div.promotion__details h2', 'div.promotion__content h2', '[class*="business"] h2', 'h2']:
                    elem = soup.select_one(selector)
                    if elem:
                        text = elem.get_text(strip=True)
                        if text and len(text) > 0:
                            comercio = text
                            print(f"[{self.nombre}] Comercio encontrado ({selector}): {comercio}")
                            break
                
                if not comercio:
                    print(f"[{self.nombre}] No se encontró h2.oh-text-body-lg (intentará alternativas)")
                    # Como último recurso, buscar en parte del alt de la imagen del comercio
                    img_alt = soup.select_one('img[src*="Comercio"]')
                    if img_alt:
                        alt_text = img_alt.get('alt', '')
                        if alt_text:
                            comercio = alt_text
                            print(f"[{self.nombre}] Comercio desde imagen alt: {comercio}")
            
            # EXTRACTOR 2: Promoción desde <h1 class="oh-text-headline-md">
            promocion_elem = soup.select_one('h1.oh-text-headline-md')
            if promocion_elem:
                promocion = promocion_elem.get_text(strip=True)
                print(f"[{self.nombre}] Promoción encontrada: {promocion}")
            else:
                print(f"[{self.nombre}] No se encontró h1.oh-text-headline-md")
            
            # EXTRACTOR 3: Vigencia desde <div class="promotion__characteristics">
            # Buscamos específicamente el tag con "Vigencia"
            vigencia_div = soup.select_one('div.promotion__characteristics')
            if vigencia_div:
                print(f"[{self.nombre}] promotion__characteristics encontrado")
                # Buscar dentro de este div el subtitle que contiene las fechas
                caracteristicas = vigencia_div.select('div.promotion__characteristics__content')
                print(f"[{self.nombre}] Características encontradas: {len(caracteristicas)}")
                
                for i, caracteristica in enumerate(caracteristicas):
                    titulo = caracteristica.select_one('p.promotion__characteristics__title')
                    if titulo:
                        titulo_text = titulo.get_text(strip=True)
                        print(f"[{self.nombre}] Característica {i}: {titulo_text}")
                        
                        if "Vigencia" in titulo_text:
                            subtitle = caracteristica.select_one('p.promotion__characteristics__subtitle')
                            if subtitle:
                                texto_vigencia = subtitle.get_text(strip=True)
                                print(f"[{self.nombre}] Texto vigencia: {texto_vigencia}")
                                # Patrón para extraer fechas (DD de mes/número)
                                # Buscar formato: "Válido desde el 01 enero, hasta el 30 de junio de 2026"
                                # o "desde el...hasta el"
                                
                                # Primero intentar extraer fechas numéricas DD/MM/YYYY
                                patron_numerico = r'(\d{1,2})/(\d{1,2})/(\d{4})'
                                fechas_numericas = re.findall(patron_numerico, texto_vigencia)
                                print(f"[{self.nombre}] Fechas numéricas encontradas: {fechas_numericas}")
                                
                                if len(fechas_numericas) >= 2:
                                    fecha_inicio = f"{fechas_numericas[0][0]}/{fechas_numericas[0][1]}/{fechas_numericas[0][2]}"
                                    fecha_fin = f"{fechas_numericas[-1][0]}/{fechas_numericas[-1][1]}/{fechas_numericas[-1][2]}"
                                elif len(fechas_numericas) == 1:
                                    fecha_fin = f"{fechas_numericas[0][0]}/{fechas_numericas[0][1]}/{fechas_numericas[0][2]}"
                                
                                # Si no encontramos fechas numéricas, extraer en formato texto
                                # Patrón para "Válido desde el DD de mes, hasta el DD de mes de YYYY"
                                # Este patrón captura: "01 enero" "30 junio" "2026"
                                patron_texto = r'desde\s+el\s+(\d{1,2})\s+de\s+(\w+),?\s+(?:hasta\s+)?el\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})'
                                match_texto = re.search(patron_texto, texto_vigencia, re.IGNORECASE | re.DOTALL)
                                
                                if not fecha_inicio or not fecha_fin:
                                    if match_texto:
                                        print(f"[{self.nombre}] Match encontrado: {match_texto.groups()}")
                                        dia_inicio, mes_inicio, dia_fin, mes_fin, year = match_texto.groups()
                                        # Convertir nombres de mes a números
                                        meses = {
                                            'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
                                            'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
                                            'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
                                        }
                                        mes_inicio_num = meses.get(mes_inicio.lower(), '')
                                        mes_fin_num = meses.get(mes_fin.lower(), '')
                                        
                                        if mes_inicio_num and mes_fin_num:
                                            fecha_inicio = f"{dia_inicio.zfill(2)}/{mes_inicio_num}/{year}"
                                            fecha_fin = f"{dia_fin.zfill(2)}/{mes_fin_num}/{year}"
                                            print(f"[{self.nombre}] Fechas extraídas en formato texto: {fecha_inicio} - {fecha_fin}")
                                    else:
                                        print(f"[{self.nombre}] No match para patrón de texto. Buscando alternativas...")
                                        # Intenta pattern alternativo:  "01 enero y 30 de junio" o variaciones
                                        patron_alt = r'(\d{1,2})\s+(?:de\s+)?(\w+).*?(\d{1,2})\s+(?:de\s+)?(\w+)\s+(?:de\s+)?(\d{4})'
                                        match_alt = re.search(patron_alt, texto_vigencia, re.IGNORECASE | re.DOTALL)
                                        if match_alt:
                                            dia_inicio, mes_inicio, dia_fin, mes_fin, year = match_alt.groups()
                                            meses = {
                                                'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
                                                'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
                                                'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
                                            }
                                            mes_inicio_num = meses.get(mes_inicio.lower(), '')
                                            mes_fin_num = meses.get(mes_fin.lower(), '')
                                            if mes_inicio_num and mes_fin_num:
                                                fecha_inicio = f"{dia_inicio.zfill(2)}/{mes_inicio_num}/{year}"
                                                fecha_fin = f"{dia_fin.zfill(2)}/{mes_fin_num}/{year}"
                                                print(f"[{self.nombre}] Fechas extraídas (patrón alt): {fecha_inicio} - {fecha_fin}")
                            else:
                                print(f"[{self.nombre}] No se encontró subtitle en vigencia")
            else:
                print(f"[{self.nombre}] No se encontró div.promotion__characteristics")
            
            # EXTRACTOR 4: Stock desde expansion-item o características
            # Buscar en todo el contenido de texto de la página
            texto_completo = soup.get_text()
            
            # Patrón para stock: "Stock: Máximo 1,000 promociones" o variaciones
            # Buscar las variaciones más comunes
            patron_stock = r'(?:stock|máximo|promociones|cantidades|unidades|disponibles|cupos|canjes)[\s:]*(\d{1,5}(?:[.,]\d{3})*)'
            match_stock = re.search(patron_stock, texto_completo, re.IGNORECASE)
            if match_stock:
                stock_raw = match_stock.group(1)
                # Limpiar formato (remover separadores de miles)
                stock = re.sub(r'[,.\s]', '', stock_raw)
                print(f"[{self.nombre}] Stock encontrado: {stock}")
            else:
                print(f"[{self.nombre}] No se encontró stock")
            
            print(f"[{self.nombre}] Detalles extraídos: Comercio={comercio}, Fecha Inicio={fecha_inicio}, Fecha Fin={fecha_fin}, Stock={stock}")
            
            # Volver a la página anterior
            page.go_back(timeout=10000)
            time.sleep(0.5)
            
            return fecha_inicio, fecha_fin, stock, promocion, comercio
            
        except Exception as e:
            print(f"[{self.nombre}] Error extrayendo detalles: {e}")
            import traceback
            traceback.print_exc()
            # Intentar volver aunque haya error
            try:
                page.go_back(timeout=5000)
            except:
                pass
            return "", "", "", "", ""
    
    def _extraer_precio(self, texto: str) -> tuple:
        """Extrae precio y tipo de descuento del texto"""
        
        texto_lower = texto.lower()
        
        # Buscar porcentaje de descuento
        match_pct = re.search(r'(\d{1,3})%\s*(?:de\s+)?(?:descuento|dscto|dto|off)', texto_lower)
        if match_pct:
            return match_pct.group(1) + "%", "% Descuento"
        
        # Buscar precio en soles
        match_sol = re.search(r'S/\s*([\d.,]+)', texto_lower)
        if match_sol:
            return "S/" + match_sol.group(1), "Precio promo"
        
        # Buscar "a sólo S/"
        match_solo = re.search(r'a\s+s[oó]lo\s+S/\s*([\d.,]+)', texto_lower)
        if match_solo:
            return "S/" + match_solo.group(1), "Precio promo"
        
        return "", "Beneficio"
