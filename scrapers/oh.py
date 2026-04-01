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
                    promos_categoria = self._parsear(html, categoria)
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

    def _parsear(self, html: str, categoria: str) -> List[Promocion]:
        soup = BeautifulSoup(html, "lxml")
        promociones = []
        
        # Buscar específicamente las tarjetas de promociones (oh-card-promotion)
        cards = soup.select('oh-card-promotion div.card-promotion')
        
        seen = set()  # Para evitar duplicados
        
        for card in cards:
            try:
                # Obtener el contenedor principal de la tarjeta (que tiene el enlace)
                link_elem = card.select_one('a.card-promotion__card')
                if not link_elem:
                    continue
                
                # Extraer URL
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
                    promociones.append(Promocion(
                        fuente=self.nombre,
                        categoria=categoria,
                        titulo=titulo,
                        descripcion=descripcion,
                        comercio=comercio,
                        precio=precio_dto,
                        tipo=tipo,
                        fecha_inicio="",
                        fecha_fin="",
                        stock="",
                        url=enlace if enlace else self.url_base,
                        imagen_url=imagen_url,
                    ))
            except Exception as e:
                print(f"[{self.nombre}] Error procesando tarjeta: {e}")
                continue
        
        return promociones
    
    def _limpiar_precio_dto(self, precio_text: str) -> str:
        """Limpia el texto de precio, extrayendo solo número (sin símbolos extras)"""
        if not precio_text:
            return ""
        
        precio_text = precio_text.strip()
        import re
        
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
    
    def _extraer_precio(self, texto: str) -> tuple:
        """Extrae precio y tipo de descuento del texto"""
        import re
        
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
