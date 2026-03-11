from bs4 import BeautifulSoup
with open('output/debug_movistar.html', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'lxml')

cards = soup.select('.swiper-slide, article, .card, [class*="Promo"], [class*="benefit"], [class*="card"], [class*="Benefit"]')
print(f'Total cards selected: {len(cards)}')

filtered_cards = []
for c in cards:
    if not any(c in other.parents for other in cards if other != c):
        filtered_cards.append(c)

print(f'Filtered cards selected: {len(filtered_cards)}')

for i, c in enumerate(filtered_cards[:15]):
    text = c.get_text(" | ", strip=True)
    if text:
        print(f'--- Card {i} ---')
        print('Classes:', c.get('class'))
        print('Text:', text)