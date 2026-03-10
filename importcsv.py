from bs4 import BeautifulSoup
import csv
import os

INPUT_HTML = r"C:\Users\ALVARO\Desktop\Dev\BenefitsWebScrapping\output\index.html"
OUTPUT_CSV = r"C:\Users\ALVARO\Desktop\Dev\BenefitsWebScrapping\output\promociones.csv"

if not os.path.exists(INPUT_HTML):
    raise FileNotFoundError(f"No existe el archivo: {INPUT_HTML}")

with open(INPUT_HTML, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "html.parser")

tabla = soup.find("table", {"id": "tablaPromos"})
if not tabla:
    raise ValueError("No se encontró la tabla con id='tablaPromos'")

tbody = tabla.find("tbody", {"id": "cuerpoTabla"})
if not tbody:
    raise ValueError("No se encontró el tbody con id='cuerpoTabla'")

rows = tbody.find_all("tr")
data = []

for row in rows:
    fuente = row.get("data-fuente", "").strip()
    categoria = row.get("data-categoria", "").strip()
    tipo = row.get("data-tipo", "").strip()
    comercio = row.get("data-comercio", "").strip()

    celdas = row.find_all("td")
    if len(celdas) < 11:
        continue

    promo_tag = celdas[3].find("strong")
    promocion = promo_tag.get_text(" ", strip=True) if promo_tag else celdas[3].get_text(" ", strip=True)

    img_tag = celdas[3].find("img")
    imagen = img_tag["src"].strip() if img_tag and img_tag.has_attr("src") else ""

    descripcion = celdas[4].get_text(" ", strip=True)
    precio_dto = celdas[5].get_text(" ", strip=True)
    tipo_visible = celdas[6].get_text(" ", strip=True)
    fecha_inicio = celdas[7].get_text(" ", strip=True)
    fecha_fin = celdas[8].get_text(" ", strip=True)
    stock = celdas[9].get_text(" ", strip=True)

    enlace_tag = celdas[10].find("a")
    enlace = enlace_tag["href"].strip() if enlace_tag and enlace_tag.has_attr("href") else ""

    data.append([
        fuente,
        categoria,
        comercio,
        promocion,
        descripcion,
        precio_dto,
        tipo,
        tipo_visible,
        fecha_inicio,
        fecha_fin,
        stock,
        enlace,
        imagen
    ])

headers = [
    "fuente",
    "categoria",
    "comercio",
    "promocion",
    "descripcion",
    "precio_dto",
    "tipo_data",
    "tipo_visible",
    "fecha_inicio",
    "fecha_fin_vigencia",
    "stock",
    "enlace",
    "imagen"
]

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(data)

print(f"CSV generado correctamente: {OUTPUT_CSV}")
print(f"Filas exportadas: {len(data)}")