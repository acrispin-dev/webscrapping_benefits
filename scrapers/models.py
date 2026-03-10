from dataclasses import dataclass


@dataclass
class Promocion:
    fuente: str          # Nombre del banco/empresa
    categoria: str       # Tipo de promoción (restaurantes, viajes, etc.)
    titulo: str
    descripcion: str
    comercio: str = ""   # Nombre del comercio/marca de la promoción (ej: KFC, Tambo)
    descripcion: str
    # ── Precio / Descuento ─────────────────────────────────────────────────────
    precio: str = ""     # Valor: "S/ 9.90" ó "30" (entero si es porcentaje)
    tipo: str = ""       # "% Descuento" | "Precio promo" | "Beneficio"
    # ── Vigencia ───────────────────────────────────────────────────────────────
    fecha_inicio: str = ""
    fecha_fin: str = ""
    # ── Otros ─────────────────────────────────────────────────────────────────
    stock: str = ""      # Ej: "Hasta agotar stock", "50 unidades", ""
    url: str = ""        # Solo URL de la página principal
    imagen_url: str = ""
    condiciones: str = ""
