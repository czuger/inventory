import io

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

MM = 2.8346  # points per mm

STICKER_W = 105 * MM
STICKER_H = 57 * MM
COLS = 2
ROWS = 5
PAGE_W, PAGE_H = A4  # 595.27 x 841.89 pt

MARGIN_X = (PAGE_W - COLS * STICKER_W) / 2
MARGIN_Y = (PAGE_H - ROWS * STICKER_H) / 2

PAD = 3 * MM
GAP = 4 * MM   # gap between text area and QR code
QR_SIZE = 45 * MM
FONT_SIZE = 7
LINE_H = FONT_SIZE * 1.4
TITLE_SIZE = 8


def _qr_image(url: str) -> ImageReader:
    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return ImageReader(buf)


def _word_wrap(c: canvas.Canvas, text: str, font: str, size: float, max_w: float) -> list[str]:
    words = text.split()
    if not words:
        return ['']
    result, current = [], words[0]
    for word in words[1:]:
        candidate = current + ' ' + word
        if c.stringWidth(candidate, font, size) <= max_w:
            current = candidate
        else:
            result.append(current)
            current = word
    result.append(current)
    return result


def _draw_sticker(c: canvas.Canvas, x: float, y: float, lines: list[str], url: str):
    # cut border
    c.setStrokeColorRGB(0.75, 0.75, 0.75)
    c.setLineWidth(0.5)
    c.rect(x, y, STICKER_W, STICKER_H)

    # QR code (right side, vertically centered)
    qr_x = x + STICKER_W - QR_SIZE - PAD
    qr_y = y + (STICKER_H - QR_SIZE) / 2
    c.drawImage(_qr_image(url), qr_x, qr_y, width=QR_SIZE, height=QR_SIZE)

    # vertical separator
    sep_x = qr_x - GAP / 2
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.setLineWidth(0.4)
    c.line(sep_x, y + PAD, sep_x, y + STICKER_H - PAD)

    if not lines:
        return

    # text area width: from left pad to separator minus half-gap margin
    text_x = x + PAD
    text_max_w = sep_x - x - PAD - GAP / 2

    # expand each input line into wrapped sub-lines
    wrapped = []  # list of (text, font, size)
    for i, line in enumerate(lines):
        font = 'Helvetica-Bold' if i == 0 else 'Helvetica'
        size = TITLE_SIZE if i == 0 else FONT_SIZE
        for sub in _word_wrap(c, line, font, size, text_max_w):
            wrapped.append((sub, font, size))

    # vertically center the block
    total_h = (len(wrapped) - 1) * LINE_H + TITLE_SIZE
    start_y = y + STICKER_H / 2 + total_h / 2

    c.setFillColorRGB(0, 0, 0)
    for i, (text, font, size) in enumerate(wrapped):
        c.setFont(font, size)
        c.drawString(text_x, start_y - size - i * LINE_H, text)


def make_stickers_pdf(stickers: list) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    for idx, (lines, url) in enumerate(stickers):
        if idx > 0 and idx % (COLS * ROWS) == 0:
            c.showPage()

        pos = idx % (COLS * ROWS)
        col = pos % COLS
        row = pos // COLS

        x = MARGIN_X + col * STICKER_W
        # reportlab origin is bottom-left; row 0 = top of page
        y = PAGE_H - MARGIN_Y - (row + 1) * STICKER_H

        _draw_sticker(c, x, y, lines, url)

    c.save()
    buf.seek(0)
    return buf.read()
