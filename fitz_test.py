
import fitz
import re

_RE_FECHA = re.compile(r'(?:Del|Vigencia)[^\d]*([\d/]+)\s*al\s*([\d/]+)', re.IGNORECASE)
_RE_A_SOLO = re.compile(r'a\s+solo\s+(S/[\d\.]+)', re.IGNORECASE)

doc = fitz.open('CatalogoDePromocionesLima.pdf')
page = doc[7]
width = page.rect.width

# get dict
d = page.get_text('dict')
blocks = d['blocks']

# split into left and right columns
col_left = []
col_right = []

for b in blocks:
    bbox = b['bbox']
    center_x = (bbox[0] + bbox[2]) / 2
    if center_x < width / 2:
        col_left.append(b)
    else:
        col_right.append(b)

def process_col(col_blocks):
    col_blocks.sort(key=lambda b: b['bbox'][1]) # sort by top Y
    
    current_image = None
    bloque_actual = []
    
    for b in col_blocks:
        if b['type'] == 1:
            current_image = b
            print('--- NEW LOGO IMAGE ---', b['bbox'])
        elif b['type'] == 0:
            text = ''
            for l in b['lines']:
                for s in l['spans']:
                    text += s['text'] + ' '
                text += '\n'
            text = text.strip()
            if text:
                print(f'Text under logo: {text[:50]}...')

print('LEFT COLUMN:')
process_col(col_left)
print('\nRIGHT COLUMN:')
process_col(col_right)

