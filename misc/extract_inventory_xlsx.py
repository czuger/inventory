"""
Re-extract the club inventory from the original spreadsheet, faithfully.

Reads `misc/20241206_inventaire Grognards.xlsx` with the standard library only (an .xlsx is a zip of XML parts),
so that nothing a flat export loses is lost here: merged headers, strikethrough, cell comments, floating text boxes
and cell fills are all read and all accounted for.

Writes two NEW files and never touches the application database:

    data/xlsx_extract/inventory_v2.json      the source of truth, one object per inventory line
    data/xlsx_extract/inventory_v2.sqlite3   the same data, rebuilt from the JSON, for querying

The rules below are tuned to one frozen file, so its sha256 is pinned: a different file is refused rather than
parsed with rules that were never checked against it.

Usage:
    python misc/extract_inventory_xlsx.py                # extract, check, write both files
    python misc/extract_inventory_xlsx.py --print-rows   # also print how every row was classified
    python misc/extract_inventory_xlsx.py --check-tsv    # also diff the cell values against the old TSV exports
"""
import argparse
import csv
import hashlib
import io
import json
import os
import posixpath
import re
import sqlite3
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / 'misc' / '20241206_inventaire Grognards.xlsx'
OUT_DIR = ROOT / 'data' / 'xlsx_extract'
EXPECTED_SHA256 = '803669d842d49e2cecde0a77a1c0a07db7c5acd11e35d375ff24fb4a8eec64ef'
SCHEMA_VERSION = 2

SHEET_IDS = {'Feuil1': 'F1', 'Nappes': 'NA', 'Feuil2': 'F2', 'Feuil3': 'F3'}
TSV_FILES = {'Feuil1': '20241206_inventaire Grognards.xls - Feuil1.tsv', 'Nappes': 'Nappes.tsv'}
# The only cells where the old TSV exports differ from the workbook (header filled in later; a newline flattened).
KNOWN_TSV_DIFFS = {('Feuil1', ref) for ref in ('E2', 'G2', 'H2', 'I2', 'J2', 'K2', 'B14')}

M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
XDR = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
DML = 'http://schemas.openxmlformats.org/drawingml/2006/main'

RED, BLUE, GREEN, BLACK = 'FFFF0000', 'FF0070C0', 'FF00B050', 'FF000000'
YELLOW, GREY = 'FFFFFF00', 'FFD8D8D8'

# Every (bold, italic, underline, strike, font colour, fill) combination a value cell may have. Anything else
# means the sheet encodes something this script does not understand, and the run fails.
KNOWN_STYLES = {
    (True, False, True, False, RED, None): 'typology',
    (True, False, True, False, RED, YELLOW): 'typology',
    (True, False, False, False, BLACK, None): 'column header',
    (True, True, True, False, BLUE, None): 'category',
    (False, False, True, False, GREEN, None): 'subcategory',
    (False, False, False, False, BLACK, None): 'plain',
    (False, False, False, True, BLACK, None): 'struck',
    (False, True, False, False, BLACK, None): 'italic',
}
LEVELS = {'typology': 0, 'category': 1, 'subcategory': 2, 'group': 3}

ROOM_FIXES = {'gande salle': 'grande salle'}

# Words that count containers rather than name the thing: "1 boite" under an item takes that item's label.
CONTAINER_UNITS = {'boite', 'boites', 'boîte', 'boîtes', 'carton', 'cartons', 'panière', 'panières', 'set', 'sets'}
UNIT_CANONICAL = {
    'boite': 'boîte', 'boites': 'boîte', 'boîte': 'boîte', 'boîtes': 'boîte', 'carton': 'carton', 'cartons': 'carton',
    'panière': 'panière', 'panières': 'panière', 'set': 'set', 'sets': 'set', 'figs': 'figurine', 'kg': 'kg',
    'l': 'l', 'm': 'm',
}

# Rows the general rules cannot classify. (sheet id, row) -> (kind, reason)
ROW_OVERRIDES = {
    ('F1', 144): ('heading_mark', 'category heading with a location mark (F144) but no quantity and no remark'),
    ('F1', 164): ('heading_self_item', 'category heading that is its own single line: B164 describes its content'),
    ('F1', 180): ('heading_self_item', 'category heading that is its own single line: B180 counts its boxes'),
}


def part(n, n_max=None, unit=None, qualifier=None, dimension=None, approx=False):
    return {'n': n, 'n_max': n_max, 'unit': unit, 'qualifier': qualifier, 'dimension': dimension, 'approx': approx}


# Quantity cells the general parser cannot read. Each override is checked against the numbers in the raw text.
QTY_OVERRIDES = {
    ('F1', 14): {'parts': [part(1, qualifier='latex'), part(4, qualifier='floquées')],
                 'reason': 'two counts, each with its material, on two lines'},
    ('F1', 18): {'parts': [part(11, qualifier='steppe'), part(8, qualifier='plage'), part(9, qualifier='neige')],
                 'reason': 'three counts',
                 'flags': [('QTY_PARTS_PAIRED_WITH_REMARK',
                            'qualifiers taken by position from C18 "steppe + plage + neige"')]},
    ('F1', 19): {'parts': [part(8, dimension='120cm')], 'reason': 'count x length'},
    ('F1', 20): {'parts': [part(2, dimension='180cm')], 'reason': 'count x length'},
    ('F1', 40): {'parts': [part(2, unit='panières')], 'label': 'batiments',
                 'reason': 'count, container, then the thing'},
    ('F1', 41): {'parts': [part(1.5, unit='m')], 'label': 'murs', 'reason': 'a length, then the thing'},
    ('F1', 48): {'parts': [part(2, n_max=3, unit='m')], 'label': 'routes', 'reason': 'a length range, then the thing'},
    ('F1', 87): {'parts': [part(33, unit='piétons'), part(4, unit='cavaliers')],
                 'reason': 'two counts of different things'},
    ('F1', 164): {'parts': [], 'reason': 'free text',
                  'flags': [('QTY_FREE_TEXT', 'B164 is a description ("1 lampe + accessoires + fig en en libre '
                                              'service"), not a countable quantity')]},
    ('F1', 180): {'parts': [part(1, unit='boites', qualifier='petite'), part(6, unit='boites', qualifier='grandes')],
                  'reason': 'two counts of boxes'},
    ('F1', 181): {'parts': [], 'reason': 'not a quantity',
                  'flags': [('QTY_NOT_A_QUANTITY',
                             'B181 lists scales ("15mm, 28mm") and C181 periods ("17e, 18e, 19e")')]},
}

# Ambiguities only a human can settle. (sheet id, row) -> [(code, detail)]
_ARMADA = 'labelled "= règle" in A69 but counted in cartons/boxes with faction or product names; rows 70-73 continue it'
MANUAL_FLAGS = {
    ('F1', 19): [('REMARK_SPANS_ROWS',
                  'C19 and C20 read as one sentence: "+ 4 trétaux supprimées durant période COVID"'),
                 ('REMARK_MENTIONS_OTHER_ITEM', 'C19 records four trestles removed; they have no row of their own')],
    ('F1', 20): [('REMARK_SPANS_ROWS', 'C20 continues the sentence started in C19')],
    ('F1', 26): [('QTY_IN_REMARK', 'C26 "dans 1 boite" may be the quantity; B26 is empty')],
    ('F1', 62): [('TYPE_UNCLEAR', 'a figurine listed under scenery (+30mm); its game is not stated')],
    ('F1', 69): [('TYPE_UNCLEAR', _ARMADA)],
    ('F1', 70): [('TYPE_UNCLEAR', _ARMADA)],
    ('F1', 71): [('TYPE_UNCLEAR', _ARMADA)],
    ('F1', 72): [('TYPE_UNCLEAR', _ARMADA)],
    ('F1', 73): [('TYPE_UNCLEAR', _ARMADA)],
    ('F1', 101): [('CONTEXT_UNCLEAR',
                   '"2 maquettes" has no label of its own; attached to row 100 because it follows it')],
    ('F1', 142): [('LOC_MAY_INHERIT', 'the lights (row 139) are "chez le Préz"; their stands may be there too')],
    ('F1', 181): [('ROW_UNCLEAR',
                   'either a note that the listing of the stock is held by François S, or a second lot')],
}

# Relations stated by a remark. (sheet id, row) -> [(relation, target id, evidence)]
MANUAL_LINKS = {
    ('F1', 78): [('contained_in', 'F1:r77', 'C78 "dans la boite des Gob"')],
}

# Where a floating text box belongs: its anchor cell is only where it was dropped on the sheet.
TEXTBOX_SECTION = {('F1', 'G25'): 'F1:s22'}

# Category headings (by row) whose content is not ordinary club stock.
SECTION_DISPOSITION = {('F1', 166): 'gift_candidate', ('F1', 180): 'for_sale'}

# Obvious typos. Never applied: offered as `label.suggested`, and flagged.
TYPO_FIXES = [
    ('floquéee', 'floquée'), ('batîments', 'bâtiments'), ('EFLES', 'ELFES'), ('URUKAÏ', 'URUK-HAÏ'),
    ('Filed of Glory', 'Field of Glory'), ('Flame of War', 'Flames of War'), ('Dipolmacy', 'Diplomacy'),
    ('Handiap Race', 'Handicap Race'), ('FIRESTROM', 'FIRESTORM'), ('Planet Steams', 'Planet Steam'),
    ('figruines', 'figurines'), ('Régles', 'Règles'),
]

# Nappes "Matériau" -> the application's tablecloth material values.
MATERIAL_APP = {'Texturé': 'textured', 'Tissu': 'cloth', 'Mousepad': 'mousepad (neoprene)'}
# What a Feuil1 wording implies for the Nappes "Matériau" column; a different value there is a conflict.
WORDING_MATERIAL = {'floqué': 'Texturé', 'tissu': 'Tissu', 'mousse': 'Mousepad', 'latex': 'Latex'}

DECISIONS = [
    ('D01', 'Read the .xlsx with zipfile + xml.etree, no third-party library.',
     'openpyxl is not installed and does not expose floating text boxes; the raw XML exposes everything.'),
    ('D02', 'Location columns are mapped per header block; the one-row header at Feuil1 row 182 inherits the map of '
            'the block above it.',
     'Rows 1-3, 64-66 and 127-129 repeat the same header for printing and all agree. Row 182 has no room/spot rows, '
     'and no row below it carries a location mark.'),
    ('D03', 'The room "gande salle" is normalized to "grande salle"; the raw spelling is kept in room_raw.',
     'An obvious typo, repeated in every header block.'),
    ('D04', 'Rooms follow the header: grande salle = placard 1 porte, placard 2 portes; petite salle = pièce 1, '
            'vitrine 1, vitrine 2, pièce 2, armoire 1, armoire 2.',
     'Stated by explicit cells in Feuil1 row 2 and Nappes row 2 and by the merges D65:E65 / F65:K65 and '
     'D128:E128 / F128:K128.'),
    ('D05', 'Hierarchy comes from the font of column A (red = typology, blue = category, green = sub-category), '
            'with the numbering kept verbatim in number_raw and never used as an identifier.',
     'The numbering is unreliable: 1.4 is used twice, 1.2.4 precedes 1.2.3, 17.2/17.3/17.4 stand for 1.7.x, '
     '1.4.2.2 appears twice. Records are identified by sheet and row.'),
    ('D06', 'A heading row that also carries data yields a section and an item. A green or blue row with a numeric '
            'quantity is a leaf item, not a section.',
     'Rows 40, 56, 60, 84, 104, 167, 169 put the first item of the section on the heading row; rows 131-139 and 143 '
     'are items typed in the sub-category style.'),
    ('D07', 'A row with an empty column A takes its label from the quantity cell ("9 maisons", "Britannia") and '
            'records the row it continues in `context`. When the quantity cell only counts containers ("1 boite"), '
            'the label is inherited from that context.',
     'These rows list things under the heading or item above them.'),
    ('D08', 'Quantities keep the raw text and are parsed into parts (n, n_max, unit, qualifier, dimension, approx). '
            'A total is given only when the parts share a unit and none is a range. Name-only rows are `implied`.',
     'Column B mixes counts, containers, lengths, weights, ranges, approximations and plain names; one integer '
     'cannot hold that without inventing.'),
    ('D09', 'Location marks are kept one per column with their raw value: X = presence, a number = a count at that '
            'place, text = kept as text with any number parsed. No per-place split is inferred from X marks.',
     'Seven rows are in several places; only some say how many where.'),
    ('D10', 'A struck-through quantity or material cell sets status = struck. The row is kept.',
     'Strikethrough is how the sheet records things lost or removed (remarks: "perdues dans la masse", '
     '"supprimées durant période COVID").'),
    ('D11', 'For tablecloths (section 1.1.1) the Nappes rows are canonical and Feuil1 rows 6-14 are kept but marked '
            'canonical = false; the two are linked with refines / refined_by.',
     'Nappes is a finer breakdown of the same stock (same totals, split by place and theme, plus a material). '
     'Summing both would count every tablecloth twice. Reversible: flip `canonical`.'),
    ('D12', 'Nothing is invented: no game, universe, period or location that the sheet does not state. An item '
            'without a location mark has an empty locations list.',
     'The old extraction filled required application fields with guesses.'),
    ('D13', '"chez ..." in a remark, a comment or a label is recorded in `holder` (who, how many, where it is said).',
     'Several items are kept at a member\'s home rather than in the club rooms.'),
    ('D14', 'Sections 1.7 "cadeaux potentiels" and 1.8 "stock de figruines à vendre" set disposition = '
            'gift_candidate / for_sale instead of club.',
     'They are listed in the inventory but are not club stock to lend.'),
    ('D15', 'Floating text boxes are annotations attached to a section or to the sheet, not to the cell they float '
            'over. The box over the 15mm scenery block is attached to section 1.2.1.',
     'The anchor cell is only where the box was dropped; the 15mm box describes the whole block in aggregate.'),
    ('D16', 'Typos are never corrected in place; a correction is offered in label.suggested and flagged.',
     'The raw sheet is the record; silent corrections cannot be told apart from errors.'),
    ('D17', 'Everything interpreted (size in cm, scale, application material, suggested application item type) '
            'lives under `derived`, each with the rule that produced it.',
     'Keeps the faithful layer and the interpreted layer apart.'),
    ('D18', 'Sizes in parentheses with decimals, "(1,2x1,8)", are read as metres; bare "50x50" / "60x60" as '
            'centimetres.',
     'Gaming mats are 0.9 to 1.8 m; modular boards are 50 or 60 cm tiles.'),
    ('D19', 'Plain rows with a label and nothing else (15mm scenery, rows 24 and 27-38) are kept with '
            'status = placeholder.',
     'They name kinds of scenery without quantity or place; whether they are stock is not stated.'),
]


def fail(message):
    raise SystemExit(f'ERROR: {message}')


def m(tag):
    return f'{{{M}}}{tag}'


def norm_ws(text):
    return re.sub(r'\s+', ' ', text).strip()


def slug(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def split_ref(ref):
    match = re.fullmatch(r'([A-Z]+)(\d+)', ref)
    return match.group(1), int(match.group(2))


def col_index(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def col_name(n):
    name = ''
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def range_refs(rng):
    first, _, last = rng.partition(':')
    (c1, r1), (c2, r2) = split_ref(first), split_ref(last or first)
    return [f'{col_name(c)}{r}' for r in range(r1, r2 + 1) for c in range(col_index(c1), col_index(c2) + 1)]


# ───────────────────────────── raw reader ─────────────────────────────

def read_workbook(path):
    """Everything the workbook holds, with no interpretation."""
    z = zipfile.ZipFile(path)
    names = set(z.namelist())

    def xml(name):
        return ET.fromstring(z.read(name))

    def rels(part_name):
        folder, filename = posixpath.split(part_name)
        name = f'{folder}/_rels/{filename}.rels'
        if name not in names:
            return {}
        return {rel.get('Id'): (rel.get('Type').rsplit('/', 1)[-1],
                                posixpath.normpath(posixpath.join(folder, rel.get('Target'))))
                for rel in xml(name)}

    strings = []
    for si in xml('xl/sharedStrings.xml').findall(m('si')):
        if si.find(m('rPh')) is not None:
            fail('phonetic runs in shared strings are not handled')
        strings.append(''.join(t.text or '' for t in si.iter(m('t'))))

    styles = xml('xl/styles.xml')

    def on(font, tag):
        el = font.find(m(tag))
        return el is not None and el.get('val', '1') not in ('0', 'false', 'none')

    fonts = []
    for font in styles.find(m('fonts')):
        color = font.find(m('color'))
        fonts.append({'b': on(font, 'b'), 'i': on(font, 'i'), 'u': on(font, 'u'), 'strike': on(font, 'strike'),
                      'color': color.get('rgb') if color is not None else None})
    fills = []
    for fill in styles.find(m('fills')):
        pattern = fill.find(m('patternFill'))
        if pattern is None or pattern.get('patternType') in (None, 'none'):
            fills.append(None)
        else:
            fg = pattern.find(m('fgColor'))
            fills.append(fg.get('rgb') if fg is not None and fg.get('rgb') else pattern.get('patternType'))
    xfs = [dict(fonts[int(xf.get('fontId', 0))], fill=fills[int(xf.get('fillId', 0))])
           for xf in styles.find(m('cellXfs'))]

    wb_rels = rels('xl/workbook.xml')
    sheets = []
    for sheet_el in xml('xl/workbook.xml').find(m('sheets')):
        name = sheet_el.get('name')
        if sheet_el.get('state') != 'visible':
            fail(f'sheet {name!r} is not visible; hidden sheets are not handled')
        part_name = wb_rels[sheet_el.get(f'{{{R}}}id')][1]
        root = xml(part_name)
        cells, empty_fills = {}, {}
        for row in root.find(m('sheetData')):
            if row.get('hidden') == '1':
                fail(f'{name}: hidden row {row.get("r")}')
            for c in row:
                ref, style = c.get('r'), xfs[int(c.get('s', 0))]
                if c.find(m('f')) is not None or c.find(m('is')) is not None:
                    fail(f'{name}!{ref}: formulas and inline strings are not handled')
                v = c.find(m('v'))
                if v is None:
                    if style['fill']:
                        empty_fills[ref] = style['fill']
                    continue
                if c.get('t') == 's':
                    value, kind = strings[int(v.text)], 's'
                    if value == '':
                        fail(f'{name}!{ref}: empty string cell')
                elif c.get('t') in (None, 'n'):
                    number = float(v.text)
                    value, kind = (int(number) if number.is_integer() else number), 'n'
                else:
                    fail(f'{name}!{ref}: cell type {c.get("t")!r} is not handled')
                col, row_no = split_ref(ref)
                cells[ref] = {'ref': ref, 'col': col, 'row': row_no, 'value': value, 'type': kind, 'style': style}
        merges = [mc.get('ref') for mc in root.iter(m('mergeCell'))]

        comments, boxes = [], []
        for kind, target in rels(part_name).values():
            if kind == 'comments':
                for comment in xml(target).iter(m('comment')):
                    comments.append({'ref': comment.get('ref'),
                                     'raw': ''.join(t.text or '' for t in comment.iter(m('t')))})
            elif kind == 'drawing':
                for anchor in xml(target):
                    start = anchor.find(f'{{{XDR}}}from')
                    if start is None:
                        fail(f'{name}: a drawing without a cell anchor')
                    col = int(start.find(f'{{{XDR}}}col').text) + 1
                    ref = f'{col_name(col)}{int(start.find(f"{{{XDR}}}row").text) + 1}'
                    lines = [''.join(t.text or '' for t in p.iter(f'{{{DML}}}t')) for p in anchor.iter(f'{{{DML}}}p')]
                    boxes.append({'ref': ref, 'text': '\n'.join(line.strip() for line in lines if line.strip())})
        rows = {}
        for cell in cells.values():
            rows.setdefault(cell['row'], {})[cell['col']] = cell
        sheets.append({'name': name, 'id': SHEET_IDS[name], 'cells': cells, 'rows': rows, 'merges': merges,
                       'empty_fills': empty_fills, 'comments': comments, 'boxes': boxes})
    return sheets


# ───────────────────────────── layout ─────────────────────────────

def find_headers(sheet, locations=None):
    """
    Header blocks: a row holding `quantité` and `Localisation`, followed (or not) by a room row and a spot row.
    With `locations`, every location column is tied to its location record.
    """
    rows, headers = sheet['rows'], []
    merged = {ref: range_refs(rng)[0] for rng in sheet['merges'] for ref in range_refs(rng)}
    for r in sorted(rows):
        by_value = {cell['value']: col for col, cell in rows[r].items()}
        if 'quantité' not in by_value or 'Localisation' not in by_value:
            continue
        header = {'id': f'{sheet["id"]}:h{r}', 'row': r, 'rows': [r], 'label_col': 'A', 'qty_col': by_value['quantité'],
                  'remark_col': by_value['remarques'], 'material_col': None, 'columns': None}
        start = by_value['Localisation']
        three_rows = (r + 2 in rows and start in rows[r + 2]
                      and 'A' not in rows.get(r + 1, {}) and 'A' not in rows[r + 2])
        if three_rows:
            header['rows'] = [r, r + 1, r + 2]
            columns = []
            for index in range(col_index(start), max(col_index(c) for c in rows[r + 2]) + 1):
                col = col_name(index)
                spot = rows[r + 2].get(col)
                room = rows[r + 1].get(col) or sheet['cells'].get(merged.get(f'{col}{r + 1}', ''))
                if spot is None or room is None:
                    fail(f'{sheet["name"]}: location column {col} of the header at row {r} has no room or spot')
                columns.append({'col': col, 'room_raw': room['value'], 'spot_raw': spot['value']})
            header['columns'] = columns
            for hr in header['rows']:
                for col, cell in rows[hr].items():
                    if cell['value'] == 'Matériau':
                        header['material_col'] = col
        headers.append(header)
    if not headers or headers[0]['columns'] is None:
        fail(f'{sheet["name"]}: no three-row header found')
    for previous, header in zip(headers, headers[1:]):
        if header['columns'] is None:
            header['columns'], header['inherited_from'] = previous['columns'], previous['id']
    if locations is not None:
        for header in headers:
            header['columns'] = [dict(column, id=loc['id'], room=loc['room'], spot=loc['spot'])
                                 for column, loc in zip(header['columns'], locations)]
        for loc, column in zip(locations, headers[0]['columns']):
            loc['columns'][sheet['name']] = column['col']
    return headers


# ───────────────────────────── parsing helpers ─────────────────────────────

CODE_RE = re.compile(r'^(\d+(?:\.\d+)*)(?:\.\s*|\s+)(\S.*)$', re.S)
NUMBER = r'\d+(?:,\d+)?'
QTY_RE = re.compile(rf'^({NUMBER})(?:-({NUMBER}))?\s*(.*)$', re.S)


def split_code(text):
    """'1.1.1.3.nappes mousse' -> ('1.1.1.3', 'nappes mousse'); a label without numbering -> (None, label)."""
    match = CODE_RE.match(text.strip())
    return (match.group(1), match.group(2)) if match else (None, text)


def fr_number(text):
    number = float(text.replace(',', '.'))
    return int(number) if number.is_integer() else number


def parse_qty_text(text):
    """'40 figs env' -> (part, 'figs'); 'x3' -> (part, ''); text that does not start with a number -> None."""
    text = norm_ws(text)
    match = re.fullmatch(r'x(\d+)', text)
    if match:
        return part(int(match.group(1))), ''
    match = QTY_RE.match(text)
    if not match:
        return None
    rest, approx = match.group(3).strip(), False
    env = re.fullmatch(r'(.*?)\s*\benv', rest)
    if env:
        rest, approx = env.group(1).strip(), True
    return part(fr_number(match.group(1)), n_max=fr_number(match.group(2)) if match.group(2) else None,
                approx=approx), rest


def style_key(style):
    return (style['b'], style['i'], style['u'], style['strike'], style['color'], style['fill'])


def style_letters(style):
    return ''.join(letter for letter, key in (('b', 'b'), ('i', 'i'), ('u', 'u'), ('s', 'strike')) if style[key])


def text_level(cell):
    return KNOWN_STYLES[style_key(cell['style'])]


class Extraction:
    def __init__(self):
        self.headers, self.sections, self.items, self.annotations, self.rows = [], [], [], [], []
        self.locations = []
        self.consumers = {}   # (sheet id, ref) -> [(consumer id, role, primary)]

    def consume(self, sheet_id, ref, consumer, role, primary=True):
        self.consumers.setdefault((sheet_id, ref), []).append((consumer, role, primary))

    def item(self, item_id):
        return next(item for item in self.items if item['id'] == item_id)

    def section(self, section_id):
        return next(section for section in self.sections if section['id'] == section_id)


def flag(record, code, detail):
    record['flags'].append({'code': code, 'detail': detail})


def build_quantity(key, cell, label_from_qty):
    """
    Returns (quantity, label taken from the cell or None, inherit the label from the context?).
    `label_from_qty` is true for rows whose column A is empty or a heading: there the cell names the thing.
    """
    quantity = {'raw': cell['value'] if cell else None, 'parts': [], 'total': None, 'unit': None,
                'unit_canonical': None, 'approx': False, 'implied': False, 'rule': None}
    label, inherit, flags = None, False, []
    override = QTY_OVERRIDES.get(key)
    if cell is None:
        if override:
            fail(f'{key}: quantity override on an empty cell')
        quantity['rule'] = 'empty'
    elif override:
        raw_numbers = sorted(fr_number(n) for n in re.findall(NUMBER, str(cell['value'])))
        stated = [str(p[k]).replace('.', ',') for p in override['parts'] for k in ('n', 'n_max', 'dimension')
                  if p[k] is not None]
        used = sorted(fr_number(n) for n in re.findall(NUMBER, ' '.join(stated)))
        if override['parts'] and raw_numbers != used:
            fail(f'{key}: quantity override {used} does not match the numbers in {cell["value"]!r} {raw_numbers}')
        quantity['parts'] = [dict(p) for p in override['parts']]
        quantity['rule'] = f'override: {override["reason"]}'
        flags = list(override.get('flags', []))
        label = override.get('label')
        inherit = label_from_qty and label is None and bool(override['parts'])
    elif cell['type'] == 'n':
        if label_from_qty:
            fail(f'{key}: a bare number where a label was expected')
        quantity['parts'], quantity['rule'] = [part(cell['value'])], 'number'
    else:
        parsed = parse_qty_text(cell['value'])
        if parsed is None:
            if not label_from_qty:
                fail(f'{key}: cannot read the quantity {cell["value"]!r}; add a QTY_OVERRIDES entry')
            label, quantity['implied'], quantity['rule'] = norm_ws(cell['value']), True, 'name only'
        else:
            one, rest = parsed
            if label_from_qty:
                if not rest:
                    fail(f'{key}: {cell["value"]!r} has a number but no label; add a QTY_OVERRIDES entry')
                if rest.lower() in CONTAINER_UNITS:
                    one['unit'], inherit, quantity['rule'] = rest, True, 'number + container'
                else:
                    label, quantity['rule'] = rest, 'number + label'
            else:
                one['unit'], quantity['rule'] = rest or None, 'number + unit' if rest else 'number'
            quantity['parts'] = [one]
    parts = quantity['parts']
    if parts:
        units = {p['unit'] for p in parts}
        quantity['approx'] = any(p['approx'] for p in parts)
        ranged = any(p['n_max'] is not None for p in parts)
        if ranged:
            flags.append(('QTY_RANGE', f'{cell["value"]!r} is a range; no total is given'))
        if len(units) > 1:
            flags.append(('QTY_HETEROGENEOUS', f'{cell["value"]!r} counts different things; no total is given'))
        if len(units) == 1:
            quantity['unit'] = next(iter(units))
            quantity['unit_canonical'] = UNIT_CANONICAL.get((quantity['unit'] or '').lower())
            if not ranged:
                quantity['total'] = sum(p['n'] for p in parts)
    return quantity, label, inherit, flags


def build_locations(key, marks, columns):
    by_col = {column['col']: column for column in columns}
    locations = []
    for col in sorted(marks, key=col_index):
        value, column = marks[col]['value'], by_col[col]
        entry = {'col': col, 'location': column['id'], 'room': column['room'], 'spot': column['spot'],
                 'mark_raw': value, 'mark_kind': None, 'qty': None, 'qty_unit': None}
        if value == 'X':
            entry['mark_kind'] = 'presence'
        elif marks[col]['type'] == 'n':
            entry['mark_kind'], entry['qty'] = 'count', value
        else:
            parsed = re.fullmatch(r'(?:dont )?(\d+)(?: (\w+))?', norm_ws(value))
            if not parsed:
                fail(f'{key}: cannot read the location mark {value!r} in column {col}')
            entry['mark_kind'], entry['qty'], entry['qty_unit'] = 'text', int(parsed.group(1)), parsed.group(2)
        locations.append(entry)
    return locations


HOLDER_RE = re.compile(r'(?:dont (\d+) )?chez (.+?)\s*$')


def find_holder(sources):
    for text, where in sources:
        match = HOLDER_RE.search(text or '')
        if match:
            return {'who_raw': match.group(2), 'qty': int(match.group(1)) if match.group(1) else None, 'source': where}
    return None


def parse_comment(raw):
    """Google Sheets writes '======\\nID#...\\nAuthor    (date)\\nbody' into the exported comment."""
    match = re.fullmatch(r'======\nID#(\S+)\n(.+?)\s+\((\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\)\n(.*)', raw, re.S)
    if not match:
        return {'author': None, 'dated': None, 'text': raw.strip()}
    return {'author': match.group(2), 'dated': match.group(3), 'text': match.group(4).strip()}


def suggest_fix(text):
    fixed = text
    for wrong, right in TYPO_FIXES:
        fixed = fixed.replace(wrong, right)
    return fixed if fixed != text else None


# ───────────────────────────── records ─────────────────────────────

def make_item(ex, sheet, header, r, kind, cells, stack, context, label_from, comments_by_ref):
    """One record for one source line. `label_from` is 'A' (own label) or 'B' (label in the quantity cell)."""
    sid = sheet['id']
    key = (sid, r)
    item_id = f'{sid}:r{r}'
    a, b, c = cells.get(header['label_col']), cells.get(header['qty_col']), cells.get(header['remark_col'])
    material = cells.get(header['material_col']) if header['material_col'] else None
    marks = {column['col']: cells[column['col']] for column in header['columns'] if column['col'] in cells}

    item = {'id': item_id, 'sheet': sheet['name'], 'row': r, 'kind': kind, 'canonical': True,
            'section_path': [section['id'] for section in stack],
            'typology': None, 'category': None, 'subcategory': None, 'group': None,
            'context': None, 'number_raw': None,
            'raw': {'label': a['value'] if a else None, 'quantity': b['value'] if b else None,
                    'remark': c['value'] if c else None, 'material': material['value'] if material else None,
                    'marks': {col: cell['value'] for col, cell in marks.items()}},
            'cells': {}, 'label': None, 'quantity': None, 'remark': norm_ws(c['value']) if c else None,
            'locations': [], 'location_not_applicable': False, 'status': 'active', 'disposition': 'club',
            'holder': None, 'format': {'struck': [], 'italic': []}, 'comments': [], 'links': [], 'derived': {},
            'flags': []}
    for section in stack:
        item[section['level']] = section['label']
        if (sid, section['row']) in SECTION_DISPOSITION and section['id'].startswith(sid):
            item['disposition'] = SECTION_DISPOSITION[(sid, section['row'])]

    quantity, qty_label, inherit, qty_flags = build_quantity(key, b, label_from == 'B')
    item['quantity'] = quantity
    if label_from == 'A':
        code, text = split_code(a['value'])
        item['number_raw'] = code
        item['label'] = {'text': norm_ws(text), 'origin': 'label_cell', 'suggested': None}
    else:
        if context is None:
            fail(f'{key}: a row without a label and nothing above it to continue')
        item['context'] = {'kind': context['kind'], 'id': context['id']}
        if context['kind'] == 'item':
            item['links'].append({'rel': 'continues', 'target': context['id'], 'evidence': 'column A is empty'})
        if qty_label is not None:
            item['label'] = {'text': norm_ws(qty_label), 'origin': 'qty_cell', 'suggested': None}
        elif inherit:
            item['label'] = {'text': context['label'], 'origin': 'context', 'suggested': None}
        else:
            fail(f'{key}: no label could be derived')
    item['label']['suggested'] = suggest_fix(item['label']['text'])
    if item['label']['suggested']:
        flag(item, 'TYPO_SUGGESTION', f'{item["label"]["text"]!r} -> {item["label"]["suggested"]!r}')
    for code, detail in qty_flags:
        flag(item, code, detail)

    item['locations'] = build_locations(key, marks, header['columns'])
    loc_cols = [column['col'] for column in header['columns']]
    if loc_cols and all(sheet['empty_fills'].get(f'{col}{r}') == GREY for col in loc_cols):
        item['location_not_applicable'] = True

    # which cells this record is made of
    roles = [(header['label_col'], a, 'label'), (header['qty_col'], b, 'quantity'), (header['remark_col'], c, 'remark')]
    if material:
        roles.append((header['material_col'], material, 'material'))
    roles += [(col, cell, 'mark') for col, cell in marks.items()]
    for col, cell, role in roles:
        if cell is None:
            continue
        owned = not (role == 'label' and kind in ('heading_item', 'heading_mark', 'heading_self_item'))
        if owned:
            item['cells'][cell['ref']] = cell['value']
        ex.consume(sid, cell['ref'], item_id, role, primary=owned)
        if cell['style']['strike']:
            item['format']['struck'].append(cell['ref'])
        if cell['style']['i'] and role != 'label':
            item['format']['italic'].append(cell['ref'])
        if cell['ref'] in comments_by_ref:
            item['comments'].append(dict(comments_by_ref[cell['ref']], cell=cell['ref']))
    for refs in item['format'].values():
        refs.sort(key=lambda ref: col_index(split_ref(ref)[0]))
    known = {col for col, _, _ in roles}
    for col in cells:
        if col not in known and col != header['label_col']:
            fail(f'{sheet["name"]}!{col}{r}: a value in a column the header does not define')

    # status
    qty_cols = (header['qty_col'], header['material_col'])
    struck = [ref for ref in item['format']['struck'] if split_ref(ref)[0] in qty_cols]
    if struck:
        item['status'] = 'struck'
        flag(item, 'STRUCK_THROUGH', f'{", ".join(struck)} struck through: lost or removed')
    elif quantity['total'] == 0:
        item['status'] = 'zero'
        flag(item, 'QTY_ZERO', 'the sheet counts zero of these')
    elif kind == 'placeholder':
        item['status'] = 'placeholder'

    # holder
    sources = [(item['remark'], f'{sheet["name"]}!{c["ref"]}' if c else None)]
    sources += [(comment['text'], f'comment on {sheet["name"]}!{comment["cell"]}') for comment in item['comments']]
    if label_from == 'A':
        sources.append((item['label']['text'], f'{sheet["name"]}!{a["ref"]}'))
    item['holder'] = find_holder(sources)

    # flags that follow from the above
    if item['status'] == 'active':
        if not quantity['parts'] and not quantity['implied'] and not any(
                f['code'] in ('QTY_FREE_TEXT', 'QTY_NOT_A_QUANTITY') for f in item['flags']):
            flag(item, 'QTY_MISSING', 'no quantity in the sheet')
        whole_holder = item['holder'] and item['holder']['qty'] is None
        if item['location_not_applicable']:
            flag(item, 'LOC_NOT_APPLICABLE', 'location cells are greyed out in the sheet')
        elif not item['locations'] and whole_holder:
            flag(item, 'LOC_OFFSITE',
                 f'no location mark; held "chez {item["holder"]["who_raw"]}" ({item["holder"]["source"]})')
        elif not item['locations']:
            flag(item, 'LOC_MISSING', 'no location mark in the sheet')
        if item['holder'] and item['holder']['qty'] is not None:
            flag(item, 'PARTLY_OFFSITE',
                 f'{item["holder"]["qty"]} held "chez {item["holder"]["who_raw"]}" ({item["holder"]["source"]})')
    kinds = [loc['mark_kind'] for loc in item['locations']]
    if kinds.count('presence') > 1 and (quantity['total'] is None or quantity['total'] > 1):
        flag(item, 'LOC_SPLIT_UNCLEAR', f'in {len(kinds)} places with no count per place')
    if 'presence' in kinds and len(set(kinds)) > 1:
        partial = ', '.join(f'{loc["col"]}{r}={loc["mark_raw"]!r}' for loc in item['locations']
                            if loc['mark_kind'] != 'presence')
        flag(item, 'LOC_PARTIAL_MARK', f'{partial} beside an X: the rest is at the X')
    if kinds and all(k == 'count' for k in kinds):
        counted = sum(loc['qty'] for loc in item['locations'])
        if counted != quantity['total']:
            flag(item, 'LOC_COUNT_MISMATCH', f'marks add up to {counted}, quantity is {quantity["raw"]!r}; '
                                             f'the marks may count something else (remark: {item["remark"]!r})')
    if kind == 'heading_mark':
        flag(item, 'HEADING_HAS_MARK', 'a location mark on a heading row: unclear what it locates')
    for code, detail in MANUAL_FLAGS.get(key, []):
        flag(item, code, detail)
    for rel, target, evidence in MANUAL_LINKS.get(key, []):
        item['links'].append({'rel': rel, 'target': target, 'evidence': evidence})

    ex.items.append(item)
    return item


def check_numbering(record, code, parent, last_code):
    if code is None:
        return
    numbers = tuple(int(n) for n in code.split('.'))
    parent_code = parent['number_raw'] if parent else None
    if parent_code and parent['level'] != 'typology' and not code.startswith(parent_code + '.'):
        flag(record, 'NUMBERING_MISMATCH', f'{code} sits under {parent_code} ({parent["label"]!r})')
    slot = parent['id'] if parent else None
    previous = last_code.get(slot)
    if previous and numbers < previous[0]:
        flag(record, 'NUMBERING_OUT_OF_ORDER', f'{code} comes after {previous[1]}')
    last_code[slot] = (numbers, code)


def process_feuil1(ex, sheet):
    sid, rows = sheet['id'], sheet['rows']
    headers = find_headers(sheet, ex.locations)
    header_of = {r: header for header in headers for r in header['rows']}
    comments_by_ref = {c['ref']: parse_comment(c['raw']) for c in sheet['comments']}
    labelled = sorted(r for r in rows if 'A' in rows[r] and r not in header_of)
    stack, context, header, last_code = [], None, None, {}

    def new_section(r, level, cell, code, text):
        section = {'id': f'{sid}:s{r}', 'sheet': sheet['name'], 'row': r, 'level': level,
                   'parent': stack[-1]['id'] if stack else None, 'number_raw': code, 'label_raw': cell['value'],
                   'label': norm_ws(text), 'label_suggested': suggest_fix(norm_ws(text)), 'flags': []}
        if section['label_suggested']:
            flag(section, 'TYPO_SUGGESTION', f'{section["label"]!r} -> {section["label_suggested"]!r}')
        ex.sections.append(section)
        return section

    for r in sorted(rows):
        cells = rows[r]
        if r in header_of:
            header = header_of[r]
            for cell in cells.values():
                ex.consume(sid, cell['ref'], header['id'], 'header')
            if r == header['row']:
                code, text = split_code(cells['A']['value'])
                repeat = bool(stack) and stack[0]['label'] == norm_ws(text)
                if not repeat:
                    stack.clear()
                    section = new_section(r, 'typology', cells['A'], code, text)
                    stack.append(section)
                    ex.consume(sid, cells['A']['ref'], section['id'], 'section_label', primary=False)
                    context = None
                ex.rows.append({'sheet': sheet['name'], 'row': r, 'kind': 'header',
                                'reason': ('header block, repeated for printing' if repeat
                                           else 'header block; starts a typology'),
                                'records': [header['id']] + ([] if repeat else [stack[0]['id']])})
            else:
                ex.rows.append({'sheet': sheet['name'], 'row': r, 'kind': 'header',
                                'reason': 'room row' if r == header['row'] + 1 else 'spot row',
                                'records': [header['id']]})
            continue

        a, b, c = cells.get('A'), cells.get(header['qty_col']), cells.get(header['remark_col'])
        marks = [column['col'] for column in header['columns'] if column['col'] in cells]
        has_data = bool(b or c or marks)
        records = []
        if a is None:
            if b is None:
                fail(f'{sheet["name"]} row {r}: no label and no quantity cell')
            if r - 1 not in rows:
                fail(f'{sheet["name"]} row {r}: a row without a label after a blank row')
            kind = 'continuation'
            reason = f'column A is empty: continues {context["id"]} ({context["label"]!r})'
            item = make_item(ex, sheet, header, r, kind, cells, stack, context, 'B', comments_by_ref)
            records.append(item['id'])
        else:
            code, text = split_code(a['value'])
            level = text_level(a)
            if level not in ('category', 'subcategory', 'plain'):
                fail(f'{sheet["name"]}!A{r}: unexpected style {level!r} for a label')
            override = ROW_OVERRIDES.get((sid, r))
            if override:
                kind, reason = override
                reason = f'override: {reason}'
            elif level != 'plain':
                if not has_data:
                    kind, reason = 'section', f'{level} heading (font style), no data on the row'
                elif b is not None and b['type'] == 'n':
                    kind, reason = 'item', f'{level}-styled row with a numeric quantity: a leaf item, not a heading'
                else:
                    kind, reason = 'heading_item', f'{level} heading that also carries the first item of its section'
            elif not has_data:
                following = [n for n in labelled if n > r]
                next_code = split_code(rows[following[0]]['A']['value'])[0] if following else None
                if code and next_code and next_code.startswith(code + '.'):
                    kind = 'group'
                    reason = f'plain label with no data whose numbering is extended by row {following[0]}'
                else:
                    kind, reason = 'placeholder', 'plain label with no quantity, remark or location'
            else:
                kind, reason = 'item', 'plain label with data'

            if level != 'plain':
                while stack and LEVELS[stack[-1]['level']] >= LEVELS[level]:
                    stack.pop()
            else:
                while stack and stack[-1]['level'] == 'group' and not (
                        code and code.startswith(stack[-1]['number_raw'] + '.')):
                    stack.pop()
            parent = stack[-1] if stack else None

            section = None
            if kind in ('section', 'group', 'heading_item', 'heading_mark', 'heading_self_item'):
                section = new_section(r, 'group' if kind == 'group' else level, a, code, text)
                check_numbering(section, code, parent, last_code)
                stack.append(section)
                ex.consume(sid, a['ref'], section['id'], 'section_label')
                records.append(section['id'])
            if kind == 'heading_item':
                context = {'kind': 'section', 'id': section['id'], 'label': section['label']}
                item = make_item(ex, sheet, header, r, kind, cells, stack, context, 'B', comments_by_ref)
                records.append(item['id'])
            elif kind in ('item', 'placeholder', 'heading_mark', 'heading_self_item'):
                item = make_item(ex, sheet, header, r, kind, cells, stack, None, 'A', comments_by_ref)
                if section is None:
                    check_numbering(item, code, parent, last_code)
                context = {'kind': 'item', 'id': item['id'], 'label': item['label']['text']}
                records.append(item['id'])
            else:
                context = {'kind': 'section', 'id': section['id'], 'label': section['label']}
        ex.rows.append({'sheet': sheet['name'], 'row': r, 'kind': kind, 'reason': reason, 'records': records})

    # numbering used more than once
    by_code, section_ids = {}, {section['id'] for section in ex.sections}
    for record in ex.sections + ex.items:
        # an item made from a heading row shares that heading's number: one use, not two
        own_heading = record['id'].startswith(f'{sid}:r') and f'{sid}:s{record["row"]}' in section_ids
        if record['id'].startswith(sid) and record.get('number_raw') and record.get('level') != 'typology' \
                and not own_heading:
            by_code.setdefault(record['number_raw'], []).append(record)
    for code, records in by_code.items():
        if len(records) > 1:
            for record in records:
                others = ', '.join(f'row {o["row"]}' for o in records if o is not record)
                flag(record, 'NUMBERING_DUPLICATE', f'{code} is also used at {others}')
    return headers, comments_by_ref


def process_nappes(ex, sheet):
    """Thirteen tablecloth rows under one header; each refines a Feuil1 row with the same numbering."""
    sid, rows = sheet['id'], sheet['rows']
    headers = find_headers(sheet, ex.locations)
    if len(headers) != 1 or headers[0]['material_col'] is None:
        fail('Nappes: expected one header block with a Matériau column')
    header = headers[0]
    comments_by_ref = {c['ref']: parse_comment(c['raw']) for c in sheet['comments']}
    by_code = {}
    for item in ex.items:
        if item['sheet'] == 'Feuil1' and item['number_raw'] and item['subcategory'] == 'nappe de jeu':
            by_code.setdefault(item['number_raw'], []).append(item)
    for r in sorted(rows):
        cells = rows[r]
        if r in header['rows']:
            for cell in cells.values():
                ex.consume(sid, cell['ref'], header['id'], 'header')
            ex.rows.append({'sheet': sheet['name'], 'row': r, 'kind': 'header', 'reason': 'header block',
                            'records': [header['id']]})
            continue
        if 'A' not in cells or text_level(cells['A']) != 'plain':
            fail(f'Nappes row {r}: expected a plain labelled row')
        code = split_code(cells['A']['value'])[0]
        targets = by_code.get(code, [])
        if len(targets) != 1:
            fail(f'Nappes row {r}: numbering {code!r} matches {len(targets)} Feuil1 tablecloth rows')
        target = targets[0]
        stack = [ex.section(section_id) for section_id in target['section_path']]
        item = make_item(ex, sheet, header, r, 'item', cells, stack, None, 'A', comments_by_ref)
        item['links'].append({'rel': 'refines', 'target': target['id'], 'evidence': f'same numbering {code}'})
        target['links'].append({'rel': 'refined_by', 'target': item['id'], 'evidence': f'same numbering {code}'})
        target['canonical'] = False
        ex.rows.append({'sheet': sheet['name'], 'row': r, 'kind': 'item', 'reason': f'refines {target["id"]}',
                        'records': [item['id']]})
    return headers, comments_by_ref


def reconcile_nappes(ex):
    """Nappes and Feuil1 describe the same tablecloths: say where they disagree instead of picking silently."""
    for target in [item for item in ex.items if any(link['rel'] == 'refined_by' for link in item['links'])]:
        refiners = [ex.item(link['target']) for link in target['links'] if link['rel'] == 'refined_by']
        ids = ', '.join(i['id'] for i in refiners)
        labels = {i['label']['text'] for i in refiners}
        if labels != {target['label']['text']}:
            said = ', '.join(sorted(map(repr, labels)))
            detail = f'{target["id"]} says {target["label"]["text"]!r}, {ids} say {said}'
            for record in [target] + refiners:
                flag(record, 'CONFLICT_SIZE' if '(' in target['label']['text'] else 'CONFLICT_LABEL', detail)
        total = sum(i['quantity']['total'] for i in refiners)
        if total != target['quantity']['total']:
            for record in [target] + refiners:
                flag(record, 'CONFLICT_QTY',
                     f'{target["id"]} counts {target["quantity"]["total"]}, {ids} add up to {total}')
        places = {loc['location'] for i in refiners for loc in i['locations']}
        if places != {loc['location'] for loc in target['locations']}:
            for record in [target] + refiners:
                flag(record, 'CONFLICT_LOCATION', f'{target["id"]} and {ids} are not marked in the same places')
        # material: the Feuil1 wording (label, or the qualifier of the matching part) against the Matériau column
        for refiner in refiners:
            wording = target['label']['text']
            matching = [p for p in target['quantity']['parts']
                        if p['qualifier'] and p['n'] == refiner['quantity']['total']]
            if len(target['quantity']['parts']) > 1 and len(matching) == 1:
                wording = matching[0]['qualifier']
            expected = next((mat for word, mat in WORDING_MATERIAL.items() if word in wording.lower()), None)
            if expected and expected != refiner['raw']['material']:
                detail = (f'{target["id"]} says {wording!r}, {refiner["id"]} says Matériau = '
                          f'{refiner["raw"]["material"]!r}')
                flag(target, 'CONFLICT_MATERIAL', detail)
                flag(refiner, 'CONFLICT_MATERIAL', detail)


# ───────────────────────────── derived layer ─────────────────────────────

def derive(ex):
    sections = {section['id']: section for section in ex.sections}
    for item in ex.items:
        derived, text = {}, item['label']['text']
        # size
        match = re.search(r'\((\d+(?:,\d+)?|\?)x(\d+(?:,\d+)?|\?)\)', text)
        if match and '?' in match.groups():
            flag(item, 'SIZE_UNKNOWN', f'the sheet gives the size as {match.group(0)}')
        elif match:
            derived['size_cm'] = {'value': [round(fr_number(g) * 100) for g in match.groups()],
                                  'rule': 'size_in_parentheses_is_metres', 'source': text}
        else:
            match = re.search(r'(?<![\d,])(\d{2,3})x(\d{2,3})(?![\d,])', text)
            if match:
                derived['size_cm'] = {'value': [int(g) for g in match.groups()],
                                      'rule': 'bare_size_is_centimetres', 'source': text}
        # scale: the item's own label first, then the nearest heading that states one
        for source_id, source_text, rule in [(item['id'], text, 'scale_in_label')] + [
                (sid, sections[sid]['label'], 'scale_in_heading') for sid in reversed(item['section_path'])]:
            match = re.search(r'\+?\d+mm', source_text)
            if match:
                derived['scale'] = {'value': match.group(0), 'rule': rule, 'source': source_id}
                break
        if item['raw']['material'] in MATERIAL_APP:
            derived['material'] = {'value': MATERIAL_APP[item['raw']['material']],
                                   'rule': 'nappes_material_to_app_value', 'source': item['raw']['material']}
        suggestion = suggest_type(item)
        if suggestion:
            derived['suggested_app_type'] = {'value': suggestion[0], 'rule': suggestion[1]}
        item['derived'] = derived


def suggest_type(item):
    """Which of the application's eight item types this line would be. A suggestion, never a fact."""
    if any(f['code'] in ('TYPE_UNCLEAR', 'ROW_UNCLEAR', 'HEADING_HAS_MARK') for f in item['flags']):
        return None
    category, sub = item['category'] or '', item['subcategory'] or ''
    label = item['label']['text'].lower()
    if item['typology'] == 'Consommable':
        return 'consumable', 'T1 typology Consommable'
    if sub == 'nappe de jeu':
        return 'tablecloth', 'T2 sub-category nappe de jeu'
    if sub == 'plaques modulaires' or category == 'décors de jeu':
        return 'terrain', 'T3 modular boards and scenery'
    if category == 'jeux de figurines':
        if 'règle' in label or 'extension' in label:
            return 'rulebook', 'T4a label says règle or extension'
        if re.search(r'\bdés\b', label):
            return 'equipment', 'T4b dice'
        if label.startswith('décors'):
            return 'terrain', 'T4c label starts with Décors'
        return 'miniature', 'T4d under jeux de figurines'
    if category == 'jeux':
        if sub == 'Régles' or '= règle' in label:
            return 'rulebook', 'T5a rules'
        return 'board_game', 'T5b boxed game'
    if category in ('appareils', 'matériel divers', 'matériel peinture'):
        return 'equipment', 'T6 equipment'
    if category == 'cadeaux potentiels':
        mapping = {'règle': 'rulebook', 'jeu': 'board_game', 'figurines': 'miniature', 'autres': 'equipment'}
        if sub in mapping:
            return mapping[sub], f'T7 cadeaux potentiels / {sub}'
    if category.startswith('stock de'):
        return 'miniature', 'T8 stock of figurines'
    return None


# ───────────────────────────── annotations and checks ─────────────────────────────

def annotate(ex, sheets, comments):
    stamps = set()
    for sheet in sheets:
        sid = sheet['id']
        for box in sheet['boxes']:
            stamp = re.fullmatch(r'inventaire du\s*(\d\d)/(\d\d)/(\d\d)', norm_ws(box['text']))
            note = {'id': f'{sid}:box:{box["ref"]}', 'kind': 'stamp' if stamp else 'textbox', 'sheet': sheet['name'],
                    'anchor': box['ref'], 'text': box['text'], 'author': None, 'dated': None, 'item': None,
                    'section': None}
            if stamp:
                note['dated'] = f'20{stamp.group(3)}-{stamp.group(2)}-{stamp.group(1)}'
                stamps.add(note['dated'])
            else:
                if (sid, box['ref']) not in TEXTBOX_SECTION:
                    fail(f'{sheet["name"]}: text box at {box["ref"]} has no entry in TEXTBOX_SECTION')
                note['section'] = ex.section(TEXTBOX_SECTION[(sid, box['ref'])])['id']
            ex.annotations.append(note)
        for ref, comment in comments[sid].items():
            owners = [item['id'] for item in ex.items if any(c['cell'] == ref for c in item['comments'])
                      and item['sheet'] == sheet['name']]
            if len(owners) != 1:
                fail(f'{sheet["name"]}!{ref}: the comment belongs to {len(owners)} items')
            ex.annotations.append({'id': f'{sid}:comment:{ref}', 'kind': 'comment', 'sheet': sheet['name'],
                                   'anchor': ref, 'text': comment['text'], 'author': comment['author'],
                                   'dated': comment['dated'], 'item': owners[0], 'section': None})
        # fills on cells without a value
        for fill in sorted(set(sheet['empty_fills'].values())):
            refs = sorted((ref for ref, f in sheet['empty_fills'].items() if f == fill),
                          key=lambda x: (split_ref(x)[1], col_index(split_ref(x)[0])))
            rows = {split_ref(ref)[1] for ref in refs}
            owners = [item['id'] for item in ex.items if item['sheet'] == sheet['name'] and item['row'] in rows
                      and item['location_not_applicable']]
            if fill != GREY or len(rows) != 1 or len(owners) != 1:
                fail(f'{sheet["name"]}: fill {fill} on {refs} is not understood')
            ex.annotations.append({'id': f'{sid}:fill:{refs[0]}', 'kind': 'fill', 'sheet': sheet['name'],
                                   'anchor': f'{refs[0]}:{refs[-1]}',
                                   'text': f'grey fill ({fill}): location not applicable',
                                   'author': None, 'dated': None, 'item': owners[0], 'section': None})
    return sorted(stamps)


def verify(ex, sheets, headers):
    """Nothing in the workbook may be left unexplained. Returns the per-cell audit trail."""
    source_cells = []
    for sheet in sheets:
        sid = sheet['id']
        header_rows = {r for header in headers.get(sid, []) for r in header['rows']}
        for ref, cell in sheet['cells'].items():
            key = style_key(cell['style'])
            if key not in KNOWN_STYLES:
                fail(f'{sheet["name"]}!{ref}: unknown style {key}')
            users = ex.consumers.get((sid, ref), [])
            primary = [u for u in users if u[2]]
            if len(primary) != 1:
                fail(f'{sheet["name"]}!{ref} = {cell["value"]!r} has {len(primary)} primary consumers (expected 1)')
            if cell['style']['strike']:
                owner = ex.item(primary[0][0]) if primary[0][0] in {i['id'] for i in ex.items} else None
                if owner is None or owner['status'] != 'struck':
                    fail(f'{sheet["name"]}!{ref} is struck through but its record is not marked struck')
            if cell['style']['fill'] and not (cell['style']['fill'] == YELLOW and cell['row'] in header_rows):
                fail(f'{sheet["name"]}!{ref}: fill {cell["style"]["fill"]} is not understood')
            if KNOWN_STYLES[key] == 'typology' and cell['row'] not in header_rows:
                fail(f'{sheet["name"]}!{ref}: typology style outside a header block')
            style = cell['style']
            source_cells.append({'sheet': sheet['name'], 'ref': ref, 'value': cell['value'], 'type': cell['type'],
                                 'style': style_letters(style),
                                 'color': style['color'], 'fill': style['fill'],
                                 'role': primary[0][1], 'consumer': primary[0][0],
                                 'also': [u[0] for u in users if not u[2]]})
        for rng in sheet['merges']:
            if {split_ref(ref)[1] for ref in range_refs(rng)} - header_rows:
                fail(f'{sheet["name"]}: merge {rng} outside a header block')
        if not sheet['cells'] and (sheet['merges'] or sheet['comments'] or sheet['boxes'] or sheet['empty_fills']):
            fail(f'{sheet["name"]}: an empty sheet that still holds merges, comments, drawings or fills')
        noted = {a['anchor'] for a in ex.annotations if a['sheet'] == sheet['name']}
        for box in sheet['boxes']:
            if box['ref'] not in noted:
                fail(f'{sheet["name"]}: text box at {box["ref"]} is not recorded')
        for comment in sheet['comments']:
            if comment['ref'] not in noted:
                fail(f'{sheet["name"]}: comment at {comment["ref"]} is not recorded')

        # rebuild the grid from the records alone and compare it with the sheet
        rebuilt = {}
        for header in ex.headers:
            if header['sheet'] == sheet['name']:
                rebuilt.update(header['cells'])
        for section in ex.sections:
            if section['sheet'] == sheet['name'] and section['level'] != 'typology':
                rebuilt[f'A{section["row"]}'] = section['label_raw']
        for item in ex.items:
            if item['sheet'] == sheet['name']:
                clash = set(item['cells']) & set(rebuilt)
                if clash:
                    fail(f'{sheet["name"]}: cells {sorted(clash)} are claimed twice')
                rebuilt.update(item['cells'])
        original = {ref: cell['value'] for ref, cell in sheet['cells'].items()}
        if rebuilt != original:
            diff = sorted(set(rebuilt.items()) ^ set(original.items()))
            fail(f'{sheet["name"]}: the grid rebuilt from the records differs from the sheet: {diff[:6]}')

        # every non-empty row is classified exactly once
        classified = [row['row'] for row in ex.rows if row['sheet'] == sheet['name']]
        if sorted(classified) != sorted(sheet['rows']):
            fail(f'{sheet["name"]}: classified rows do not match the non-empty rows')
    source_cells.sort(key=lambda c: (list(SHEET_IDS).index(c['sheet']), split_ref(c['ref'])[1],
                                     col_index(split_ref(c['ref'])[0])))
    return source_cells


def check_tsv(sheets, folder):
    """The old flat exports hold the same values; only the known cells may differ."""
    ok = True
    for sheet in sheets:
        filename = TSV_FILES.get(sheet['name'])
        if filename is None:
            continue
        path = folder / filename
        if not path.exists():
            print(f'  tsv check: {path.name} not found, skipped')
            continue
        tsv = {}
        for r, line in enumerate(csv.reader(io.StringIO(path.read_text(encoding='utf-8')), delimiter='\t'), 1):
            for c, value in enumerate(line, 1):
                if value != '':
                    tsv[f'{col_name(c)}{r}'] = value
        xlsx = {ref: str(cell['value']) for ref, cell in sheet['cells'].items()}
        differing = {(sheet['name'], ref) for ref in set(tsv) | set(xlsx) if tsv.get(ref) != xlsx.get(ref)}
        expected = {d for d in KNOWN_TSV_DIFFS if d[0] == sheet['name']}
        status = 'as expected' if differing == expected else 'UNEXPECTED'
        ok = ok and differing == expected
        print(f'  tsv check: {sheet["name"]}: {len(xlsx)} xlsx cells, {len(tsv)} tsv cells, '
              f'{len(differing)} differing ({status}): {sorted(ref for _, ref in differing)}')
    return ok


# ───────────────────────────── assembly ─────────────────────────────

def extract(path):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        fail(f'{path.name} is not the file these rules were written for (sha256 {digest}). '
             f'Check every rule against the new file before changing EXPECTED_SHA256.')
    sheets = read_workbook(path)
    by_name = {sheet['name']: sheet for sheet in sheets}
    if list(by_name) != list(SHEET_IDS):
        fail(f'unexpected sheets {list(by_name)}')

    ex = Extraction()
    headers, comments = {}, {sheet['id']: {} for sheet in sheets}

    # locations, from the first header block; every other block must agree
    first = find_headers(by_name['Feuil1'])[0]
    for order, column in enumerate(first['columns'], 1):
        room = ROOM_FIXES.get(column['room_raw'], column['room_raw'])
        ex.locations.append({'id': f'{slug(room)}/{slug(column["spot_raw"])}', 'order': order,
                             'room_raw': column['room_raw'], 'room': room, 'spot_raw': column['spot_raw'],
                             'spot': norm_ws(column['spot_raw']), 'columns': {}})
    signature = [(loc['room_raw'], loc['spot_raw']) for loc in ex.locations]
    for name in ('Feuil1', 'Nappes'):
        for header in find_headers(by_name[name]):
            if [(c['room_raw'], c['spot_raw']) for c in header['columns']] != signature:
                fail(f'{name}: the header at row {header["row"]} does not list the same locations as Feuil1 row 1')
    headers['F1'], comments['F1'] = process_feuil1(ex, by_name['Feuil1'])
    headers['NA'], comments['NA'] = process_nappes(ex, by_name['Nappes'])
    for name in ('Feuil2', 'Feuil3'):
        if by_name[name]['cells']:
            fail(f'{name} is expected to be empty')

    for sid, found in headers.items():
        sheet = next(s for s in sheets if s['id'] == sid)
        for header in found:
            ex.headers.append({'id': header['id'], 'sheet': sheet['name'], 'rows': header['rows'],
                               'label_col': header['label_col'], 'qty_col': header['qty_col'],
                               'remark_col': header['remark_col'], 'material_col': header['material_col'],
                               'inherited_from': header.get('inherited_from'),
                               'location_columns': {c['col']: c['id'] for c in header['columns']},
                               'cells': {cell['ref']: cell['value'] for r in header['rows']
                                         for cell in sheet['rows'][r].values()},
                               'merges': [rng for rng in sheet['merges']
                                          if split_ref(range_refs(rng)[0])[1] in header['rows']]})
    reconcile_nappes(ex)
    derive(ex)
    stamps = annotate(ex, sheets, comments)
    source_cells = verify(ex, sheets, headers)
    if len(stamps) != 1:
        fail(f'expected one inventory date on the stamps, found {stamps}')

    meta = {
        'schema_version': SCHEMA_VERSION,
        'generator': 'misc/extract_inventory_xlsx.py',
        'source': {'file': path.name, 'sha256': digest, 'bytes': len(data)},
        'inventory_date': stamps[0],
        'comment_dates': sorted({a['dated'] for a in ex.annotations if a['kind'] == 'comment' and a['dated']}),
        'sheets': [{'name': sheet['name'], 'id': sheet['id'], 'non_empty_rows': len(sheet['rows']),
                    'value_cells': len(sheet['cells']), 'merges': len(sheet['merges']),
                    'comments': len(sheet['comments']), 'text_boxes': len(sheet['boxes']),
                    'struck_cells': sorted((ref for ref, c in sheet['cells'].items() if c['style']['strike']),
                                           key=lambda x: (split_ref(x)[1], x)),
                    'headers': sum(1 for h in ex.headers if h['sheet'] == sheet['name']),
                    'sections': sum(1 for s in ex.sections if s['sheet'] == sheet['name']),
                    'items': sum(1 for i in ex.items if i['sheet'] == sheet['name'])} for sheet in sheets],
        'counts': {'items': len(ex.items), 'canonical_items': sum(1 for i in ex.items if i['canonical']),
                   'by_status': {status: sum(1 for i in ex.items if i['status'] == status)
                                 for status in ('active', 'struck', 'placeholder', 'zero')},
                   'flags': sum(len(i['flags']) for i in ex.items) + sum(len(s['flags']) for s in ex.sections)},
    }
    return {'meta': meta, 'decisions': [{'id': d[0], 'rule': d[1], 'rationale': d[2]} for d in DECISIONS],
            'locations': ex.locations, 'headers': ex.headers, 'sections': ex.sections, 'items': ex.items,
            'annotations': ex.annotations, 'rows': ex.rows, 'source_cells': source_cells}, sheets


# ───────────────────────────── sqlite ─────────────────────────────

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE decisions (id TEXT PRIMARY KEY, rule TEXT NOT NULL, rationale TEXT NOT NULL) STRICT;
CREATE TABLE locations (
    id TEXT PRIMARY KEY, ord INTEGER NOT NULL, room_raw TEXT NOT NULL, room TEXT NOT NULL,
    spot_raw TEXT NOT NULL, spot TEXT NOT NULL, col_feuil1 TEXT, col_nappes TEXT
) STRICT;
CREATE TABLE sections (
    id TEXT PRIMARY KEY, sheet TEXT NOT NULL, row INTEGER NOT NULL,
    level TEXT NOT NULL CHECK (level IN ('typology', 'category', 'subcategory', 'group')),
    parent_id TEXT REFERENCES sections (id), number_raw TEXT, label_raw TEXT NOT NULL, label TEXT NOT NULL,
    label_suggested TEXT
) STRICT;
CREATE TABLE items (
    id TEXT PRIMARY KEY, sheet TEXT NOT NULL, row INTEGER NOT NULL, kind TEXT NOT NULL,
    canonical INTEGER NOT NULL CHECK (canonical IN (0, 1)),
    section_id TEXT REFERENCES sections (id), typology TEXT, category TEXT, subcategory TEXT, grp TEXT,
    context_id TEXT, number_raw TEXT, label_raw TEXT, label TEXT NOT NULL,
    label_origin TEXT NOT NULL CHECK (label_origin IN ('label_cell', 'qty_cell', 'context')), label_suggested TEXT,
    qty_raw TEXT, qty_total REAL, qty_unit TEXT, qty_unit_canonical TEXT,
    qty_approx INTEGER NOT NULL, qty_implied INTEGER NOT NULL,
    remark_raw TEXT, remark TEXT, material_raw TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'struck', 'placeholder', 'zero')),
    disposition TEXT NOT NULL CHECK (disposition IN ('club', 'gift_candidate', 'for_sale')),
    holder TEXT, holder_qty INTEGER, location_not_applicable INTEGER NOT NULL,
    scale TEXT, size_cm TEXT, material TEXT, suggested_app_type TEXT,
    derived_json TEXT NOT NULL, raw_json TEXT NOT NULL
) STRICT;
CREATE TABLE item_qty_parts (
    item_id TEXT NOT NULL REFERENCES items (id), ord INTEGER NOT NULL, n REAL NOT NULL, n_max REAL, unit TEXT,
    qualifier TEXT, dimension TEXT, approx INTEGER NOT NULL, PRIMARY KEY (item_id, ord)
) STRICT;
CREATE TABLE item_locations (
    item_id TEXT NOT NULL REFERENCES items (id), location_id TEXT NOT NULL REFERENCES locations (id),
    col TEXT NOT NULL, mark_raw TEXT NOT NULL,
    mark_kind TEXT NOT NULL CHECK (mark_kind IN ('presence', 'count', 'text')), qty REAL, qty_unit TEXT,
    PRIMARY KEY (item_id, location_id)
) STRICT;
CREATE TABLE item_links (
    item_id TEXT NOT NULL REFERENCES items (id), rel TEXT NOT NULL, target_id TEXT NOT NULL REFERENCES items (id),
    evidence TEXT
) STRICT;
CREATE TABLE annotations (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('textbox', 'stamp', 'comment', 'fill')),
    sheet TEXT NOT NULL, anchor TEXT NOT NULL, text TEXT, author TEXT, dated TEXT,
    item_id TEXT REFERENCES items (id), section_id TEXT REFERENCES sections (id)
) STRICT;
CREATE TABLE flags (
    item_id TEXT REFERENCES items (id), section_id TEXT REFERENCES sections (id),
    code TEXT NOT NULL, detail TEXT NOT NULL
) STRICT;
CREATE TABLE source_rows (
    sheet TEXT NOT NULL, row INTEGER NOT NULL, kind TEXT NOT NULL, reason TEXT NOT NULL, records TEXT NOT NULL,
    PRIMARY KEY (sheet, row)
) STRICT;
CREATE TABLE source_cells (
    sheet TEXT NOT NULL, ref TEXT NOT NULL, value TEXT NOT NULL, type TEXT NOT NULL, style TEXT NOT NULL,
    color TEXT, fill TEXT, role TEXT NOT NULL, consumer_id TEXT NOT NULL, PRIMARY KEY (sheet, ref)
) STRICT;
CREATE INDEX ix_flags_code ON flags (code);
CREATE INDEX ix_item_locations_location ON item_locations (location_id);
CREATE VIEW v_items AS
SELECT i.id, i.sheet, i.row, i.canonical, i.status, i.disposition, i.typology, i.category, i.subcategory,
       i.label, i.qty_raw, i.qty_total, i.qty_unit, i.qty_approx, i.remark, i.holder, i.scale, i.size_cm,
       i.suggested_app_type,
       (SELECT group_concat(l.room || ' / ' || l.spot
                            || CASE WHEN il.mark_kind = 'presence' THEN '' ELSE ' [' || il.mark_raw || ']' END, '; ')
          FROM item_locations il JOIN locations l ON l.id = il.location_id WHERE il.item_id = i.id) AS locations,
       (SELECT group_concat(f.code, ', ') FROM flags f WHERE f.item_id = i.id) AS flags
  FROM items i
 ORDER BY CASE i.sheet WHEN 'Feuil1' THEN 0 ELSE 1 END, i.row;
"""


def text_or_none(value):
    return None if value is None else str(value)


def write_sqlite(document, path):
    """Rebuilt from the JSON document alone, into a temporary file that then replaces the old one."""
    temp = path.with_suffix('.sqlite3.tmp')
    if temp.exists():
        temp.unlink()
    db = sqlite3.connect(temp)
    db.execute('PRAGMA journal_mode = DELETE')
    db.execute('PRAGMA foreign_keys = ON')
    db.executescript(SCHEMA)
    meta = document['meta']
    db.executemany('INSERT INTO meta VALUES (?, ?)', [
        ('schema_version', str(meta['schema_version'])), ('generator', meta['generator']),
        ('source_file', meta['source']['file']), ('source_sha256', meta['source']['sha256']),
        ('inventory_date', meta['inventory_date']), ('comment_dates', ', '.join(meta['comment_dates'])),
    ])
    db.executemany('INSERT INTO decisions VALUES (?, ?, ?)',
                   [(d['id'], d['rule'], d['rationale']) for d in document['decisions']])
    db.executemany('INSERT INTO locations VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [
        (loc['id'], loc['order'], loc['room_raw'], loc['room'], loc['spot_raw'], loc['spot'],
         loc['columns'].get('Feuil1'), loc['columns'].get('Nappes')) for loc in document['locations']])
    db.executemany('INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
        (s['id'], s['sheet'], s['row'], s['level'], s['parent'], s['number_raw'], s['label_raw'], s['label'],
         s['label_suggested']) for s in document['sections']])
    for item in document['items']:
        quantity, derived, holder = item['quantity'], item['derived'], item['holder']
        db.execute('INSERT INTO items VALUES (' + ', '.join('?' * 36) + ')', (
            item['id'], item['sheet'], item['row'], item['kind'], int(item['canonical']),
            item['section_path'][-1] if item['section_path'] else None, item['typology'], item['category'],
            item['subcategory'], item['group'], item['context']['id'] if item['context'] else None,
            item['number_raw'], item['raw']['label'], item['label']['text'], item['label']['origin'],
            item['label']['suggested'], text_or_none(quantity['raw']), quantity['total'], quantity['unit'],
            quantity['unit_canonical'], int(quantity['approx']), int(quantity['implied']),
            item['raw']['remark'], item['remark'], item['raw']['material'], item['status'], item['disposition'],
            holder['who_raw'] if holder else None, holder['qty'] if holder else None,
            int(item['location_not_applicable']),
            derived['scale']['value'] if 'scale' in derived else None,
            'x'.join(map(str, derived['size_cm']['value'])) if 'size_cm' in derived else None,
            derived['material']['value'] if 'material' in derived else None,
            derived['suggested_app_type']['value'] if 'suggested_app_type' in derived else None,
            json.dumps(derived, ensure_ascii=False), json.dumps(item['raw'], ensure_ascii=False)))
        db.executemany('INSERT INTO item_qty_parts VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [
            (item['id'], order, p['n'], p['n_max'], p['unit'], p['qualifier'], p['dimension'], int(p['approx']))
            for order, p in enumerate(quantity['parts'], 1)])
        db.executemany('INSERT INTO item_locations VALUES (?, ?, ?, ?, ?, ?, ?)', [
            (item['id'], loc['location'], loc['col'], str(loc['mark_raw']), loc['mark_kind'], loc['qty'],
             loc['qty_unit']) for loc in item['locations']])
        db.executemany('INSERT INTO flags VALUES (?, NULL, ?, ?)',
                       [(item['id'], f['code'], f['detail']) for f in item['flags']])
    for item in document['items']:
        db.executemany('INSERT INTO item_links VALUES (?, ?, ?, ?)', [
            (item['id'], link['rel'], link['target'], link['evidence']) for link in item['links']])
    for section in document['sections']:
        db.executemany('INSERT INTO flags VALUES (NULL, ?, ?, ?)',
                       [(section['id'], f['code'], f['detail']) for f in section['flags']])
    db.executemany('INSERT INTO annotations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
        (a['id'], a['kind'], a['sheet'], a['anchor'], a['text'], a['author'], a['dated'], a['item'], a['section'])
        for a in document['annotations']])
    db.executemany('INSERT INTO source_rows VALUES (?, ?, ?, ?, ?)', [
        (row['sheet'], row['row'], row['kind'], row['reason'], ', '.join(row['records'])) for row in document['rows']])
    db.executemany('INSERT INTO source_cells VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
        (c['sheet'], c['ref'], str(c['value']), c['type'], c['style'], c['color'], c['fill'], c['role'], c['consumer'])
        for c in document['source_cells']])
    db.commit()
    problems = db.execute('PRAGMA foreign_key_check').fetchall()
    db.close()
    if problems:
        temp.unlink()
        fail(f'foreign key problems in the generated database: {problems[:5]}')
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--xlsx', type=Path, default=XLSX, help='the workbook to read')
    parser.add_argument('--out-dir', type=Path, default=OUT_DIR, help='where to write inventory_v2.json/.sqlite3')
    parser.add_argument('--print-rows', action='store_true', help='print the classification of every row')
    parser.add_argument('--check-tsv', action='store_true', help='diff the cell values against the old TSV exports')
    args = parser.parse_args()

    # Fixed file names: whatever --out-dir is, this cannot land on data/inventory.sqlite3.
    json_path, sqlite_path = args.out_dir / 'inventory_v2.json', args.out_dir / 'inventory_v2.sqlite3'

    document, sheets = extract(args.xlsx)
    if args.print_rows:
        for row in document['rows']:
            print(f'  {row["sheet"]:7} {row["row"]:>4}  {row["kind"]:18} {row["reason"]}')

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    write_sqlite(json.loads(json_path.read_text(encoding='utf-8')), sqlite_path)

    meta = document['meta']
    for sheet in meta['sheets']:
        print(f'{sheet["name"]:7} {sheet["non_empty_rows"]:>4} rows, {sheet["value_cells"]:>4} cells -> '
              f'{sheet["headers"]} header blocks, {sheet["sections"]} sections, {sheet["items"]} items')
    print(f'items: {meta["counts"]["items"]} ({meta["counts"]["canonical_items"]} canonical), '
          f'by status {meta["counts"]["by_status"]}, {meta["counts"]["flags"]} flags')
    print('coverage: every cell, strikethrough, fill, comment, text box and merge is accounted for; '
          'the grid rebuilt from the records equals the sheets')
    if args.check_tsv and not check_tsv(sheets, args.xlsx.parent):
        fail('the TSV exports differ from the workbook in unexpected cells')
    print(f'wrote {json_path.relative_to(ROOT) if json_path.is_relative_to(ROOT) else json_path}')
    print(f'wrote {sqlite_path.relative_to(ROOT) if sqlite_path.is_relative_to(ROOT) else sqlite_path}')


if __name__ == '__main__':
    sys.exit(main())
