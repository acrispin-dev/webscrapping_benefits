"""
Genera el archivo output/index.html con todas las promociones.
"""
from scrapers.models import Promocion
from typing import List
from datetime import datetime
import html as html_lib

FUENTE_COLORES = {
    "Banco Falabella": "#EF3340",
    "Plin": "#8B2FC9",
    "Scotiabank": "#EC111A",
    "Interbank": "#00A859",
    "BBVA": "#004481",
    "Banco Ripley": "#6D1C7A",
    "Movistar": "#019DF4",
    "Entel": "#00AEEF",
    "OH": "#1B5E20",
}

FUENTE_EMOJIS = {
    "Banco Falabella": "🏦",
    "Plin": "📱",
    "Scotiabank": "🏦",
    "Interbank": "🏦",
    "BBVA": "🏦",
    "Banco Ripley": "🏦",
    "Movistar": "📶",
    "Entel": "📡",
    "OH": "💳",
}


def generar_html(promociones: List[Promocion], ruta_salida: str = "output/index.html"):
    fuentes = sorted({p.fuente for p in promociones})
    categorias = sorted({p.categoria for p in promociones if p.categoria})

    filas_html = ""
    for p in promociones:
        color = FUENTE_COLORES.get(p.fuente, "#555")
        emoji = FUENTE_EMOJIS.get(p.fuente, "🔖")
        titulo_safe   = html_lib.escape(p.titulo)
        desc_safe     = html_lib.escape(p.descripcion)
        cat_safe      = html_lib.escape(p.categoria)
        comercio_safe = html_lib.escape(p.comercio)
        fuente_safe   = html_lib.escape(p.fuente)
        precio_safe   = html_lib.escape(p.precio)
        tipo_safe     = html_lib.escape(p.tipo)
        f_inicio_safe = html_lib.escape(p.fecha_inicio)
        f_fin_safe    = html_lib.escape(p.fecha_fin)
        stock_safe    = html_lib.escape(p.stock)

        # Badge de tipo con color semántico
        tipo_color = {
            "% Descuento":  ("#e74c3c", "#fff"),
            "Precio promo": ("#27ae60", "#fff"),
            "Beneficio":    ("#8e44ad", "#fff"),
        }.get(p.tipo, ("#95a5a6", "#fff"))
        tipo_html = (
            f'<span class="tipo-badge" style="background:{tipo_color[0]};color:{tipo_color[1]}">'
            f'{tipo_safe}</span>'
        ) if tipo_safe else ""

        # Precio con formato visual
        precio_html = ""
        if precio_safe:
            if p.tipo == "% Descuento":
                precio_html = f'<span class="precio-pct">{precio_safe}%</span>'
            else:
                precio_html = f'<span class="precio-sol">{precio_safe}</span>'

        img_html = ""
        if p.imagen_url:
            img_html = f'<img src="{html_lib.escape(p.imagen_url)}" alt="" class="promo-img" loading="lazy">'

        enlace_html = ""
        if p.url:
            enlace_html = f'<a href="{html_lib.escape(p.url)}" target="_blank" rel="noopener noreferrer">Ver →</a>'

        filas_html += f"""
        <tr data-fuente="{fuente_safe}" data-categoria="{cat_safe}" data-tipo="{tipo_safe}" data-comercio="{comercio_safe}">
          <td>
            <span class="badge" style="background:{color}">{fuente_safe}</span>
          </td>
          <td><span class="cat-tag">{cat_safe}</span></td>
          <td><span class="comercio-tag">{comercio_safe}</span></td>
          <td>
            {img_html}
            <strong>{titulo_safe}</strong>
          </td>
          <td class="desc">{desc_safe}</td>
          <td class="precio-cell">{precio_html}</td>
          <td>{tipo_html}</td>
          <td class="fecha">{f_inicio_safe}</td>
          <td class="fecha">{f_fin_safe}</td>
          <td class="stock">{stock_safe}</td>
          <td>{enlace_html}</td>
        </tr>"""

    opciones_fuente = "".join(f'<option value="{html_lib.escape(f)}">{html_lib.escape(f)}</option>' for f in fuentes)
    opciones_cat = "".join(f'<option value="{html_lib.escape(c)}">{html_lib.escape(c)}</option>' for c in categorias)
    tipos_unicos = sorted({p.tipo for p in promociones if p.tipo})
    opciones_tipo = "".join(f'<option value="{html_lib.escape(t)}">{html_lib.escape(t)}</option>' for t in tipos_unicos)
    comercios_unicos = sorted({p.comercio for p in promociones if p.comercio})
    opciones_comercio = "".join(f'<option value="{html_lib.escape(c)}">{html_lib.escape(c)}</option>' for c in comercios_unicos)
    total = len(promociones)
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Promociones Perú — Central de Ofertas</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f0f2f5;
      color: #222;
    }}

    header {{
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
      color: #fff;
      padding: 24px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
    }}

    header h1 {{ font-size: 1.6rem; font-weight: 700; }}
    header p  {{ font-size: 0.85rem; opacity: 0.7; margin-top: 4px; }}
    .stat-badge {{
      background: rgba(255,255,255,0.15);
      border-radius: 999px;
      padding: 6px 16px;
      font-size: 0.9rem;
      font-weight: 600;
    }}

    .controles {{
      background: #fff;
      border-bottom: 1px solid #ddd;
      padding: 14px 32px;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: center;
    }}

    .controles input,
    .controles select {{
      padding: 7px 12px;
      border: 1px solid #ccc;
      border-radius: 6px;
      font-size: 0.9rem;
      outline: none;
      transition: border-color 0.2s;
    }}
    .controles input:focus,
    .controles select:focus {{ border-color: #0f3460; }}
    .controles input {{ flex: 1; min-width: 200px; }}

    .tabla-wrapper {{
      padding: 24px 32px;
      overflow-x: auto;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 10px;
      overflow: hidden;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }}

    thead tr {{ background: #1a1a2e; color: #fff; }}
    thead th {{
      padding: 12px 14px;
      text-align: left;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      white-space: nowrap;
    }}

    tbody tr {{
      border-bottom: 1px solid #f0f0f0;
      transition: background 0.15s;
    }}
    tbody tr:hover {{ background: #f7f9ff; }}
    tbody tr.oculta {{ display: none; }}

    tbody td {{
      padding: 11px 14px;
      font-size: 0.88rem;
      vertical-align: middle;
    }}

    .badge {{
      display: inline-block;
      color: #fff;
      font-size: 0.78rem;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 999px;
      white-space: nowrap;
    }}

    .cat-tag {{
      background: #eef1f8;
      color: #444;
      font-size: 0.78rem;
      padding: 3px 9px;
      border-radius: 5px;
      white-space: nowrap;
    }}

    .comercio-tag {{
      background: #fff3e0;
      color: #b45309;
      font-size: 0.8rem;
      font-weight: 600;
      padding: 3px 9px;
      border-radius: 5px;
      white-space: nowrap;
    }}

    .tipo-badge {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 3px 9px;
      border-radius: 5px;
      white-space: nowrap;
    }}

    .precio-cell {{ white-space: nowrap; text-align: right; }}
    .precio-pct {{
      font-size: 1.3rem;
      font-weight: 800;
      color: #e74c3c;
      letter-spacing: -1px;
    }}
    .precio-sol {{
      font-size: 1.1rem;
      font-weight: 700;
      color: #27ae60;
    }}

    .desc {{ max-width: 280px; color: #555; font-size: 0.83rem; }}
    .fecha {{ white-space: nowrap; color: #777; font-size: 0.82rem; }}
    .stock {{ font-size: 0.8rem; color: #e67e22; }}

    .promo-img {{
      display: block;
      max-width: 90px;
      max-height: 60px;
      object-fit: contain;
      margin-bottom: 6px;
      border-radius: 4px;
    }}

    tbody td a {{
      color: #0f3460;
      text-decoration: none;
      font-size: 0.83rem;
      white-space: nowrap;
      font-weight: 600;
    }}
    tbody td a:hover {{ text-decoration: underline; }}

    .sin-resultados {{
      text-align: center;
      padding: 40px;
      color: #999;
      font-size: 1rem;
    }}

    footer {{
      text-align: center;
      padding: 20px;
      font-size: 0.78rem;
      color: #aaa;
    }}

    @media (max-width: 768px) {{
      header, .controles, .tabla-wrapper {{ padding-left: 16px; padding-right: 16px; }}
    }}
  </style>
</head>
<body>

<header>
  <div>
    <h1>🛍️ Central de Promociones — Perú</h1>
    <p>Actualizado: {ahora} · Uso académico / local</p>
  </div>
  <span class="stat-badge">{total} promociones</span>
</header>

<div class="controles">
  <input type="text" id="buscar" placeholder="🔍 Buscar por título, descripción...">
  <select id="filtroFuente">
    <option value="">Todas las fuentes</option>
    {opciones_fuente}
  </select>
  <select id="filtroCategoria">
    <option value="">Todas las categorías</option>
    {opciones_cat}
  </select>
  <select id="filtroComercio">
    <option value="">Todos los comercios</option>
    {opciones_comercio}
  </select>
  <select id="filtroTipo">
    <option value="">Todos los tipos</option>
    {opciones_tipo}
  </select>
  <span id="contadorVisible" style="font-size:0.85rem;color:#666;margin-left:4px;"></span>
</div>

<div class="tabla-wrapper">
  <table id="tablaPromos">
    <thead>
      <tr>
        <th>Fuente</th>
        <th>Categoría</th>
        <th>Comercio</th>
        <th>Promoción</th>
        <th>Descripción</th>
        <th>Precio / Dto.</th>
        <th>Tipo</th>
        <th>F. Inicio</th>
        <th>F. Fin / Vigencia</th>
        <th>Stock</th>
        <th>Enlace</th>
      </tr>
    </thead>
    <tbody id="cuerpoTabla">
      {filas_html}
    </tbody>
  </table>
  <div class="sin-resultados" id="sinResultados" style="display:none;">
    No hay promociones que coincidan con los filtros aplicados.
  </div>
</div>

<footer>Datos obtenidos con fines académicos. La veracidad depende de la fuente original.</footer>

<script>
  const filas = Array.from(document.querySelectorAll('#cuerpoTabla tr'));
  const buscar = document.getElementById('buscar');
  const filtroFuente = document.getElementById('filtroFuente');
  const filtroCategoria = document.getElementById('filtroCategoria');
  const filtroComercio = document.getElementById('filtroComercio');
  const filtroTipo = document.getElementById('filtroTipo');
  const sinResultados = document.getElementById('sinResultados');
  const contador = document.getElementById('contadorVisible');

  function filtrar() {{
    const q = buscar.value.toLowerCase();
    const fuente = filtroFuente.value.toLowerCase();
    const cat = filtroCategoria.value.toLowerCase();
    const comercio = filtroComercio.value.toLowerCase();
    const tipo = filtroTipo.value.toLowerCase();
    let visibles = 0;

    filas.forEach(tr => {{
      const texto = tr.textContent.toLowerCase();
      const tFuente = (tr.dataset.fuente || '').toLowerCase();
      const tCat = (tr.dataset.categoria || '').toLowerCase();
      const tComercio = (tr.dataset.comercio || '').toLowerCase();
      const tTipo = (tr.dataset.tipo || '').toLowerCase();

      const okQ = !q || texto.includes(q);
      const okF = !fuente || tFuente === fuente;
      const okC = !cat || tCat === cat;
      const okCom = !comercio || tComercio === comercio;
      const okT = !tipo || tTipo === tipo;

      if (okQ && okF && okC && okCom && okT) {{
        tr.classList.remove('oculta');
        visibles++;
      }} else {{
        tr.classList.add('oculta');
      }}
    }});

    sinResultados.style.display = visibles === 0 ? 'block' : 'none';
    contador.textContent = visibles + ' resultado' + (visibles !== 1 ? 's' : '');
  }}

  buscar.addEventListener('input', filtrar);
  filtroFuente.addEventListener('change', filtrar);
  filtroCategoria.addEventListener('change', filtrar);
  filtroComercio.addEventListener('change', filtrar);
  filtroTipo.addEventListener('change', filtrar);
  filtrar();
</script>
</body>
</html>"""

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] Generado: {ruta_salida} ({total} promociones)")
