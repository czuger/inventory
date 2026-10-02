//! Sticker sheets: 105×57mm stickers, 2×5 on A4, each with the item's lines on the left
//! and a QR code of its page on the right (`make_stickers_pdf` in `pdf.py`).

use qrcode::bits::Bits;
use qrcode::{Color, EcLevel, QrCode, Version};

use super::{Document, Font, MM, PAGE_H, PAGE_W, word_wrap};

const STICKER_W: f64 = 105.0 * MM;
const STICKER_H: f64 = 57.0 * MM;
const COLS: usize = 2;
const ROWS: usize = 5;
const PAD: f64 = 3.0 * MM;
/// Between the text area and the QR code.
const GAP: f64 = 4.0 * MM;
const QR_SIZE: f64 = 45.0 * MM;
const FONT_SIZE: f64 = 7.0;
const LINE_H: f64 = FONT_SIZE * 1.4;
const TITLE_SIZE: f64 = 8.0;
/// Light modules around the code, as `qrcode.QRCode(border=1)`.
const QR_BORDER: usize = 1;

fn margin_x() -> f64 {
    (PAGE_W - COLS as f64 * STICKER_W) / 2.0
}

fn margin_y() -> f64 {
    (PAGE_H - ROWS as f64 * STICKER_H) / 2.0
}

/// `url` as Python's `qrcode` encoded it: byte mode, error correction M, the smallest
/// version that fits (`make(fit=True)`). The crate's own mode optimisation can pick a
/// denser version, with smaller modules on the printed sticker.
fn encode_qr(url: &str) -> Option<QrCode> {
    (1..=40).find_map(|version| {
        let mut bits = Bits::new(Version::Normal(version));
        bits.push_byte_data(url.as_bytes()).ok()?;
        bits.push_terminator(EcLevel::M).ok()?;
        QrCode::with_bits(bits, EcLevel::M).ok()
    })
}

/// The QR code of `url` as black squares in a `size` square at `(x, y)` (bottom-left),
/// filled as one shape so no hairline shows between neighbouring modules.
fn draw_qr(doc: &mut Document, url: &str, x: f64, y: f64, size: f64) {
    let Some(code) = encode_qr(url) else {
        tracing::error!("cannot encode {url:?} as a QR code");
        return;
    };
    let width = code.width();
    let module = size / (width + 2 * QR_BORDER) as f64;
    let colors = code.to_colors();
    let mut squares = Vec::new();
    for row in 0..width {
        // One rectangle per horizontal run of dark modules.
        let mut col = 0;
        while col < width {
            if colors[row * width + col] != Color::Dark {
                col += 1;
                continue;
            }
            let start = col;
            while col < width && colors[row * width + col] == Color::Dark {
                col += 1;
            }
            squares.push((
                x + (start + QR_BORDER) as f64 * module,
                y + size - (row + QR_BORDER + 1) as f64 * module,
                (col - start) as f64 * module,
                module,
            ));
        }
    }
    doc.fill_rgb(0.0, 0.0, 0.0);
    doc.fill_rects(&squares);
}

fn draw_sticker(doc: &mut Document, x: f64, y: f64, lines: &[String], url: &str) {
    // Cut border.
    doc.stroke_rgb(0.75, 0.75, 0.75);
    doc.line_width(0.5);
    doc.stroke_rect(x, y, STICKER_W, STICKER_H);

    // QR code: right side, vertically centered.
    let qr_x = x + STICKER_W - QR_SIZE - PAD;
    let qr_y = y + (STICKER_H - QR_SIZE) / 2.0;
    draw_qr(doc, url, qr_x, qr_y, QR_SIZE);

    // Vertical separator.
    let sep_x = qr_x - GAP / 2.0;
    doc.stroke_rgb(0.8, 0.8, 0.8);
    doc.line_width(0.4);
    doc.line(sep_x, y + PAD, sep_x, y + STICKER_H - PAD);

    if lines.is_empty() {
        return;
    }

    // Text area: from the left pad to the separator, minus half the gap.
    let text_x = x + PAD;
    let text_max_w = sep_x - x - PAD - GAP / 2.0;
    let mut wrapped = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        let (font, size) = if i == 0 { (Font::HelveticaBold, TITLE_SIZE) } else { (Font::Helvetica, FONT_SIZE) };
        for sub in word_wrap(line, font, size, text_max_w) {
            wrapped.push((sub, font, size));
        }
    }

    // Vertically centered block.
    let total_h = (wrapped.len() - 1) as f64 * LINE_H + TITLE_SIZE;
    let start_y = y + STICKER_H / 2.0 + total_h / 2.0;
    doc.fill_rgb(0.0, 0.0, 0.0);
    for (i, (text, font, size)) in wrapped.iter().enumerate() {
        doc.text(*font, *size, text_x, start_y - size - i as f64 * LINE_H, text);
    }
}

/// One sticker per `(lines, url)`, ten to a page.
pub fn make_stickers_pdf(stickers: &[(Vec<String>, String)]) -> Vec<u8> {
    let mut doc = Document::new();
    for (index, (lines, url)) in stickers.iter().enumerate() {
        if index > 0 && index % (COLS * ROWS) == 0 {
            doc.new_page();
        }
        let position = index % (COLS * ROWS);
        let (col, row) = (position % COLS, position / COLS);
        let x = margin_x() + col as f64 * STICKER_W;
        // The origin is bottom-left; row 0 is the top of the page.
        let y = PAGE_H - margin_y() - (row + 1) as f64 * STICKER_H;
        draw_sticker(&mut doc, x, y, lines, url);
    }
    doc.finish()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pages(pdf: &[u8]) -> usize {
        let text = String::from_utf8_lossy(pdf);
        text.split("/Count ").nth(1).and_then(|rest| rest.split_whitespace().next()?.parse().ok()).unwrap_or(0)
    }

    #[test]
    fn qr_codes_like_python() {
        // Python's qrcode gives version 3 (29 modules) and version 4 (33) for these.
        assert_eq!(encode_qr("http://localhost/test/miniatures/1").unwrap().width(), 29);
        assert_eq!(encode_qr("https://apps.ieroe.com/inventory/grognards/miniatures/1").unwrap().width(), 33);
    }

    #[test]
    fn ten_per_page() {
        let sticker = (vec!["Infantry".to_owned(), "Qté : 2".to_owned()], "http://localhost/t/miniatures/1".to_owned());
        assert_eq!(pages(&make_stickers_pdf(&[])), 1);
        assert_eq!(pages(&make_stickers_pdf(&vec![sticker.clone(); 10])), 1);
        assert_eq!(pages(&make_stickers_pdf(&vec![sticker; 11])), 2);
    }
}
