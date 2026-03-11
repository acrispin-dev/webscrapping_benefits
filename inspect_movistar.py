import requests
from bs4 import BeautifulSoup

url = "https://www.movistar.com.pe/club-movistar"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
}

resp = requests.get(url, headers=headers)
print("Status:", resp.status_code)
html = resp.text

import os
os.makedirs("output", exist_ok=True)
with open("output/debug_movistar.html", "w", encoding="utf-8") as f:
    f.write(html)

print("HTML size:", len(html))