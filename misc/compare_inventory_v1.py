"""
Compare the old extraction of the club spreadsheet with the fresh one, and write the report.

The "old extraction" is what `misc/seed_grognards.py` put into the application database. This script reads

    data/inventory.sqlite3                   the application database, opened immutable: never written, not even
                                             its -shm file
    data/xlsx_extract/inventory_v2.json      the fresh extraction (run misc/extract_inventory_xlsx.py first)
    misc/inventory_v1_mapping.json           hand-curated: which old row comes from which sheet line

and writes

    data/xlsx_extract/inventory_v2.sqlite3   tables v1_links, v1_diffs, v1_app_state (added to the v2 database)
    misc/inventory_xlsx_extraction_report.md the discrepancy report, decisions and open questions

The mapping is the only hand-made input. It is refused unless every old row and every new item appears exactly
once, each relation matches its cardinality, and each old row still has the name recorded in the mapping. Every
difference in the report is then computed from the two data sets, not typed.

Usage:
    python misc/extract_inventory_xlsx.py
    python misc/compare_inventory_v1.py
"""
import argparse
import difflib
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_DB = ROOT / 'data' / 'inventory.sqlite3'
V2_JSON = ROOT / 'data' / 'xlsx_extract' / 'inventory_v2.json'
V2_DB = ROOT / 'data' / 'xlsx_extract' / 'inventory_v2.sqlite3'
MAPPING = ROOT / 'misc' / 'inventory_v1_mapping.json'
APP_DATABASES = {'inventory.sqlite3', 'inventory_test.sqlite3'}
REPORT = ROOT / 'misc' / 'inventory_xlsx_extraction_report.md'

# application table -> the item_type used by borrowings, duplicate links and legacy ids
TABLES = {'tablecloths': 'tablecloth', 'terrains': 'terrain', 'miniatures': 'miniature', 'rulebooks': 'rulebook',
          'board_games': 'board_game', 'books': 'book', 'equipment': 'equipment', 'consumables': 'consumable'}
CONTAINER_UNITS = {'boite', 'boites', 'boîte', 'boîtes', 'carton', 'cartons', 'panière', 'panières', 'set', 'sets'}
PLACEHOLDER_VALUES = {None, '', 'Generic', 'Mixte'}
# The sheet writes the same person several ways ("chez Prez", "chez le Préz").
HOLDER_NAMES = {'prez': 'le Préz', 'le prez': 'le Préz'}
STOPWORDS = {'des', 'les', 'the', 'and', 'une', 'avec', 'pour', 'dans', 'dont', 'chez'}
# Other spellings of the same thing: a v1 value is "in the source" when the sheet uses one of these.
ALIASES = {
    'art de la guerre': ['adg'], 'star wars armada': ['armada'], 'star wars': ['starwars'],
    'flames of war': ['fow'], 'xxe siecle': ['20e siecle'],
}
UNMAPPED_REASONS = {
    'not_canonical': lambda item: not item['canonical'],
    'struck': lambda item: item['status'] == 'struck',
    'placeholder': lambda item: item['status'] == 'placeholder',
    'zero': lambda item: item['status'] == 'zero',
    'dropped': lambda item: item['canonical'] and item['status'] == 'active',
}
CAUSES = {
    'room_header_misread': 'Room read wrongly from the merged header',
    'wrong_spot': 'Stored in the wrong spot',
    'location_invented': 'Location invented (the sheet gives none)',
    'multi_location_collapsed': 'Several places collapsed into one',
    'quantity_lost': 'Quantity lost (stored as 1)',
    'quantity_in_name': 'Count kept in the name, quantity stored as 1',
    'quantity_differs': 'Quantity differs',
    'quantity_summed': 'Different things added into one number',
    'quantity_assumed': 'Quantity assumed (the sheet gives none)',
    'approx_dropped': 'Approximation ("env") dropped',
    'unit_dropped': 'Counts containers, stored as a bare number',
    'struck_imported_as_live': 'Struck-through row imported as live stock',
    'rows_merged': 'Several sheet lines merged into one row',
    'row_split': 'One sheet line split into several rows',
    'scale_differs': 'Scale differs from the sheet',
    'size_differs': 'Size differs from the sheet',
    'material_differs': 'Material differs from the sheet',
    'value_not_in_source': 'Value the sheet does not state',
    'remark_not_carried': 'Remark not carried over',
    'comment_not_carried': 'Cell comment not carried over',
}


def fail(message):
    raise SystemExit(f'ERROR: {message}')


def norm(text):
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def tokens(text):
    return [t for t in norm(text).split() if len(t) >= 3 and t not in STOPWORDS]


def close(token, pool):
    return any(token == other or difflib.SequenceMatcher(None, token, other).ratio() >= 0.8 for other in pool)


def stated_in(value, source):
    """Is `value` something the source text says, allowing for spelling, spacing and known aliases?"""
    squashed = norm(source).replace(' ', '')
    if norm(value).replace(' ', '') in squashed:
        return True
    pool = tokens(source)
    if tokens(value) and all(close(token, pool) for token in tokens(value)):
        return True
    return any(norm(alias) in norm(source) for alias in ALIASES.get(norm(value), []))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ───────────────────────────── inputs ─────────────────────────────

def read_old(path):
    """The item rows of the application database with what hangs off them. Opened immutable: nothing is written."""
    wal = Path(str(path) + '-wal')
    if wal.exists() and wal.stat().st_size:
        fail(f'{wal.name} is not empty: an immutable open would miss its content. Stop the app and checkpoint first.')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.row_factory = sqlite3.Row
    locations = {row['id']: dict(row) for row in db.execute('SELECT * FROM locations')}
    games = {row['id']: row['name'] for row in db.execute('SELECT * FROM games')}
    borrowings = Counter((row['item_type'], row['item_id']) for row in db.execute('SELECT * FROM borrowings'))
    legacy = {(row['item_type'], row['item_id']): row['object_id']
              for row in db.execute('SELECT * FROM legacy_object_ids')}
    duplicates = Counter()
    for row in db.execute('SELECT * FROM duplicate_links'):
        duplicates[(row['item1_type'], row['item1_id'])] += 1
        duplicates[(row['item2_type'], row['item2_id'])] += 1
    rows = {}
    for table, item_type in TABLES.items():
        for row in db.execute(f'SELECT * FROM {table} ORDER BY id'):
            row = dict(row)
            location = locations[row['location_id']]
            rows[f'{table}:{row["id"]}'] = {
                'key': f'{table}:{row["id"]}', 'table': table, 'id': row['id'],
                'name': row.get('name') or row.get('type'), 'quantity': row['quantity'],
                'room': location['room'], 'spot': location['spot'], 'game': games.get(row.get('game_id')),
                'scale': row.get('scale'), 'theater': row.get('theater'), 'universe': row.get('universe'),
                'size': row.get('size'), 'material': row.get('material'), 'remarks': row.get('remarks'),
                'unit': row.get('unit'), 'sticker_printed': row['sticker_printed'],
                'images': len(json.loads(row['images'])), 'borrowings': borrowings[(item_type, row['id'])],
                'legacy_object_id': legacy.get((item_type, row['id'])),
                'duplicate_links': duplicates[(item_type, row['id'])],
            }
    db.close()
    return rows, list(locations.values())


def check_mapping(mapping, old, items):
    """The mapping is hand-made, so it gets no benefit of the doubt."""
    seen_old, seen_new = Counter(), Counter()
    uses = Counter(new for link in mapping['links'] for new in link['new'])
    for link in mapping['links'] + mapping['unmapped_old']:
        seen_old[link['old']] += 1
        if link['old'] not in old:
            fail(f'mapping: {link["old"]} is not a row of the old database')
        if old[link['old']]['name'] != link['old_name']:
            fail(f'mapping: {link["old"]} is now named {old[link["old"]]["name"]!r}, the mapping was written for '
                 f'{link["old_name"]!r}. The database changed: review the mapping.')
    for link in mapping['links']:
        for new in link['new']:
            if new not in items:
                fail(f'mapping: {link["old"]} points at {new}, which is not an item of the new extraction')
        shared = [uses[new] > 1 for new in link['new']]
        expected = 'merged' if len(link['new']) > 1 else 'split' if shared[0] else 'exact'
        if link['relation'] != expected or (len(link['new']) > 1 and any(shared)):
            fail(f'mapping: {link["old"]} is declared {link["relation"]!r} but its links make it {expected!r}')
    for entry in mapping['unmapped_new']:
        if entry['new'] not in items:
            fail(f'mapping: unmapped_new lists {entry["new"]}, which is not an item of the new extraction')
        if not UNMAPPED_REASONS[entry['reason']](items[entry['new']]):
            fail(f'mapping: {entry["new"]} is listed as {entry["reason"]!r} but the extraction says otherwise')
        seen_new[entry['new']] += 1
    for new in uses:
        if seen_new[new]:
            fail(f'mapping: {new} is both linked and listed as unmapped')
        seen_new[new] += 1
    missing_old = sorted(set(old) - set(seen_old)) + sorted(k for k, n in seen_old.items() if n > 1)
    missing_new = sorted(set(items) - set(seen_new)) + sorted(k for k, n in seen_new.items() if n > 1)
    if missing_old or missing_new:
        fail(f'mapping: not accounted for exactly once: old {missing_old}, new {missing_new}')


def check_seed(old, path=ROOT / 'misc' / 'seed_grognards.py'):
    """Is the database still what the seed script wrote? Compared on name, quantity and spot, in seed order."""
    import ast
    if not path.exists():
        return f'`{path.name}` was not found, so the database could not be checked against it.'
    models = {'Tablecloth': 'tablecloths', 'Terrain': 'terrains', 'Miniature': 'miniatures', 'Rulebook': 'rulebooks',
              'BoardGame': 'board_games', 'Book': 'books', 'Equipment': 'equipment', 'Consumable': 'consumables'}
    tree = ast.parse(path.read_text(encoding='utf-8'))
    spots = {}
    for node in ast.walk(tree):   # loc_gs_p1 = get_or_create(Location, ..., spot="Pièce 1")
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and getattr(node.value.func, 'id', '') == 'get_or_create':
            spot = [k.value.value for k in node.value.keywords if k.arg == 'spot']
            if spot:
                spots[node.targets[0].id] = spot[0]
    seeded = defaultdict(list)
    for node in ast.walk(tree):
        is_save = isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'save' and node.args
        call = node.args[0] if is_save else None
        if isinstance(call, ast.Call) and getattr(call.func, 'id', '') in models:
            kw = {k.arg: k.value for k in call.keywords}
            name = kw.get('name') or kw.get('type')
            quantity = kw['quantity'].value if 'quantity' in kw else 1
            seeded[models[call.func.id]].append((node.lineno, name.value, quantity, spots[kw['location'].id]))
    total = same = 0
    for table_name, rows in seeded.items():
        for order, (_, name, quantity, spot) in enumerate(sorted(rows), 1):
            total += 1
            row = old.get(f'{table_name}:{order}')
            same += bool(row and (row['name'], row['quantity'], row['spot']) == (name, quantity, spot))
    return (f'It seeds {total} items; {same} of them are in `data/inventory.sqlite3` with the same name, quantity '
            f'and location, so every item discrepancy below is an extraction error, not a later edit.' if same == total
            else f'It seeds {total} items; only {same} still match `data/inventory.sqlite3` on name, quantity and '
                 f'location, so some differences below may be later edits.')


# ───────────────────────────── differences ─────────────────────────────

def source_text(items, sections):
    """Everything the sheet says on and above these lines."""
    texts = []
    for item in items:
        texts += [item['label']['text'], item['remark'] or '', str(item['raw']['quantity'] or ''),
                  item['raw']['label'] or '', item['raw']['material'] or '']
        texts += [sections[sid]['label'] for sid in item['section_path']]
        texts += [comment['text'] for comment in item['comments']]
    return ' | '.join(texts)


def describe_qty(item):
    raw = item['quantity']['raw']
    return 'none' if raw is None else repr(raw)


def describe_line(item):
    """'2' (pieds / lumières): the quantity cell, then what the line is."""
    path = [item['subcategory'], item['label']['text']] if item['subcategory'] else [item['label']['text']]
    return f'{describe_qty(item)} ({" / ".join(path)})'


def numbers_in(text):
    return set(re.findall(r'\d+(?:,\d+)?', str(text)))


def describe_places(items):
    places = []
    for item in items:
        for loc in item['locations']:
            mark = '' if loc['mark_kind'] == 'presence' else f' [{loc["mark_raw"]}]'
            places.append(f'{loc["spot"]}{mark}')
    return ', '.join(dict.fromkeys(places)) or 'none'


def compare(old_row, relation, items, sections, columns):
    """Differences between one old row and the sheet line(s) it comes from. Yields (field, old, new, cause, extra)."""
    for found in _compare(old_row, relation, items, sections, columns):
        yield found if len(found) == 5 else (*found, {})


def _compare(old_row, relation, items, sections, columns):
    # where
    spots = {loc['spot'].casefold() for item in items for loc in item['locations']}
    marks = [loc for item in items for loc in item['locations']]
    old_place = f'{old_row["room"]} / {old_row["spot"]}'
    whole = [item['holder']['who_raw'] for item in items if item['holder'] and item['holder']['qty'] is None]
    holders = sorted({HOLDER_NAMES.get(norm(who), who) for who in whole})
    if not spots and len(holders) == 1 and norm(old_row['spot']) == norm(f'chez {holders[0]}'):
        pass   # no mark in the sheet, and the old row already says whose home it is at
    elif not spots:
        struck = any(item['status'] == 'struck' for item in items)
        extra = [f'held "chez {who}"' for who in whole] + (['struck through'] if struck else [])
        why = f' ({"; ".join(dict.fromkeys(extra))})' if extra else ''
        yield 'location', old_place, f'no location mark{why}', 'location_invented', {
            'holders': holders, 'struck': struck}
    elif old_row['spot'].casefold() not in spots:
        marked = sorted({loc['col'] for loc in marks})
        stored = columns[old_row['spot'].casefold()][items[0]['sheet']]
        shifts = sorted({ord(stored) - ord(col) for col in marked})
        yield 'location', old_place, describe_places(items), 'wrong_spot', {
            'marked_col': ', '.join(marked), 'stored_col': stored, 'shifts': shifts,
            'target_spots': sorted({loc['spot'] for loc in marks})}
    elif len(spots) > 1 or any(loc['mark_kind'] != 'presence' for loc in marks):
        yield 'location', old_place, describe_places(items), 'multi_location_collapsed'
    # status
    if any(item['status'] == 'struck' for item in items):
        struck = ', '.join(ref for item in items for ref in item['format']['struck'])
        yield 'status', 'live stock', f'struck through ({struck})', 'struck_imported_as_live'
    # how many
    old_qty = old_row['quantity']
    if relation == 'split':
        item = items[0]
        parts = [p for p in item['quantity']['parts']
                 if p['qualifier'] and norm(p['qualifier']) in norm(old_row['name'])]
        yield 'rows', '1 of several rows', f'one line: {describe_qty(item)} / {item["remark"]!r}', 'row_split'
        if len(parts) == 1 and parts[0]['n'] != old_qty:
            yield ('quantity', old_qty, f'{parts[0]["n"]} ({parts[0]["qualifier"]})',
                   'quantity_lost' if old_qty == 1 else 'quantity_differs', {'target_qty': parts[0]['n']})
    elif relation == 'merged':
        labels = ' + '.join(describe_line(item) for item in items)
        yield 'rows', '1 row', f'{len(items)} lines: {labels}', 'rows_merged'
        totals = [item['quantity']['total'] for item in items]
        if None not in totals and sum(totals) == old_qty:
            units = {item['quantity']['unit'] for item in items}
            if len(units) > 1:
                yield 'quantity', old_qty, labels, 'quantity_summed'
        else:
            yield 'quantity', old_qty, labels, 'quantity_lost' if old_qty == 1 else 'quantity_differs'
    else:
        quantity = items[0]['quantity']
        if quantity['implied']:
            if old_qty != 1:
                yield 'quantity', old_qty, 'a name only (one implied)', 'quantity_differs'
        elif not quantity['parts']:
            yield 'quantity', old_qty, describe_qty(items[0]), 'quantity_assumed'
        elif quantity['total'] is None:
            added = sum(p['n'] for p in quantity['parts'])
            yield ('quantity', old_qty, describe_qty(items[0]),
                   'quantity_summed' if added == old_qty else 'quantity_differs')
        elif quantity['total'] != old_qty:
            stated = numbers_in(quantity['raw'])
            if old_qty == 1 and stated and stated <= numbers_in(old_row['name']):
                yield 'quantity', old_qty, describe_qty(items[0]), 'quantity_in_name'
            else:
                yield ('quantity', old_qty, describe_qty(items[0]),
                       'quantity_lost' if old_qty == 1 else 'quantity_differs', {'target_qty': quantity['total']})
        else:
            if quantity['approx']:
                yield 'quantity', old_qty, describe_qty(items[0]), 'approx_dropped'
            unit = (quantity['unit'] or '').lower()
            if unit in CONTAINER_UNITS and not stated_in(unit, old_row['name']):
                yield 'quantity', old_qty, describe_qty(items[0]), 'unit_dropped'
    # what the sheet lets one derive
    source = source_text(items, sections)
    scales = {item['derived']['scale']['value'] for item in items if 'scale' in item['derived']}
    if old_row['scale']:
        if scales and old_row['scale'] not in scales:
            yield ('scale', old_row['scale'], ', '.join(sorted(scales)), 'scale_differs',
                   {'target_scales': sorted(scales)})
        elif not scales and old_row['scale'] not in PLACEHOLDER_VALUES:
            yield 'scale', old_row['scale'], 'not stated', 'value_not_in_source'
    if old_row['size']:
        sizes = {'x'.join(map(str, item['derived']['size_cm']['value'])) if 'size_cm' in item['derived'] else '?x?'
                 for item in items}
        if old_row['size'] not in sizes:
            yield 'size', old_row['size'], ', '.join(sorted(sizes)), 'size_differs'
    if old_row['material']:
        materials = {item['derived']['material']['value'] for item in items if 'material' in item['derived']}
        if materials and old_row['material'] not in materials:
            yield 'material', old_row['material'], ', '.join(sorted(materials)), 'material_differs'
    for field in ('game', 'universe', 'theater'):
        value = old_row[field]
        if value not in PLACEHOLDER_VALUES and not stated_in(value, source):
            yield field, value, 'not stated', 'value_not_in_source'
    # what was said beside the line
    carried = ('name', 'remarks', 'game', 'universe', 'theater', 'unit', 'scale')
    old_text = ' | '.join(str(old_row[k]) for k in carried if old_row[k])
    for item in items:
        # a split line spreads its remark over the old rows: checked by the quantity comparison instead
        lost = item['remark'] and tokens(item['remark']) and not stated_in(item['remark'], old_text)
        if lost and relation != 'split':
            yield 'remark', 'absent', repr(item['remark']), 'remark_not_carried'
        for comment in item['comments']:
            yield 'comment', 'absent', f'{comment["text"]!r} (comment on {comment["cell"]})', 'comment_not_carried'


def fuzzy_audit(old, items, linked):
    """
    An independent look at the hand-made mapping: for each old row, which new lines share the most words with its
    name? Reported when the curated link is not among the best. Not an error: a list to look at.
    """
    candidates = {key: tokens(' '.join(filter(None, [item['label']['text'], item['remark'],
                                                     str(item['raw']['quantity'] or '')])))
                  for key, item in items.items() if item['canonical']}
    rows = []
    for key, row in old.items():
        words = tokens(row['name'])
        scores = {new: sum(close(word, pool) for word in words) / len(words) for new, pool in candidates.items()}
        top = max(scores.values())
        best = sorted((new for new, score in scores.items() if score == top),
                      key=lambda n: (n[:2], int(n.split('r')[1])))
        curated = linked.get(key, [])
        if not top or not set(curated) & set(best):
            rows.append((key, row['name'], curated, round(max((scores[n] for n in curated), default=0), 2),
                         best[:3] if top else [], round(top, 2)))
    return rows


# ───────────────────────────── outputs ─────────────────────────────

def write_tables(path, links, diffs, old):
    db = sqlite3.connect(path)
    db.executescript("""
        DROP TABLE IF EXISTS v1_links; DROP TABLE IF EXISTS v1_diffs; DROP TABLE IF EXISTS v1_app_state;
        CREATE TABLE v1_links (
            old_table TEXT, old_id INTEGER, old_name TEXT, new_id TEXT REFERENCES items (id),
            relation TEXT NOT NULL CHECK (relation IN ('exact', 'merged', 'split', 'no_source', 'not_in_v1')),
            note TEXT
        ) STRICT;
        CREATE TABLE v1_diffs (
            old_table TEXT NOT NULL, old_id INTEGER NOT NULL, new_ids TEXT, field TEXT NOT NULL,
            old_value TEXT, new_value TEXT, cause TEXT NOT NULL
        ) STRICT;
        CREATE TABLE v1_app_state (
            old_table TEXT NOT NULL, old_id INTEGER NOT NULL, sticker_printed INTEGER NOT NULL, images INTEGER NOT NULL,
            borrowings INTEGER NOT NULL, duplicate_links INTEGER NOT NULL, legacy_object_id TEXT,
            PRIMARY KEY (old_table, old_id)
        ) STRICT;
        CREATE INDEX ix_v1_diffs_cause ON v1_diffs (cause);
    """)
    db.executemany('INSERT INTO v1_links VALUES (?, ?, ?, ?, ?, ?)', links)
    db.executemany('INSERT INTO v1_diffs VALUES (?, ?, ?, ?, ?, ?, ?)', diffs)
    db.executemany('INSERT INTO v1_app_state VALUES (?, ?, ?, ?, ?, ?, ?)', [
        (row['table'], row['id'], row['sticker_printed'], row['images'], row['borrowings'], row['duplicate_links'],
         row['legacy_object_id']) for row in old.values()])
    db.commit()
    db.close()


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ⏎ ')


def table(headers, rows):
    if not rows:
        return ['_None._', '']
    lines = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|']
    lines += ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]
    return lines + ['']


def where(items):
    return ', '.join(f'{item["sheet"]} row {item["row"]}' for item in items)


def sheet_line(item):
    """How the line reads in the sheet, cell by cell."""
    return '; '.join(f'{ref}={value!r}' for ref, value in item['cells'].items())


def write_report(path, document, old, mapping, diffs, audit, hashes, seed_check):
    items = {item['id']: item for item in document['items']}
    meta = document['meta']
    by_cause = defaultdict(list)
    for diff in diffs:
        by_cause[diff['cause']].append(diff)
    linked = {link['old']: [items[new] for new in link['new']] for link in mapping['links']}
    dropped = [items[e['new']] for e in mapping['unmapped_new'] if e['reason'] == 'dropped']

    def rows_for(cause, fields=('old', 'name', 'source', 'old_value', 'new_value')):
        out = []
        for diff in by_cause.get(cause, []):
            row = {'old': diff['old'].replace(':', '#'), 'name': old[diff['old']]['name'] if diff['old'] in old else '',
                   'source': where(diff['items']), 'old_value': diff['old_value'], 'new_value': diff['new_value'],
                   'field': diff['field']}
            out.append([row[f] for f in fields])
        return out

    def named(ids):
        return ', '.join(f'{n} ({items[n]["label"]["text"]})' for n in ids) or '-'

    L = []
    L += ['# Inventory spreadsheet: audit of the old extraction and fresh re-extraction', '',
          '_Generated by `misc/compare_inventory_v1.py` from the workbook, the application database and '
          '`misc/inventory_v1_mapping.json`. Do not edit by hand: change the scripts or the mapping and run them '
          'again._', '']

    # 1
    counts = meta['counts']
    wrong_room = by_cause.get('room_header_misread', [])
    L += ['## 1. Summary', '',
          f'- **Source**: `misc/{meta["source"]["file"]}` (sha256 `{meta["source"]["sha256"][:16]}…`), '
          f'inventory dated {meta["inventory_date"]} by its stamps, with comments added on '
          f'{", ".join(d[:10] for d in meta["comment_dates"])}.',
          f'- **Old extraction**: the items hard-coded in `misc/seed_grognards.py`. {seed_check} '
          f'The database also holds {len(mapping["unmapped_old"])} item added by hand, and application state '
          f'(users, borrowings, photos, sticker flags) that no extraction produced.',
          f'- **New extraction**: {counts["items"]} lines ({counts["canonical_items"]} canonical) from '
          f'{sum(s["non_empty_rows"] for s in meta["sheets"])} non-empty rows of two sheets; '
          f'{counts["by_status"]["active"]} active, {counts["by_status"]["struck"]} struck through, '
          f'{counts["by_status"]["placeholder"]} placeholders, {counts["by_status"]["zero"]} counted zero; '
          f'{counts["flags"]} flags for human review.',
          f'- **Rooms**: {len(wrong_room)} of the 8 spots are stored under the wrong room.',
          f'- **Places**: {len(by_cause["wrong_spot"])} old rows are in the wrong spot, '
          f'{len(by_cause["location_invented"])} have a location the sheet does not give, '
          f'{len(by_cause["multi_location_collapsed"])} lost one or more of their places.',
          f'- **Quantities**: {len(by_cause["quantity_lost"]) + len(by_cause["quantity_in_name"])} stored as 1 against '
          f'another count in the sheet ({len(by_cause["quantity_in_name"])} of them keep the count in the name), '
          f'{len(by_cause["quantity_differs"])} otherwise different, {len(by_cause["quantity_summed"])} adding '
          f'different things, {len(by_cause["approx_dropped"])} approximations and '
          f'{len(by_cause["unit_dropped"])} container counts stored as bare numbers.',
          f'- **Rows**: {len(dropped)} sheet lines are missing from the old extraction, '
          f'{len(by_cause["struck_imported_as_live"])} struck-through lines were imported as live stock, '
          f'{len(by_cause["rows_merged"])} old rows merge several lines.',
          f'- **Invented values**: {len(by_cause["value_not_in_source"])} games, universes, periods or scales that '
          f'the sheet does not state.',
          '- **Cause**: interpretation, not file conversion. The old TSV exports hold the same cell values as the '
          'workbook. See section 4.',
          f'- **Untouched**: `data/inventory.sqlite3` has the same sha256 before and after (`{hashes[0][:16]}…`).', '']

    # 2
    L += ['## 2. Sources', '']
    L += table(['Sheet', 'Non-empty rows', 'Value cells', 'Merges', 'Comments', 'Text boxes', 'Struck cells',
                'Records'],
               [[s['name'], s['non_empty_rows'], s['value_cells'], s['merges'], s['comments'], s['text_boxes'],
                 ', '.join(s['struck_cells']) or '-',
                 f'{s["headers"]} header blocks, {s["sections"]} sections, {s["items"]} items']
                for s in meta['sheets']])
    L += ['- `Feuil1` is the inventory. Column A is a numbered label, B `quantité`, C `remarques`, D to K eight '
          'location columns under a three-row header (title, room, spot) repeated at rows 1, 64 and 127 for printing.',
          '- `Nappes` breaks section 1.1.1 (tablecloths) down further, with a `Matériau` column.',
          '- `Feuil2` and `Feuil3` are empty. There is no formula and no hidden row or sheet.',
          '- The old flat exports `misc/…Feuil1.tsv` and `misc/Nappes.tsv` hold the same values as the workbook, apart '
          'from six header cells of row 2 (filled in later) and one line break (B14).',
          '- `misc/seed_grognards.py` is the old extraction. `misc/old_imports.tar.gz` and `misc/old_version.tar.gz` '
          'hold three earlier attempts as JSON; they were not compared.', '']
    L += ['Information that exists only as formatting, and that any flat export loses:', '']
    L += table(['What', 'Where', 'Meaning'], [
        ['Strikethrough', ', '.join(f'{s["name"]}!{ref}' for s in meta['sheets'] for ref in s['struck_cells']),
         'Lost or removed stock'],
        *[[f'Cell comment ({a["author"]}, {a["dated"]})', f'{a["sheet"]}!{a["anchor"]}', a['text']]
          for a in document['annotations'] if a['kind'] == 'comment'],
        *[['Floating text box', f'{a["sheet"]}, over {a["anchor"]}', a['text']]
          for a in document['annotations'] if a['kind'] == 'textbox'],
        ['Stamp, three times', 'Feuil1', f'inventaire du 06/12/24 ({meta["inventory_date"]})'],
        *[['Grey fill', f'{a["sheet"]}!{a["anchor"]}', 'Location not applicable']
          for a in document['annotations'] if a['kind'] == 'fill'],
        ['Merged header cells', 'Feuil1 D65:E65, F65:K65 (and rows 128)', 'Which spots belong to which room'],
        ['Font colour of column A', 'Feuil1', 'Red typology, blue category, green sub-category'],
    ])

    # 3
    L += ['## 3. Discrepancies: old extraction against the sheet', '',
          'Old rows are written `table#id` as in `data/inventory.sqlite3`. "Sheet" columns quote the workbook.', '']
    L += ['### 3.1 Rooms', '',
          'One defect in the `locations` table. The header puts only the two cupboards in the grande salle; the old '
          'extraction also put pièce 1 and both vitrines there.', '']
    L += table(['Old location', 'Old room', 'Room in the sheet', 'Old item rows there'],
               [[f'locations#{d["old"].split(":")[1]} {d["spot"]}', d['old_value'], d['new_value'], d['count']]
                for d in wrong_room])
    wrong = by_cause.get('wrong_spot', [])
    shifts = Counter(shift for d in wrong for shift in d['shifts'])
    L += ['### 3.2 Wrong spot', '', 'The mark is in one column, the old row names the spot of another.', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Marked in the sheet', 'Column', 'Old place', 'Its column',
                'Off by'],
               [[d['old'].replace(':', '#'), old[d['old']]['name'], where(d['items']), d['new_value'], d['marked_col'],
                 d['old_value'], d['stored_col'], ', '.join(f'{s:+d}' for s in d['shifts'])] for d in wrong])
    one_off = bool(wrong) and set(shifts) <= {-1, 1}
    if one_off:
        L += [f'All {len(wrong)} are exactly one column away from the mark: {shifts[1]} one column to the right, '
              f'{shifts[-1]} one column to the left.', '']
    L += ['### 3.3 Invented location', '',
          'The sheet has no mark on these lines. The application requires a location, so one was made up.', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Old place', 'Sheet'], rows_for('location_invented'))
    L += ['### 3.4 Several places collapsed into one', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Old place', 'Marked in the sheet'],
               rows_for('multi_location_collapsed'))
    L += ['### 3.5 Quantities', '']
    for cause in ('quantity_lost', 'quantity_in_name', 'quantity_differs', 'quantity_summed', 'quantity_assumed',
                  'approx_dropped', 'unit_dropped'):
        L += [f'**{CAUSES[cause]}**', '']
        L += table(['Old row', 'Old name', 'Sheet line', 'Old quantity', 'Sheet quantity'], rows_for(cause))
    L += ['### 3.6 Struck-through lines imported as live stock', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Old', 'Sheet'], rows_for('struck_imported_as_live'))
    L += ['### 3.7 Lines merged or split', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Old', 'Sheet'], rows_for('rows_merged') + rows_for('row_split'))
    L += ['### 3.8 Sheet lines missing from the old extraction', '']
    L += table(['Sheet line', 'Section', 'Cells', 'Disposition'],
               [[where([item]), ' / '.join(filter(None, [item['category'], item['subcategory']])), sheet_line(item),
                 item['disposition']] for item in dropped])
    others = Counter(e['reason'] for e in mapping['unmapped_new'] if e['reason'] != 'dropped')
    L += [f'Also absent, for a reason: {others["not_canonical"]} Feuil1 tablecloth lines (the old extraction used '
          f'the Nappes sheet instead), {others["struck"]} struck-through lines (rightly left out), '
          f'{others["placeholder"]} placeholders with no quantity or place, {others["zero"]} line counted zero.', '']
    L += ['### 3.9 Values the sheet does not state', '',
          'Added by the old extraction from general knowledge. Possibly right, but not in the source.', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Field', 'Old value'],
               rows_for('value_not_in_source', ('old', 'name', 'source', 'field', 'old_value')))
    L += ['**Scale, size or material that contradicts the sheet**', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Field', 'Old value', 'Sheet'],
               [r for cause in ('scale_differs', 'size_differs', 'material_differs')
                for r in rows_for(cause, ('old', 'name', 'source', 'field', 'old_value', 'new_value'))])
    L += ['### 3.10 Remarks and comments not carried over', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'In the sheet'],
               [r for cause in ('remark_not_carried', 'comment_not_carried')
                for r in rows_for(cause, ('old', 'name', 'source', 'new_value'))])
    L += ['### 3.11 Spelling changed silently', '',
          'The old extraction corrected these without saying so. The new one keeps the sheet\'s spelling and offers '
          'the correction separately (`label.suggested`).', '']
    L += table(['Old row', 'Old name', 'Sheet line', 'Spelling in the sheet'],
               [[key.replace(':', '#'), old[key]['name'], where([item]), item['label']['text']]
                for key, new in linked.items() for item in new if item['label']['suggested']])
    L += ['### 3.12 Old rows with no source line', '']
    L += table(['Old row', 'Old name', 'Why'],
               [[e['old'].replace(':', '#'), e['old_name'], e['reason']] for e in mapping['unmapped_old']])

    # 4
    L += ['## 4. What went wrong, and why', '',
          'The flat export was not the problem: the TSV files hold the same values as the workbook. The errors come '
          'from how the model read them, and from the shape it had to fill.', '',
          '1. **Counting empty columns.** The TSV line of row 50 is '
          '`\\t1 tombeau de Balin\\t\\t\\t\\t\\t\\t\\tX`: the X comes after a run of empty fields. '
          + ('Every wrong spot of section 3.2 is exactly one column off, which is what miscounting such a run by one '
             'gives.' if one_off else 'The wrong spots of section 3.2 are what miscounting such a run gives.'),
          '2. **Reading the merged room header.** In the TSV, row 2 holds `gande salle` in D and `petite salle` in F, '
          'with nothing in between. The old extraction took "pièce 1, vitrine 1, vitrine 2" as part of the grande '
          'salle. The merges D65:E65 and F65:K65, and the explicit cells of row 2 in the workbook, say otherwise.',
          '3. **Filling required fields.** The application schema makes `location_id`, `game_id` and `scale` '
          'mandatory. Where the sheet is silent, a value was invented rather than the gap reported.',
          '4. **One integer for every quantity.** "3 boites", "40 figs env", "11 + 8 + 9" and "1,5m de murs" cannot '
          'share one integer column. Counts were dropped, summed across units, or moved into the name.',
          '5. **Tidying up.** Lines were merged, sections 1.6 to 1.8 left out, typos corrected and remarks dropped, '
          'none of it recorded.',
          '6. **Formatting ignored.** Strikethrough, comments and the text box never reached the model.', '']

    # 5
    L += ['## 5. The new extraction', '',
          '- `data/xlsx_extract/inventory_v2.json` is the source of truth: `meta`, `decisions`, `locations`, '
          '`headers`, `sections`, `items`, `annotations`, `rows` (how each row was classified) and `source_cells` '
          '(every cell with its role).',
          '- `data/xlsx_extract/inventory_v2.sqlite3` is rebuilt from that JSON: tables `items`, `item_qty_parts`, '
          '`item_locations`, `item_links`, `locations`, `sections`, `annotations`, `flags`, `decisions`, '
          '`source_rows`, `source_cells`, the flat view `v_items`, and the comparison tables `v1_links`, `v1_diffs`, '
          '`v1_app_state`.',
          '- One record per source line, identified by sheet and row (`F1:r47`, `NA:r8`), never by the numbering.',
          '- `raw` and `cells` hold the sheet verbatim. `label`, `quantity`, `locations`, `status`, `holder` and '
          '`disposition` are the reading of it. `derived` holds interpretation, each value with its rule.',
          '- Count stock with `canonical = 1` and `status = \'active\'`: this leaves out the Feuil1 tablecloth lines '
          'that Nappes refines, the struck lines and the placeholders.', '',
          '```sql',
          '-- everything in one spot',
          "SELECT id, label, qty_raw, remark FROM v_items WHERE canonical AND locations LIKE '%pièce 2%';",
          '-- what needs a human',
          'SELECT code, count(*) FROM flags GROUP BY code ORDER BY 2 DESC;',
          '-- how one old row differs from the sheet',
          "SELECT field, old_value, new_value, cause FROM v1_diffs WHERE old_table = 'terrains' AND old_id = 16;",
          '```', '']
    L += ['### Decisions', '']
    L += table(['Id', 'Decision', 'Why'], [[d['id'], d['rule'], d['rationale']] for d in document['decisions']])

    # 6
    L += ['## 6. Needs human review', '',
          'Nothing below was guessed. Each flag is in the `flags` table with the same wording.', '']
    questions = [
        ('Rooms', 'The sheet puts pièce 1, vitrine 1 and vitrine 2 in the petite salle; the application says Grande '
                  'salle. Which is true on site?'),
        ('Tablecloths', 'Is `Nappes` the authority over Feuil1 rows 6-14? It settles the StarWars mat size '
                        '(`?x?` against `1,2x1,8`) and contradicts the ADG mat material (`latex` against `Mousepad`).'),
        ('Struck lines', 'Are the ADG mats (row 14) and the wooden boards (rows 19-20) gone for good? The '
                         'application still lists the mats, with stickers printed.'),
        ('Partial marks', '`dont 2` (F10), `1` of nine houses (H47), `1 maison` (H61): the rest is assumed to be at '
                          'the X. Do G153/K153 count boxes of dice?'),
        ('Unsplit places', 'Four coffee machines over two places (row 131), three power strips over three (row 136).'),
        ('Row 144', 'An X on the heading `1.5.matériel divers`: what does it locate?'),
        ('15mm scenery', 'Rows 25-26 have a place but no quantity; rows 24 and 27-38 have neither. The text box '
                         '("54 panières bleues + 1 boite de rangement…") describes the block as a whole and cannot be '
                         'split over those rows.'),
        ('Off-site items', 'Camera, its stand, the lights and the SSD cards are "chez le Préz". Do the light stands '
                           '(row 142) follow? One AdG rulebook is "chez Stéphane M" (row 125).'),
        ('Armada', 'Rows 69-73 are labelled "= règle" but count cartons, a crate and boxes: rules or miniatures?'),
        ('Rows 62, 101, 164, 181', 'A figurine under scenery; "2 maquettes" with no label; a composite line; a line '
                                   'holding scales and periods where quantity and remark should be.'),
        ('Sections 1.7 and 1.8', 'Gift candidates and stock for sale: do they belong in the application at all?'),
        ('miniatures#18', '"Maison européennes" was added by hand and has no line in the sheet.'),
    ]
    L += table(['Topic', 'Question'], questions)
    flags = defaultdict(list)
    for item in document['items']:
        for f in item['flags']:
            flags[f['code']].append((f'{item["sheet"]} row {item["row"]}', item['label']['text'], f['detail']))
    for section in document['sections']:
        for f in section['flags']:
            flags[f['code']].append((f'{section["sheet"]} row {section["row"]}', section['label'], f['detail']))
    quiet = ('TYPO_SUGGESTION', 'NUMBERING_DUPLICATE', 'NUMBERING_MISMATCH', 'NUMBERING_OUT_OF_ORDER')
    L += ['### Flags', '']
    L += table(['Flag', 'Line', 'Label', 'Detail'],
               [[code, line, label, detail] for code in sorted(flags) if code not in quiet
                for line, label, detail in flags[code]])
    L += ['### Spelling and numbering', '', 'Kept as written. Corrections are suggestions only.', '']
    L += table(['Flag', 'Line', 'Label', 'Detail'],
               [[code, line, label, detail] for code in quiet for line, label, detail in flags[code]])

    # 7
    L += ['## 7. Checks the scripts enforce', '',
          '- The workbook\'s sha256 is pinned; another file is refused.',
          '- Every value cell has exactly one primary consumer (header, section, or item field).',
          '- Every struck cell belongs to a record marked struck; every fill, comment, text box and merge is recorded.',
          '- Any font or fill combination outside the eight known ones stops the run.',
          '- The cell grid rebuilt from the records alone equals each sheet, value for value.',
          '- Hand-written quantity overrides must use exactly the numbers of the raw text.',
          '- With `--check-tsv`, the old TSV exports must differ from the workbook only in the seven known cells.',
          '- The mapping must account for every old row and every new item exactly once, with matching names.',
          '- The application database is opened immutable and its sha256 compared before and after.',
          '- Running the extractor twice gives a byte-identical JSON file.', '']

    # appendices
    L += ['## Appendix A. How every row was read', '']
    L += table(['Sheet', 'Row', 'Kind', 'Why', 'Records'],
               [[r['sheet'], r['row'], r['kind'], r['reason'], ', '.join(r['records'])] for r in document['rows']])
    L += ['## Appendix B. Old rows and their source lines', '',
          'Stickers, photos, borrowings and legacy ids hang off the old ids: any correction of the application data '
          'must keep those ids.', '']
    rows = []
    for link in mapping['links']:
        row = old[link['old']]
        state = [f'{row[key]} {what}' for key, what in (('images', 'photo(s)'), ('borrowings', 'borrowing event(s)'),
                                                         ('duplicate_links', 'duplicate link(s)')) if row[key]]
        rows.append([link['old'].replace(':', '#'), row['name'], link['relation'], where(linked[link['old']]),
                     ' + '.join(item['label']['text'] for item in linked[link['old']]),
                     ', '.join(filter(None, state)) or '-', link.get('note', '')])
    L += table(['Old row', 'Old name', 'Relation', 'Sheet line', 'Sheet label', 'Application state', 'Note'], rows)
    printed = sum(row['sticker_printed'] for row in old.values())
    legacy = sum(1 for row in old.values() if row['legacy_object_id'])
    L += [f'{printed} of the {len(old)} old rows have `sticker_printed = 1`; {legacy} have a legacy Mongo id that '
          f'printed QR codes still point to.', '']
    L += ['## Appendix C. Mapping audit', '',
          'An independent look at the hand-made mapping. For each old row, the new lines sharing the most words '
          'with its name were searched; a row is listed here when its curated link is not among them. The old names '
          'were rewritten freely, so a row listed here is not an error by itself: check that the rewriting explains '
          'it.', '']
    L += table(['Old row', 'Old name', 'Curated link', 'Its score', 'Best by shared words', 'Score'],
               [[key.replace(':', '#'), name, named(curated), own, named(best), score]
                for key, name, curated, own, best, score in audit])
    path.write_text('\n'.join(L).rstrip() + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--old-db', type=Path, default=OLD_DB)
    parser.add_argument('--v2-json', type=Path, default=V2_JSON)
    parser.add_argument('--v2-db', type=Path, default=V2_DB)
    parser.add_argument('--mapping', type=Path, default=MAPPING)
    parser.add_argument('--report', type=Path, default=REPORT)
    args = parser.parse_args()
    # The only file this script writes besides the report. It must never be an application database.
    if args.v2_db.resolve() == args.old_db.resolve() or args.v2_db.name in APP_DATABASES:
        fail(f'refusing to write {args.v2_db}: that is an application database')

    before = sha256(args.old_db)
    old, old_locations = read_old(args.old_db)
    document = json.loads(args.v2_json.read_text(encoding='utf-8'))
    mapping = json.loads(args.mapping.read_text(encoding='utf-8'))
    items = {item['id']: item for item in document['items']}
    sections = {section['id']: section for section in document['sections']}
    check_mapping(mapping, old, items)

    diffs = []
    # the locations table itself
    spots = {loc['spot'].casefold(): loc for loc in document['locations']}
    for location in old_locations:
        sheet = spots.get(location['spot'].casefold())
        if sheet is None:
            fail(f'old location {location["spot"]!r} is not a spot of the sheet')
        if sheet['room'].casefold() != location['room'].casefold():
            count = sum(1 for row in old.values()
                        if row['spot'] == location['spot'] and row['room'] == location['room'])
            diffs.append({'old': f'locations:{location["id"]}', 'items': [], 'field': 'room',
                          'old_value': location['room'], 'new_value': sheet['room'], 'cause': 'room_header_misread',
                          'spot': location['spot'], 'count': count})
    columns = {loc['spot'].casefold(): loc['columns'] for loc in document['locations']}
    for link in mapping['links']:
        linked_items = [items[new] for new in link['new']]
        for field, old_value, new_value, cause, extra in compare(old[link['old']], link['relation'], linked_items,
                                                                 sections, columns):
            diffs.append({'old': link['old'], 'items': linked_items, 'field': field, 'old_value': old_value,
                          'new_value': new_value, 'cause': cause, **extra})
    seed_check = check_seed(old)
    unknown = {d['cause'] for d in diffs} - set(CAUSES)
    if unknown:
        fail(f'causes without a description: {unknown}')

    link_rows = []
    for link in mapping['links']:
        table_name, old_id = link['old'].split(':')
        link_rows += [(table_name, int(old_id), link['old_name'], new, link['relation'], link.get('note'))
                      for new in link['new']]
    for entry in mapping['unmapped_old']:
        table_name, old_id = entry['old'].split(':')
        link_rows.append((table_name, int(old_id), entry['old_name'], None, 'no_source', entry['reason']))
    for entry in mapping['unmapped_new']:
        link_rows.append((None, None, None, entry['new'], 'not_in_v1', f'{entry["reason"]}: {entry["detail"]}'))
    diff_rows = [(d['old'].split(':')[0], int(d['old'].split(':')[1]), ', '.join(i['id'] for i in d['items']) or None,
                  d['field'], str(d['old_value']), str(d['new_value']), d['cause']) for d in diffs]
    write_tables(args.v2_db, link_rows, diff_rows, old)

    linked = {link['old']: link['new'] for link in mapping['links']}
    audit = fuzzy_audit(old, items, linked)
    after = sha256(args.old_db)
    if before != after:
        fail(f'{args.old_db} changed while it was being read ({before} -> {after})')
    write_report(args.report, document, old, mapping, diffs, audit, (before, after), seed_check)

    linked_new = {new for link in mapping['links'] for new in link['new']}
    print(f'old rows: {len(old)} ({len(mapping["links"])} linked, '
          f'{len(mapping["unmapped_old"])} without a source line)')
    print(f'new items: {len(items)} ({len(linked_new)} linked, '
          f'{len(mapping["unmapped_new"])} not in the old extraction)')
    for cause, count in sorted(Counter(d['cause'] for d in diffs).items(), key=lambda kv: -kv[1]):
        print(f'  {count:>3}  {CAUSES[cause]}')
    print(f'mapping audit: {len(audit)} old rows whose curated link is not the best word match (appendix C)')
    print(f'{args.old_db.name}: sha256 unchanged ({after[:16]}…)')
    for path in (args.v2_db, args.report):
        print(f'wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}')


if __name__ == '__main__':
    sys.exit(main())
