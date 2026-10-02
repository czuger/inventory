#!/usr/bin/env python3
"""Run the Flask app and the Rust app side by side and diff what they answer.

    python rust/parity/run_parity.py [--no-build] [--keep] [--verbose]

Both apps get a copy of the same database (built by Alembic, then seeded here), the same
secret key and the same (dummy) Discord credentials. Every request in the script below is
sent to both — Flask in-process through its test client, Rust over HTTP to a server
started on a free port — with the same session cookie, which both apps can read and sign.
Mutating requests run in the same order on both, so ids stay aligned.

Compared, per request: the status; Location, Content-Type, Content-Disposition, Vary and
Allow (as a set: werkzeug's order is hash-randomized per process); the session each app
writes back, decoded; and the body — HTML byte for byte (uuids of uploaded files
normalized), PDFs by page count and drawn text. At the end both databases are compared
table by table (timestamps and uuids normalized).

The differences MIGRATION_PLAN.md §6.3 lists are expected: those requests are marked
`expect=...` and reported, not counted as failures. Exit status 1 on any other difference.
"""
import argparse
import base64
import difflib
import io
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUST = REPO / 'rust'
SECRET = 'parity-secret-key'
DISCORD = {'client_id': 'parity-client', 'client_secret': 'parity-secret'}
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
STATE = re.compile(r'state=[A-Za-z0-9]{30}')

SEED = """
INSERT INTO associations (name, slug) VALUES ('Les Grognards d''Alsace', 'test'), ('Other Asso', 'other');
INSERT INTO games (name) VALUES ('Zeta Game'), ('Bolt Action'), ('Warhammer 40k');
INSERT INTO locations (association_id, room, spot) VALUES
  (1, 'Cave', ''), (1, 'Grenier', 'Étagère 2'), (2, 'Elsewhere', '');
INSERT INTO users (discord_id, username, display_name, is_admin) VALUES
  ('100', 'admin_user', 'The Admin', 1), ('200', 'plain', NULL, 0), ('300', 'other_user', 'O''Brien', 0);
INSERT INTO miniatures (association_id, category, type, game_id, scale, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Miniature', 'Infanterie "Garde" <impériale>', 2, '28mm', 5, 1, 0, 2, '["abc_photo.jpg"]'),
  (1, 'Miniature', 'Space Marines Tactical Squad with plasma gun and heavy bolter', 3, '28mm', 10, 0, 1, 1, '[]'),
  (2, 'Miniature', 'Theirs', 1, '15mm', 1, 0, 0, 3, '[]');
INSERT INTO terrains (association_id, category, type, game_id, scale, theater, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Terrain', 'Forêt', 1, '15mm', NULL, 1, 0, 1, 1, '[]'),
  (1, 'Terrain', 'Bocage', 2, '28mm', 'Normandie', 4, 4, 0, 2, '[]');
INSERT INTO tablecloths (association_id, category, type, material, game_id, size, remarks, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Tablecloth', 'Desert', 'vinyl', 2, '120x180', 'Taché & usé', 1, 1, 0, 1, '[]'),
  (1, 'Tablecloth', 'Snow', NULL, 1, '?x?', NULL, 2, 0, 0, 1, '[]');
INSERT INTO rulebooks (association_id, category, name, game_id, supplement, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Rulebook', 'Core Rules', 2, 1, 2, 0, 0, 2, '[]');
INSERT INTO board_games (association_id, category, name, universe, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Board Game', 'Chess', NULL, 1, 0, 0, 1, '[]'), (1, 'Board Game', 'Catan', '', 1, 0, 1, 1, '[]');
INSERT INTO books (association_id, category, name, universe, period, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Book', 'Osprey', 'WW2', '', 1, 0, 0, 1, '[]');
INSERT INTO equipment (association_id, category, type, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Equipment', 'Dice', 3, 0, 0, 1, '[]');
INSERT INTO consumables (association_id, category, type, unit, quantity, borrowing_count, sticker_printed, location_id, images) VALUES
  (1, 'Consumable', 'Paint', 'pots', 0, 0, 0, 1, '[]'), (1, 'Miniature', 'Glue', NULL, 2, 0, 0, 2, '[]');
INSERT INTO borrowings (association_id, borrower_id, item_id, item_type, action, date) VALUES
  (1, 2, 1, 'miniature', 'borrow', '2026-09-30 10:00:00.000000'),
  (1, 1, 1, 'miniature', 'return', '2026-09-30 12:30:00.123456'),
  (1, 2, 1, 'miniature', 'borrow', '2026-10-01 08:15:00.000000'),
  (1, 3, 1, 'tablecloth', 'borrow', '2026-10-01 09:00:00.000000');
INSERT INTO duplicate_links (association_id, item1_id, item1_type, item2_id, item2_type, created_at) VALUES
  (1, 1, 'miniature', 1, 'rulebook', '2026-10-01 08:00:00.000000'),
  (1, 1, 'terrain', 1, 'miniature', '2026-10-01 08:00:00.000000'),
  (1, 99, 'book', 1, 'miniature', '2026-10-01 08:00:00.000000');
INSERT INTO legacy_object_ids (object_id, item_type, item_id) VALUES
  ('65f0c0ffee0123456789abcd', 'miniature', 2), ('65f0c0ffee0123456789abce', 'board_game', 1);
"""


# --- PDFs --------------------------------------------------------------------------

def _streams(pdf: bytes):
    for match in re.finditer(rb'<<(.*?)>>\s*stream\r?\n', pdf, re.S):
        start = match.end()
        end = pdf.index(b'endstream', start)
        data, filters = pdf[start:end].rstrip(b'\r\n'), match.group(1)
        if b'ASCII85Decode' in filters:
            data = base64.a85decode(data.strip().rstrip(b'~>') + b'~>', adobe=True)
        if b'FlateDecode' in filters:
            data = zlib.decompress(data)
        yield data


def _unescape(literal: bytes) -> str:
    out, i = bytearray(), 0
    while i < len(literal):
        c = literal[i]
        if c == 0x5C:  # backslash
            nxt = literal[i + 1:i + 4]
            octal = re.match(rb'[0-7]{1,3}', nxt)
            if octal:
                out.append(int(octal.group(), 8))
                i += 1 + len(octal.group())
                continue
            out.append(literal[i + 1])
            i += 2
            continue
        out.append(c)
        i += 1
    return out.decode('cp1252', 'replace')


def pdf_summary(pdf: bytes):
    """(page count, drawn strings in order)."""
    tree = next(m.group(1) for m in re.finditer(rb'<<((?:(?!>>).)*)>>', pdf, re.S) if re.search(rb'/Type\s*/Pages\b', m.group(1)))
    pages = int(re.search(rb'/Count\s+(\d+)', tree).group(1))
    texts = []
    for stream in _streams(pdf):
        texts += [_unescape(m.group(1)) for m in re.finditer(rb'\(((?:\\.|[^\\)])*)\)\s*Tj', stream, re.S)]
    return pages, texts


def strip_markup(text: str) -> str:
    return ' '.join(re.sub(r'<[^>]*>', '', text).split())


# --- the two apps ------------------------------------------------------------------

class Response:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, {k.lower(): v for k, v in headers}, body
        self.set_cookies = [v for k, v in headers if k.lower() == 'set-cookie']


def multipart(files):
    boundary = 'PARITYBOUNDARY'
    body = b''
    for field, filename, data in files:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                 f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + b'\r\n'
    body += f'--{boundary}--\r\n'.encode()
    return f'multipart/form-data; boundary={boundary}', body


class FlaskApp:
    def __init__(self, db, static_dir, prefix):
        import inventory.libs.initialization as init
        init.load_config = lambda: {'discord': DISCORD}
        init.load_secret_key = lambda: SECRET
        os.environ['DATABASE_URL'] = f'sqlite:///{db}'
        os.environ['URL_PREFIX'] = prefix
        logging.disable(logging.CRITICAL)
        from inventory.api.app import create_app
        self.app = create_app()
        self.app.static_folder = str(static_dir)
        self.client = self.app.test_client(use_cookies=False)
        self.serializer = self.app.session_interface.get_signing_serializer(self.app)

    def request(self, method, path, headers, body, content_type):
        kwargs = {'method': method, 'headers': headers}
        if body is not None:
            kwargs['data'] = body
            kwargs['content_type'] = content_type
        r = self.client.open(path, **kwargs)
        return Response(r.status_code, list(r.headers.items()), r.get_data())


class RustApp:
    def __init__(self, db, uploads, prefix, work):
        root = work / f'rust_root{prefix.replace("/", "_")}'
        root.mkdir(exist_ok=True)
        (root / 'README.md').touch()
        (root / 'config.json').write_text(json.dumps({'discord': DISCORD}))
        (root / 'secret_key.txt').write_text(SECRET)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            self.port = s.getsockname()[1]
        env = {**os.environ, 'INVENTORY_ROOT': str(root), 'DATABASE_URL': f'sqlite:///{db}', 'UPLOADS_DIR': str(uploads),
               'BIND_ADDR': f'127.0.0.1:{self.port}', 'URL_PREFIX': prefix, 'RUST_LOG': 'error'}
        binary = RUST / 'target' / 'debug' / 'inventory'
        subprocess.run([binary, 'migrate'], env=env, check=True, capture_output=True)
        self.process = subprocess.Popen([binary, 'serve'], env=env)
        for _ in range(100):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health')
                break
            except OSError:
                time.sleep(0.05)
        self.opener = urllib.request.build_opener(type('NoRedirect', (urllib.request.HTTPRedirectHandler,), {
            'redirect_request': lambda *a, **k: None}))

    def request(self, method, path, headers, body, content_type):
        headers = dict(headers)
        if body is not None:
            headers['Content-Type'] = content_type
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=body, method=method, headers=headers)
        try:
            r = self.opener.open(req)
        except urllib.error.HTTPError as e:
            r = e
        return Response(r.status, list(r.headers.items()), r.read())

    def stop(self):
        self.process.terminate()
        self.process.wait()


# --- comparing ---------------------------------------------------------------------

class Parity:
    def __init__(self, flask, rust, cookie_name, verbose):
        self.flask, self.rust, self.cookie_name, self.verbose = flask, rust, cookie_name, verbose
        self.cookies = {}  # session label -> (flask cookie, rust cookie)
        self.count = self.differences = self.expected = 0

    def forge(self, label, data):
        cookie = self.flask.serializer.dumps(data)
        self.cookies[label] = (cookie, cookie)

    def decode(self, cookie):
        if not cookie:
            return {}
        data = self.flask.serializer.loads(cookie)
        return {('_state_discord_<state>' if k.startswith('_state_discord_') else k):
                ('<state>' if k.startswith('_state_discord_') else v) for k, v in data.items()}

    def _new_cookie(self, response, old):
        for header in response.set_cookies:
            name, _, rest = header.partition('=')
            if name == self.cookie_name:
                value = rest.split(';')[0]
                return value or None, header
        return old, None

    @staticmethod
    def _normalize(text: str) -> str:
        return STATE.sub('state=<state>', UUID.sub('<uuid>', text))

    def compare(self, label, method, path, session='anon', form=None, files=None, referer=None, expect=None):
        self.count += 1
        cookies = self.cookies.get(session, (None, None))
        body = content_type = None
        if files is not None:
            content_type, body = multipart(files)
        elif form is not None:
            content_type = 'application/x-www-form-urlencoded'
            body = urllib.parse.urlencode(form).encode()
        results = []
        for app, cookie in ((self.flask, cookies[0]), (self.rust, cookies[1])):
            headers = {'Host': 'localhost'}
            if cookie:
                headers['Cookie'] = f'{self.cookie_name}={cookie}'
            if referer:
                headers['Referer'] = referer
            results.append(app.request(method, path, headers, body, content_type))
        a, b = results
        new_a, set_a = self._new_cookie(a, cookies[0])
        new_b, set_b = self._new_cookie(b, cookies[1])
        self.cookies[session] = (new_a, new_b)

        problems = []
        if a.status != b.status:
            problems.append(f'status {a.status} vs {b.status}')
        for name in ('location', 'content-type', 'content-disposition', 'vary'):
            va, vb = (self._normalize(r.headers.get(name, '')) for r in (a, b))
            if va != vb:
                problems.append(f'{name}: {va!r} vs {vb!r}')
        allow_a, allow_b = ({m.strip() for m in r.headers.get('allow', '').split(',') if m.strip()} for r in (a, b))
        if allow_a != allow_b:
            problems.append(f'allow: {sorted(allow_a)} vs {sorted(allow_b)}')
        if (set_a is None) != (set_b is None):
            problems.append(f'set-cookie: {set_a!r} vs {set_b!r}')
        elif set_a is not None:
            attrs_a, attrs_b = (h.split(';', 1)[1] if ';' in h else '' for h in (set_a, set_b))
            if attrs_a != attrs_b:
                problems.append(f'cookie attributes: {attrs_a!r} vs {attrs_b!r}')
            if self.decode(new_a) != self.decode(new_b):
                problems.append(f'session: {self.decode(new_a)} vs {self.decode(new_b)}')

        body_diff = []
        ctype = a.headers.get('content-type', '')
        if ctype == 'application/pdf' and b.headers.get('content-type') == 'application/pdf':
            # reportlab read item names as markup (an unknown tag vanished); Rust prints them as
            # they are (§6.3). Strip tags on both sides so everything else is still compared.
            sa, sb = (pdf_summary(r.body) for r in (a, b))
            sa, sb = ((n, [strip_markup(t) for t in texts]) for n, texts in (sa, sb))
            if sa[0] != sb[0]:
                problems.append(f'pdf pages {sa[0]} vs {sb[0]}')
            if sa[1] != sb[1]:
                problems.append('pdf text differs')
                body_diff = list(difflib.unified_diff(sa[1], sb[1], 'flask', 'rust', lineterm='', n=1))
        elif self._normalize(a.body.decode('utf-8', 'replace')) != self._normalize(b.body.decode('utf-8', 'replace')):
            problems.append('body differs')
            body_diff = list(difflib.unified_diff(
                self._normalize(a.body.decode('utf-8', 'replace')).splitlines(),
                self._normalize(b.body.decode('utf-8', 'replace')).splitlines(), 'flask', 'rust', lineterm='', n=1))

        if not problems:
            if expect:
                print(f'  NOTE   {label}: expected a difference ({expect}) but both agree')
            elif self.verbose:
                print(f'  ok     {label}')
            return
        if expect:
            self.expected += 1
            print(f'  EXPECT {label}: {"; ".join(problems)}  [{expect}]')
            return
        self.differences += 1
        print(f'  DIFF   {method} {path} [{session}] {label}: {"; ".join(problems)}')
        for line in body_diff[:40]:
            print('         ' + line)


# --- the requests ------------------------------------------------------------------

SEGMENTS = ['miniatures', 'terrains', 'tablecloths', 'rulebooks', 'board-games', 'books', 'equipment', 'consumables']

FORMS = {
    'miniatures': {'category': 'Miniature', 'type': 'Cavalerie', 'game': '2', 'scale': '28mm', 'quantity': '3', 'location': '2'},
    'terrains': {'category': 'Terrain', 'type': 'Haies', 'game': '1', 'scale': '15mm', 'theater': '', 'quantity': '', 'location': '1'},
    'tablecloths': {'category': 'Tablecloth', 'quantity': '1', 'type': 'Mer', 'material': 'cloth', 'game': '1',
                    'size': '120x90', 'remarks': '', 'location': '1'},
    'rulebooks': {'category': 'Rulebook', 'name': 'Livre de règles', 'game': '3', 'supplement': 'on', 'quantity': '1', 'location': '1'},
    'board-games': {'category': 'Board Game', 'name': 'Go', 'universe': 'Asie', 'quantity': '2', 'location': '2'},
    'books': {'category': 'Book', 'name': "L'Art de la guerre", 'universe': '', 'period': 'Antiquité', 'quantity': '1', 'location': '1'},
    'equipment': {'category': 'Equipment', 'type': 'Mètre ruban', 'quantity': '4', 'location': '1'},
    'consumables': {'category': 'Consumable', 'type': 'Colle', 'unit': 'tubes', 'location': '2'},
}


def scenario(p: Parity):
    p.forge('anon', {})
    p.forge('user', {'user_id': 2})
    p.forge('admin', {'user_id': 1, 'lang': 'en'})
    p.forge('admin_fr', {'user_id': 1})
    p.forge('mongo', {'user_id': '65f0c0ffee0123456789abcd', 'lang': 'en'})

    print('pages')
    for session in ('anon', 'user', 'admin', 'admin_fr'):
        for seg in SEGMENTS:
            for rest in ('', '1', 'new', '1/edit', '2', 'stickers' if session == 'user' else '1'):
                p.compare(f'GET {seg}/{rest}', 'GET', f'/test/{seg}/{rest}', session)
        p.compare('print page', 'GET', '/test/print/', session)
        p.compare('print page, category', 'GET', '/test/print/?category=Board+Game', session)
        p.compare('index', 'GET', '/', session)
    p.compare('mongo-era session', 'GET', '/test/miniatures/', 'mongo')

    print('routing and errors')
    for label, method, path in [
        ('health', 'GET', '/health'), ('health HEAD', 'HEAD', '/health'), ('health POST', 'POST', '/health'),
        ('health OPTIONS', 'OPTIONS', '/health'), ('OPTIONS new', 'OPTIONS', '/test/miniatures/new'),
        ('trailing slash', 'GET', '/test/miniatures?x=1'), ('trailing slash POST', 'POST', '/test/miniatures'),
        ('print trailing slash', 'GET', '/test/print'), ('extra slash', 'GET', '/health/'),
        ('not an id', 'GET', '/test/miniatures/abc'), ('padded id', 'GET', '/test/miniatures/007'),
        ('negative id', 'GET', '/test/miniatures/-1'), ('unknown slug', 'GET', '/nope/miniatures/'),
        ('other association', 'GET', '/test/miniatures/3'), ('own association', 'GET', '/other/miniatures/3'),
        ('delete by GET', 'GET', '/test/miniatures/1/delete'), ('missing item', 'GET', '/test/books/999'),
        ('legacy sticker', 'GET', '/test/miniatures/65f0c0ffee0123456789abcd'),
        ('legacy sticker, other slug', 'GET', '/anything/board-games/65f0c0ffee0123456789abce'),
        ('legacy, wrong type', 'GET', '/test/terrains/65f0c0ffee0123456789abcd'),
        ('legacy, unknown', 'GET', '/test/miniatures/65f0c0ffee0123456789abff'),
        ('static', 'GET', '/static/favicon.png'), ('static missing', 'GET', '/static/nope.png'),
        ('upload served', 'GET', '/static/uploads/miniature/1/abc_photo.jpg'),
        ('unknown page', 'GET', '/no/such/page'),
    ]:
        p.compare(label, method, path, 'admin')

    print('gates')
    for seg in SEGMENTS:
        p.compare(f'{seg} create as user', 'POST', f'/test/{seg}/new', 'user', form=FORMS[seg])
        p.compare(f'{seg} delete as anon', 'POST', f'/test/{seg}/1/delete', 'anon')
        p.compare(f'{seg} borrow as anon', 'POST', f'/test/{seg}/1/borrow', 'anon')
        p.compare(f'{seg} stickers as user', 'GET', f'/test/{seg}/stickers', 'user')
    p.compare('print stickers as user', 'POST', '/test/print/stickers', 'user', form={'mode': 'full'})

    print('create, edit')
    for seg in SEGMENTS:
        p.compare(f'{seg} create', 'POST', f'/test/{seg}/new', 'admin', form=FORMS[seg])
    for seg in SEGMENTS:
        # The new item is the highest id; Flask and Rust both flash on the next page.
        new_id = {'miniatures': 4, 'terrains': 3, 'tablecloths': 3, 'rulebooks': 2, 'board-games': 3, 'books': 2,
                  'equipment': 2, 'consumables': 3}[seg]
        p.compare(f'{seg} new item page', 'GET', f'/test/{seg}/{new_id}', 'admin')
        edited = dict(FORMS[seg], sticker_printed='on')
        first = next(k for k in ('type', 'name') if k in edited)
        edited[first] = edited[first] + ' (modifié)'
        p.compare(f'{seg} edit', 'POST', f'/test/{seg}/{new_id}/edit', 'admin', form=edited)
        p.compare(f'{seg} edited page', 'GET', f'/test/{seg}/{new_id}', 'admin')
    bad = dict(FORMS['miniatures'])
    p.compare('missing field', 'POST', '/test/miniatures/new', 'admin', form={k: v for k, v in bad.items() if k != 'type'})
    p.compare('unknown game', 'POST', '/test/miniatures/new', 'admin', form=dict(bad, game='999'))
    p.compare('game not a number', 'POST', '/test/miniatures/new', 'admin', form=dict(bad, game='x'))
    p.compare('other association location', 'POST', '/test/miniatures/new', 'admin', form=dict(bad, location='3'))
    p.compare('padded quantity', 'POST', '/test/miniatures/new', 'admin', form=dict(bad, quantity=' 0_7 '))
    p.compare('quantity not a number', 'POST', '/test/miniatures/new', 'admin', form=dict(bad, quantity='lots'),
              expect='§6.3: 500 in Python, 400 now')
    p.compare('bad material', 'POST', '/test/tablecloths/new', 'admin', form=dict(FORMS['tablecloths'], material='silk'),
              expect='§6.3: 500 in Python, 400 now')
    p.compare('after the errors', 'GET', '/test/miniatures/', 'admin')

    print('borrowing')
    back = 'http://localhost/test/miniatures/2'
    p.compare('borrow', 'POST', '/test/miniatures/2/borrow', 'user', referer=back)
    p.compare('borrow again', 'POST', '/test/miniatures/2/borrow', 'admin', referer=back)
    p.compare('return', 'POST', '/test/miniatures/2/return', 'user', referer=back)
    p.compare('return below zero', 'POST', '/test/books/1/return', 'user', referer='http://localhost/test/books/1')
    p.compare('borrow, no referer', 'POST', '/test/books/1/borrow', 'user', expect='§6.3: 500 in Python, item page now')
    for session in ('user', 'admin', 'anon'):
        p.compare(f'history as {session}', 'GET', '/test/miniatures/2', session)

    print('duplicates')
    links = 'http://localhost/test/miniatures/2'
    for label, url in [
        ('add', 'http://localhost/test/board-games/1'), ('add again', 'http://localhost/test/board-games/1'),
        ('reverse', None), ('self', links), ('invalid', 'not-a-url'), ('unknown type', 'http://localhost/test/dragons/1'),
        ('missing item', 'http://localhost/test/books/999'), ('other association', 'http://localhost/other/miniatures/3'),
        ('legacy url', 'http://localhost/test/board-games/65f0c0ffee0123456789abce'),
        ('relative url', '/test/equipment/1'),
    ]:
        if url is None:
            p.compare(label, 'POST', '/test/board-games/1/duplicates', 'admin',
                      form={'duplicate_url': links}, referer='http://localhost/test/board-games/1/edit')
        else:
            p.compare(f'link {label}', 'POST', '/test/miniatures/2/duplicates', 'admin',
                      form={'duplicate_url': url}, referer=links)
    p.compare('link as user', 'POST', '/test/miniatures/2/duplicates', 'user', form={'duplicate_url': links})
    p.compare('links shown', 'GET', '/test/miniatures/2', 'admin')
    p.compare('links on edit page', 'GET', '/test/board-games/1/edit', 'admin')
    p.compare('unlink', 'POST', '/test/miniatures/2/duplicates/4/delete', 'admin', referer=links)
    p.compare('unlink unknown', 'POST', '/test/miniatures/2/duplicates/999/delete', 'admin', referer=links)
    p.compare('link without referer', 'POST', '/test/miniatures/1/duplicates', 'admin',
              form={'duplicate_url': 'http://localhost/test/equipment/1'})

    print('photos')
    show = 'http://localhost/test/board-games/1'
    p.compare('upload', 'POST', '/test/board-games/1/images', 'admin', referer=show,
              files=[('images', 'Partie d’été (1).jpg', b'one'), ('images', '', b''), ('images', 'b.png', b'two')])
    p.compare('photos shown', 'GET', '/test/board-games/1', 'admin')
    p.compare('delete unknown photo', 'POST', '/test/board-games/1/images/nope.jpg/delete', 'admin', referer=show)
    p.compare('upload as user', 'POST', '/test/board-games/1/images', 'user', files=[('images', 'x.jpg', b'x')])
    p.compare('upload, no referer', 'POST', '/test/equipment/1/images', 'admin', files=[('images', 'x.jpg', b'x')],
              expect='§6.3: 500 in Python, item page now')

    print('printing')
    for label, form in [('stickers, new only', {'mode': 'new'}), ('list, full', {'mode': 'full'}),
                        ('list, category', {'mode': 'category', 'category': 'Board Game'}),
                        ('list, unknown category', {'mode': 'category', 'category': 'Dragons'}),
                        ('stickers, category', {'mode': 'category', 'category': 'Terrain'}),
                        ('list, new only', {'mode': 'new'}), ('stickers, full', {'mode': 'full'})]:
        kind = 'stickers' if label.startswith('stickers') else 'list'
        p.compare(label, 'POST', f'/test/print/{kind}', 'admin', form=form)
    for seg in SEGMENTS:
        p.compare(f'{seg} stickers', 'GET', f'/test/{seg}/stickers', 'admin')
    p.compare('everything printed', 'GET', '/test/miniatures/', 'admin')

    print('delete, language, auth')
    p.compare('delete', 'POST', '/test/equipment/1/delete', 'admin', referer='http://localhost/test/equipment/1')
    p.compare('after delete', 'GET', '/test/equipment/', 'admin')
    p.compare('history of a deleted item', 'GET', '/test/miniatures/2', 'admin')
    for lang in ('en', 'fr', 'de'):
        p.compare(f'set-language {lang}', 'GET', f'/set-language/{lang}', 'user', referer='http://localhost/test/books/')
    p.compare('set-language, no referer', 'GET', '/set-language/en', 'anon')
    p.compare('page in the chosen language', 'GET', '/test/books/', 'user')
    p.compare('discord login', 'GET', '/auth/discord', 'anon')
    p.compare('discord callback, bad state', 'GET', '/auth/discord/callback?code=x&state=forged', 'anon',
              expect='§6.3: 500 in Python, back home with a message')
    p.compare('logout', 'GET', '/auth/logout', 'user')
    p.compare('logout again', 'GET', '/auth/logout', 'user')
    p.compare('logged out', 'GET', '/test/books/', 'user')


def prefixed_scenario(p: Parity):
    p.forge('admin', {'user_id': 1, 'lang': 'en'})
    p.compare('index', 'GET', '/', 'admin')
    p.compare('list links', 'GET', '/test/miniatures/', 'admin')
    p.compare('show links', 'GET', '/test/miniatures/1', 'admin')
    p.compare('trailing slash', 'GET', '/test/books', 'admin')
    p.compare('legacy sticker', 'GET', '/test/miniatures/65f0c0ffee0123456789abcd', 'admin')
    p.compare('set-language', 'GET', '/set-language/fr', 'admin')
    p.compare('discord login', 'GET', '/auth/discord', 'admin')
    p.compare('sticker urls', 'GET', '/test/books/stickers', 'admin')
    p.compare('link a production url', 'POST', '/test/books/1/duplicates', 'admin',
              form={'duplicate_url': 'https://localhost/inventory/test/rulebooks/1'},
              referer='http://localhost/inventory/test/books/1',
              expect='§6.3: refused in Python (prefix not stripped), linked now')


# --- databases ---------------------------------------------------------------------

def dump(db):
    con = sqlite3.connect(db)
    tables = [t for (t,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('sqlite_sequence', '_sqlx_migrations') ORDER BY name")]
    out = {}
    for table in tables:
        rows = []
        for row in con.execute(f'SELECT * FROM {table} ORDER BY rowid'):
            row = list(row)
            for i, value in enumerate(row):
                if isinstance(value, str):
                    value = UUID.sub('<uuid>', value)
                    if re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{6}', value) and value >= '2026-10-02':
                        value = '<now>'
                row[i] = value
            rows.append(tuple(row))
        out[table] = rows
    seq = dict(con.execute('SELECT name, seq FROM sqlite_sequence'))
    con.close()
    return out, seq


def compare_databases(py_db, rs_db, expected_tables=()):
    (py, py_seq), (rs, rs_seq) = dump(py_db), dump(rs_db)
    problems = 0
    for table in sorted(set(py) | set(rs)):
        a, b = py.get(table), rs.get(table)
        if a == b:
            continue
        note = 'EXPECT' if table in expected_tables else 'DIFF  '
        problems += table not in expected_tables
        print(f'  {note} table {table}: {len(a or [])} vs {len(b or [])} rows')
        for line in list(difflib.unified_diff([repr(r) for r in a or []], [repr(r) for r in b or []],
                                              'flask', 'rust', lineterm='', n=0))[:20]:
            print('         ' + line)
    for table in sorted(set(py_seq) | set(rs_seq)):
        if py_seq.get(table) != rs_seq.get(table):
            expected = table in expected_tables
            problems += not expected
            print(f'  {"EXPECT" if expected else "DIFF  "} sqlite_sequence {table}: {py_seq.get(table)} vs {rs_seq.get(table)}')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--no-build', action='store_true', help='use the existing debug binary')
    parser.add_argument('--keep', action='store_true', help='keep the work directory')
    parser.add_argument('--verbose', action='store_true', help='list matching requests too')
    args = parser.parse_args()

    if not args.no_build:
        subprocess.run(['cargo', 'build', '--quiet'], cwd=RUST, check=True)
    sys.path.insert(0, str(REPO))
    work = Path(tempfile.mkdtemp(prefix='parity-'))
    print(f'work directory: {work}')
    failures = 0
    try:
        for prefix in ('', 'inventory'):
            print(f'\n=== {"no prefix" if not prefix else "URL_PREFIX=" + prefix} ===')
            py_db, rs_db = work / f'py{prefix}.sqlite3', work / f'rs{prefix}.sqlite3'
            subprocess.run(['alembic', 'upgrade', 'head'], cwd=REPO, check=True, capture_output=True,
                           env={**os.environ, 'DATABASE_URL': f'sqlite:///{py_db}'})
            con = sqlite3.connect(py_db)
            con.executescript(SEED)
            con.commit()
            con.close()
            shutil.copy(py_db, rs_db)
            # Each app writes photos into its own copy of the static folder.
            py_static, rs_static = work / f'py_static{prefix}', work / f'rs_static{prefix}'
            shutil.copytree(REPO / 'inventory/api/static', py_static, ignore=shutil.ignore_patterns('uploads'))
            for static in (py_static, rs_static):
                (static / 'uploads/miniature/1').mkdir(parents=True)
                (static / 'uploads/miniature/1/abc_photo.jpg').write_bytes(b'photo')

            flask = FlaskApp(py_db, py_static, prefix)
            rust = RustApp(rs_db, rs_static / 'uploads', prefix, work)
            parity = Parity(flask, rust, f'session_{prefix}' if prefix else 'session', args.verbose)
            try:
                (prefixed_scenario if prefix else scenario)(parity)
            finally:
                rust.stop()
            print('databases')
            db_failures = compare_databases(py_db, rs_db, expected_tables={'duplicate_links'} if prefix else ())
            print(f'{parity.count} requests: {parity.differences} unexpected differences, {parity.expected} expected; '
                  f'{db_failures} unexpected database differences')
            failures += parity.differences + db_failures
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f'\n{"PARITY OK" if not failures else f"{failures} UNEXPECTED DIFFERENCES"}')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
