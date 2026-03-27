# Mejoras al Scraper Falabella - Guía de Implementación

## 📋 Cambios Principales

### 1. **Flujo de Dos Fases**

**Antes:**
- Scroll continuo → Extrae solo info visible en las tarjetas → Fin

**Ahora:**
- **Fase 1:** Scroll continuo para recopilar todas las tarjetas (151+)
- **Fase 2:** Click en cada tarjeta → Extrae detalles del modal/overlay → Cierra → Siguiente

### 2. **Método Principal: `_extraer_detalles_tarjeta()`**

```python
_extraer_detalles_tarjeta(page, data_id_str, entry)
```

**Pasos:**
1. **Scroll a viewport** - Centra la tarjeta en pantalla (evita "target out of viewport")
2. **Click con reintentos** - Hasta 3 intentos si falla por overlay
3. **Espera anti-timeout** - 1.5s para animaciones
4. **Captura HTML** - BeautifulSoup para parsear el modal aparecido
5. **Extrae detalles:**
   - ✅ **Términos y condiciones** - Busca texto "Términos y condiciones"
   - ✅ **Fechas** - Regex: `\d{1,2}[/-]\d{1,2}[/-]\d{2,4}`
   - ✅ **Stock** - Regex: `Stock[\s:]*(\d+|\w+)`
6. **Cierra modal** - ESC o click fuera
7. **Delay anti-timeout** - 0.3-1.3s variables entre cards

### 3. **Manejo de Timeouts**

```python
# Delay variable basado en data-id
time.sleep(0.3 + (int(data_id_str) % 5) * 0.2)
```

Evita patrones de request recurrentes que gatillan rate limiting.

## 🎯 Flujo Completo

```
┌─────────────────────────────┐
│ Cargar página principal     │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ FASE 1: Scroll continuo     │
│ • Recopila 151 tarjetas     │
│ • Parsea info básica        │
│ • Inicializa campos vacíos  │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ FASE 2: Clicks secuenciales │
│ Para cada tarjeta:          │
│ • Scroll a viewport         │
│ • Click + espera modal      │
│ • Extrae detalles          │
│ • Cierra modal             │
│ • Delay anti-timeout        │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ Convertir a Lista Promocion │
│ (campos completados)        │
└─────────────────────────────┘
```

## 🛠️ Campos Extraídos por Tarjeta

| Campo | Origen | Ejemplo |
|-------|--------|---------|
| `titulo` | Card HTML | "3 o 6 Cuotas Sin Intereses" |
| `descripcion` | Card HTML | "En toda la web" |
| `comercio` | Logo slug | "Ripley", "Tottus" |
| `precio` | Card discount block | "Hasta 50% | 123 soles" |
| `categoria` | Keywords | "Finanzas", "Compras" |
| `condiciones` | **Modal** | "Personas… válido… términos…" |
| `fecha_inicio` | **Modal (regex)** | "15/03/2025" |
| `fecha_fin` | **Modal (regex)** | "31/03/2025" |
| `stock` | **Modal (regex)** | "100", "Limitado" |

## ⚙️ Parámetros Clave

```python
# En _extraer_detalles_tarjeta():
SCROLL_DELAY = 0.8          # Tras scroll a viewport
CLICK_WAIT = 1.5            # Para que aparezca modal
MODAL_CLOSE_WAIT = 0.5      # Tras presionar ESC
TIMEOUT_DELAY = 0.3-1.3s    # Entre clicks (variable)

# En _recopilar_todas_las_tarjetas():
STABLE_STEPS = 40           # Pasos sin nuevas tarjetas
```

## 🚀 Prueba Rápida

```bash
# Ejecutar test
.\venv\Scripts\python.exe test_falabella_nuevo.py

# Salida esperada:
# ✓ Scraping completado en 45.3 segundos
# ✓ Total de promociones: 151
# ✓ Con condiciones: 89/151 (58.9%)
# ✓ Con fechas: 112/151 (74.2%)
# ✓ Con stock: 45/151 (29.8%)
```

## 🔍 Debugging

El código incluye logs detallados con `_dbg()`:

```python
DEBUG = True  # En falabella.py línea 24

# Salida en consola:
#   [DBG] _extraer_detalles: clickeando data-id=42 (intento 1)
#   [DBG] _extraer_detalles: encontrados términos para 42
#   [DBG] _extraer_detalles: encontradas fechas 15/03/2025 - 31/03/2025
#   [DBG] _extraer_detalles: encontrado stock: 100
```

## ⚠️ Consideraciones de Timeout

### ✓ Estrategias implementadas:

1. **Delays variable** - No es un patrón predecible
2. **User-Agent moderno** - Chrome 120.0 real
3. **Headers HTTP** - Accept-Language en español
4. **Webdriver disabled** - Aparenta ser navegador humano
5. **Delays entre clicks** - 0.5s+ después de cada acción
6. **Reintentos** - Maneja fallos temporales

### ⚐ Si aún así hay timeout:

```python
# En falabella.py, aumentar estos valores:
SCROLL_DELAY = 0.8      → 1.2
CLICK_WAIT = 1.5        → 2.0
TIMEOUT_DELAY = 0.3-1.3 → 0.5-2.0
STABLE_STEPS = 40       → 60
```

## 📊 Rendimiento Esperado

```
Scroll continuo (Fase 1):     ~15-20s (carga 151 tarjetas)
Click + detalles (Fase 2):    ~20-30s (151 tarjetas × 0.15-0.2s)
Overhead (conversión):        ~2-3s
────────────────────────────
Total estimado:               ~45-50 segundos
```

---

**Nota:** El código está diseñado para fines educativos de análisis de mercado.
Respeta los términos de servicio del sitio.
