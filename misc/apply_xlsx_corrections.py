"""
Correct the application database from the fresh extraction of the club spreadsheet, in place.

Only what the sheet states and the application can hold is changed, on the existing rows: ids are kept, so
stickers, photos, borrowings and legacy ids stay attached. Nothing is deleted and no item is added.

    rooms         a spot stored under the wrong room is moved to the room the sheet's header gives
    wrong spot    an item whose mark is in another column is moved to the marked spot
    off-site      an item the sheet says is "chez ..." gets the location "Hors club / Chez ..."
    quantity      a quantity that differs from a single whole count in the sheet is set to that count
    scale         a scale the sheet contradicts is set to the sheet's, when the application knows that scale

Everything else the audit found is listed as left alone, with the reason.

Without --apply nothing is written: the plan is printed. With --apply the database is first copied to
data/backups/ (SQLite backup, safe with the WAL), then all changes are made in one transaction, each guarded by
the value it expects to replace. A JSON log of what was changed is written beside the backup.

Usage:
    python misc/extract_inventory_xlsx.py           # once, to build data/xlsx_extract/inventory_v2.json
    python misc/apply_xlsx_corrections.py           # dry run: print the plan
    python misc/apply_xlsx_corrections.py --apply   # back up, then apply

To undo: stop the app and copy the backup over data/inventory.sqlite3 (delete its -wal and -shm files).
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from compare_inventory_v1 import CAUSES, MAPPING, OLD_DB, ROOT, V2_JSON, check_mapping, compare, read_old  # noqa: E402
from inventory.db.constants import SCALES  # noqa: E402

BACKUPS = ROOT / 'data' / 'backups'
OFFSITE_ROOM = 'Hors club'

LEFT_ALONE = {
    'multi_location_collapsed': 'the application holds one location per item; the current spot is one of those marked',
    'quantity_in_name': 'the count is already in the name; changing the quantity would count it twice',
    'quantity_summed': 'the sheet counts different things; one integer cannot hold them',
    'quantity_assumed': 'the sheet gives no quantity',
    'approx_dropped': 'the application has no field for "about"',
    'unit_dropped': 'the application has no unit field for this item type',
    'struck_imported_as_live': 'the sheet marks it lost; deleting an item is your decision',
    'rows_merged': 'splitting a row would create new items without stickers',
    'row_split': 'already one row per finish, which the application needs',
    'value_not_in_source': 'not stated by the sheet, but not contradicted either',
    'remark_not_carried': 'no remarks field on this item type',
    'comment_not_carried': 'no field for it',
}


def fail(message):
    raise SystemExit(f'ERROR: {message}')


def find_diffs(db_path, document, mapping):
    old, old_locations = read_old(db_path)
    items = {item['id']: item for item in document['items']}
    sections = {section['id']: section for section in document['sections']}
    check_mapping(mapping, old, items)
    columns = {loc['spot'].casefold(): loc['columns'] for loc in document['locations']}
    diffs = []
    for link in mapping['links']:
        linked = [items[new] for new in link['new']]
        for field, old_value, new_value, cause, extra in compare(old[link['old']], link['relation'], linked,
                                                                 sections, columns):
            diffs.append({'old': link['old'], 'relation': link['relation'], 'field': field, 'old_value': old_value,
                          'new_value': new_value, 'cause': cause,
                          'source': ', '.join(f'{i["sheet"]} row {i["row"]}' for i in linked), **extra})
    return old, old_locations, diffs


def build_plan(old, old_locations, diffs, document):
    """-> (room changes, locations to create, item changes, left alone)"""
    rooms, new_locations, changes, skipped = [], [], [], []
    spelling = {location['room'].casefold(): location['room'] for location in old_locations}
    sheet_rooms = {loc['spot'].casefold(): loc['room'] for loc in document['locations']}
    for location in old_locations:
        wanted = sheet_rooms.get(location['spot'].casefold())
        if wanted and wanted.casefold() != location['room'].casefold():
            rooms.append({'id': location['id'], 'spot': location['spot'], 'old': location['room'],
                          'new': spelling.get(wanted.casefold(), wanted.capitalize())})
    by_spot = {location['spot'].casefold(): location for location in old_locations}

    def skip(diff, reason):
        skipped.append({'old': diff['old'], 'name': old[diff['old']]['name'], 'cause': diff['cause'],
                        'sheet': diff['new_value'], 'source': diff['source'], 'reason': reason})

    for diff in diffs:
        row, cause = old[diff['old']], diff['cause']
        change = {'table': row['table'], 'id': row['id'], 'name': row['name'], 'cause': cause, 'source': diff['source']}
        if cause == 'wrong_spot':
            if len(diff['target_spots']) != 1 or diff['target_spots'][0].casefold() not in by_spot:
                skip(diff, 'marked in several places, or in a spot the application does not have')
                continue
            target = by_spot[diff['target_spots'][0].casefold()]
            changes.append(dict(change, column='location', old=row['spot'], new=target['spot'],
                                location={'spot': target['spot']}))
        elif cause == 'location_invented':
            holders = set(diff['holders'])
            if diff['struck']:
                skip(diff, 'struck through in the sheet; its location is moot until you decide whether to delete it')
            elif len(holders) == 1:
                spot = f'Chez {holders.pop()}'
                if spot not in new_locations:
                    new_locations.append(spot)
                changes.append(dict(change, column='location', old=row['spot'], new=f'{OFFSITE_ROOM} / {spot}',
                                    location={'room': OFFSITE_ROOM, 'spot': spot}))
            else:
                skip(diff, 'the sheet gives no location at all; the current one is a guess, left as it is')
        elif cause in ('quantity_lost', 'quantity_differs'):
            target = diff.get('target_qty')
            if diff['relation'] == 'merged' or target is None:
                skip(diff, 'the row merges several sheet lines; no single count to store')
            elif target != int(target):
                skip(diff, 'not a whole number')
            else:
                changes.append(dict(change, column='quantity', old=row['quantity'], new=int(target)))
        elif cause == 'scale_differs':
            usable = [scale for scale in diff['target_scales'] if scale in SCALES]
            if len(diff['target_scales']) == 1 and usable:
                changes.append(dict(change, column='scale', old=row['scale'], new=usable[0]))
            else:
                skip(diff, f'the application only knows the scales {", ".join(SCALES)}')
        elif cause in LEFT_ALONE:
            skip(diff, LEFT_ALONE[cause])
        else:
            fail(f'no rule for the cause {cause!r}')
    return rooms, new_locations, changes, skipped


def backup(db_path, stamp):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    target = BACKUPS / f'{db_path.stem}-{stamp}-before-xlsx-corrections.sqlite3'
    source, copy = sqlite3.connect(db_path), sqlite3.connect(target)
    with copy:
        source.backup(copy)
    copy.close()
    source.close()
    return target


def apply(db_path, rooms, new_locations, changes):
    db = sqlite3.connect(db_path, isolation_level=None)
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('PRAGMA busy_timeout = 5000')
    db.execute('BEGIN IMMEDIATE')
    try:
        def one(sql, args, what):
            if db.execute(sql, args).rowcount != 1:
                raise RuntimeError(f'{what}: the row is not as expected; nothing was changed')

        for room in rooms:
            one('UPDATE locations SET room = ? WHERE id = ? AND room = ?', (room['new'], room['id'], room['old']),
                f'locations#{room["id"]}')
        for change in changes:
            table, item_id = change['table'], change['id']
            if change['column'] == 'location':
                association, current = db.execute(
                    f'SELECT t.association_id, l.spot FROM {table} t JOIN locations l ON l.id = t.location_id '
                    'WHERE t.id = ?', (item_id,)).fetchone()
                if current != change['old']:
                    raise RuntimeError(f'{table}#{item_id}: location is {current!r}, expected {change["old"]!r}')
                wanted = change['location']
                if 'room' in wanted:
                    db.execute('INSERT OR IGNORE INTO locations (association_id, room, spot) VALUES (?, ?, ?)',
                               (association, wanted['room'], wanted['spot']))
                    found = db.execute('SELECT id FROM locations WHERE association_id = ? AND room = ? AND spot = ?',
                                       (association, wanted['room'], wanted['spot'])).fetchall()
                else:
                    found = db.execute('SELECT id FROM locations WHERE association_id = ? AND spot = ?',
                                       (association, wanted['spot'])).fetchall()
                if len(found) != 1:
                    raise RuntimeError(f'{table}#{item_id}: {len(found)} locations match {wanted}')
                one(f'UPDATE {table} SET location_id = ? WHERE id = ?', (found[0][0], item_id), f'{table}#{item_id}')
            else:
                column = change['column']
                one(f'UPDATE {table} SET {column} = ? WHERE id = ? AND {column} = ?',
                    (change['new'], item_id, change['old']), f'{table}#{item_id}')
        problems = db.execute('PRAGMA foreign_key_check').fetchall()
        if problems:
            raise RuntimeError(f'foreign key problems: {problems[:3]}')
        db.execute('COMMIT')
    except Exception as error:
        db.execute('ROLLBACK')
        db.close()
        fail(f'{error}. Rolled back.')
    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', type=Path, default=OLD_DB, help='the application database to correct')
    parser.add_argument('--v2-json', type=Path, default=V2_JSON)
    parser.add_argument('--mapping', type=Path, default=MAPPING)
    parser.add_argument('--apply', action='store_true', help='write the changes (default: only print them)')
    args = parser.parse_args()

    document = json.loads(args.v2_json.read_text(encoding='utf-8'))
    mapping = json.loads(args.mapping.read_text(encoding='utf-8'))
    old, old_locations, diffs = find_diffs(args.db, document, mapping)
    rooms, new_locations, changes, skipped = build_plan(old, old_locations, diffs, document)

    print(f'{args.db}: {len(rooms)} room(s), {len(new_locations)} location(s) to create, {len(changes)} item change(s)')
    for room in rooms:
        print(f'  locations#{room["id"]:<3} {room["spot"]:<18} room: {room["old"]} -> {room["new"]}')
    for spot in new_locations:
        print(f'  new location        {OFFSITE_ROOM} / {spot}')
    for change in changes:
        key = f'{change["table"]}#{change["id"]}'
        print(f'  {key:<15} {change["name"][:38]:<38} {change["column"]}: {change["old"]} -> {change["new"]}   '
              f'[{change["source"]}]')
    print(f'left alone: {len(skipped)}')
    for reason, count in Counter(s['reason'] for s in skipped).most_common():
        print(f'  {count:>3}  {reason}')

    if not (rooms or changes):
        print('nothing to change')
        return
    if not args.apply:
        print('dry run: nothing was written. Add --apply to back up and apply.')
        return

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    saved = backup(args.db, stamp)
    apply(args.db, rooms, new_locations, changes)
    log = saved.with_name(f'{args.db.stem}-{stamp}-xlsx-corrections.json')
    log.write_text(json.dumps({'database': str(args.db), 'backup': str(saved), 'rooms': rooms,
                               'new_locations': [f'{OFFSITE_ROOM} / {spot}' for spot in new_locations],
                               'changes': changes, 'left_alone': skipped}, ensure_ascii=False, indent=1) + '\n',
                   encoding='utf-8')
    print(f'applied. backup: {saved.relative_to(ROOT) if saved.is_relative_to(ROOT) else saved}')
    print(f'log:     {log.relative_to(ROOT) if log.is_relative_to(ROOT) else log}')
    try:
        _, _, remaining = find_diffs(args.db, document, mapping)
    except SystemExit as error:   # e.g. the app is running and keeps the WAL busy: the changes are in all the same
        print(f'could not re-read the database to list what remains ({error}); run this script again without --apply')
        return
    print('still different from the sheet, by cause:')
    for cause, count in Counter(d['cause'] for d in remaining).most_common():
        print(f'  {count:>3}  {CAUSES[cause]}')


if __name__ == '__main__':
    sys.exit(main())
