//! The sticker sheets and inventory lists (`inventory/api/pdf.py`, which used reportlab).
//!
//! Both only need rectangles, lines, filled squares (the QR codes) and text in the two
//! built-in Helvetica fonts, so this writes PDF directly rather than through a library:
//! a few objects, one content stream per page. Text uses the fonts' WinAnsi encoding, as
//! reportlab's standard fonts did, and the same glyph widths (`metrics`), so lines wrap
//! where they wrapped before.

mod list;
mod metrics;
mod stickers;

use std::fmt::Write as _;
use std::io::Write as _;

use flate2::Compression;
use flate2::write::ZlibEncoder;

pub use list::make_list_pdf;
pub use stickers::make_stickers_pdf;

/// Points per millimetre, as `pdf.py` rounded it.
pub const MM: f64 = 2.8346;
/// A4 in points (reportlab's `A4`).
pub const PAGE_W: f64 = 595.275_590_551_181_2;
pub const PAGE_H: f64 = 841.889_763_779_527_7;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Font {
    Helvetica,
    HelveticaBold,
}

impl Font {
    fn resource(self) -> &'static str {
        match self {
            Self::Helvetica => "F1",
            Self::HelveticaBold => "F2",
        }
    }

    fn widths(self) -> &'static [u16; 256] {
        match self {
            Self::Helvetica => &metrics::HELVETICA,
            Self::HelveticaBold => &metrics::HELVETICA_BOLD,
        }
    }
}

/// A character's WinAnsi (cp1252) code; `?` for what the encoding lacks.
fn win_ansi(c: char) -> u8 {
    let code = u32::from(c);
    if code < 0x80 || (0xA0..=0xFF).contains(&code) {
        return u8::try_from(code).unwrap_or(b'?');
    }
    match c {
        '€' => 0x80,
        '‚' => 0x82,
        'ƒ' => 0x83,
        '„' => 0x84,
        '…' => 0x85,
        '†' => 0x86,
        '‡' => 0x87,
        'ˆ' => 0x88,
        '‰' => 0x89,
        'Š' => 0x8A,
        '‹' => 0x8B,
        'Œ' => 0x8C,
        'Ž' => 0x8E,
        '‘' => 0x91,
        '’' => 0x92,
        '“' => 0x93,
        '”' => 0x94,
        '•' => 0x95,
        '–' => 0x96,
        '—' => 0x97,
        '˜' => 0x98,
        '™' => 0x99,
        'š' => 0x9A,
        '›' => 0x9B,
        'œ' => 0x9C,
        'ž' => 0x9E,
        'Ÿ' => 0x9F,
        _ => b'?',
    }
}

/// `stringWidth(text, font, size)`.
pub fn string_width(text: &str, font: Font, size: f64) -> f64 {
    let widths = font.widths();
    let units: u32 = text.chars().map(|c| u32::from(widths[usize::from(win_ansi(c))])).sum();
    f64::from(units) * size / 1000.0
}

/// Greedy word wrap, as both reportlab's `Paragraph` and `pdf.py`'s `_word_wrap` did: a
/// word that does not fit on its own still gets its own line. An empty text is one empty
/// line.
pub fn word_wrap(text: &str, font: Font, size: f64, max_width: f64) -> Vec<String> {
    let mut words = text.split_whitespace();
    let Some(first) = words.next() else { return vec![String::new()] };
    let mut lines = Vec::new();
    let mut current = first.to_owned();
    for word in words {
        let candidate = format!("{current} {word}");
        if string_width(&candidate, font, size) <= max_width {
            current = candidate;
        } else {
            lines.push(std::mem::replace(&mut current, word.to_owned()));
        }
    }
    lines.push(current);
    lines
}

/// A number as PDF wants it: no exponent, at most four decimals, no trailing zeros.
fn num(value: f64) -> String {
    let text = format!("{value:.4}");
    let text = text.trim_end_matches('0').trim_end_matches('.');
    if text == "-0" { "0".to_owned() } else { text.to_owned() }
}

/// A PDF document being drawn, page by page (bottom-left origin, in points).
#[derive(Default)]
pub struct Document {
    pages: Vec<String>,
    current: String,
    started: bool,
}

impl Document {
    pub fn new() -> Self {
        Self::default()
    }

    fn op(&mut self, op: &str) {
        self.started = true;
        self.current.push_str(op);
        self.current.push('\n');
    }

    /// `showPage()`.
    pub fn new_page(&mut self) {
        self.pages.push(std::mem::take(&mut self.current));
        self.started = false;
    }

    pub fn stroke_rgb(&mut self, r: f64, g: f64, b: f64) {
        self.op(&format!("{} {} {} RG", num(r), num(g), num(b)));
    }

    pub fn fill_rgb(&mut self, r: f64, g: f64, b: f64) {
        self.op(&format!("{} {} {} rg", num(r), num(g), num(b)));
    }

    pub fn line_width(&mut self, width: f64) {
        self.op(&format!("{} w", num(width)));
    }

    pub fn stroke_rect(&mut self, x: f64, y: f64, w: f64, h: f64) {
        self.op(&format!("{} {} {} {} re S", num(x), num(y), num(w), num(h)));
    }

    pub fn fill_rect(&mut self, x: f64, y: f64, w: f64, h: f64) {
        self.op(&format!("{} {} {} {} re f", num(x), num(y), num(w), num(h)));
    }

    /// Several rectangles filled as one path: where they touch, no seam is rendered.
    pub fn fill_rects(&mut self, rects: &[(f64, f64, f64, f64)]) {
        if rects.is_empty() {
            return;
        }
        let mut path = String::with_capacity(rects.len() * 32);
        for (x, y, w, h) in rects {
            let _ = write!(path, "{} {} {} {} re ", num(*x), num(*y), num(*w), num(*h));
        }
        path.push('f');
        self.op(&path);
    }

    pub fn line(&mut self, x1: f64, y1: f64, x2: f64, y2: f64) {
        self.op(&format!("{} {} m {} {} l S", num(x1), num(y1), num(x2), num(y2)));
    }

    /// `drawString`: `text` with its baseline starting at `(x, y)`.
    pub fn text(&mut self, font: Font, size: f64, x: f64, y: f64, text: &str) {
        let mut literal = String::with_capacity(text.len() + 2);
        for c in text.chars() {
            match win_ansi(c) {
                b'(' => literal.push_str("\\("),
                b')' => literal.push_str("\\)"),
                b'\\' => literal.push_str("\\\\"),
                code if code.is_ascii() && !code.is_ascii_control() => literal.push(char::from(code)),
                code => {
                    let _ = write!(literal, "\\{code:03o}");
                }
            }
        }
        self.op(&format!("BT /{} {} Tf {} {} Td ({literal}) Tj ET", font.resource(), num(size), num(x), num(y)));
    }

    /// The finished file. A document nothing was drawn on still has one (blank) page, as
    /// reportlab's canvas does.
    pub fn finish(mut self) -> Vec<u8> {
        if self.started || self.pages.is_empty() {
            self.new_page();
        }
        let page_count = self.pages.len();
        // Objects: 1 catalog, 2 page tree, 3-4 fonts, then a page and its content per page.
        let mut objects: Vec<Vec<u8>> = vec![
            b"<< /Type /Catalog /Pages 2 0 R >>".to_vec(),
            format!(
                "<< /Type /Pages /Count {page_count} /Kids [{}] >>",
                (0..page_count).map(|i| format!("{} 0 R", 5 + 2 * i)).collect::<Vec<_>>().join(" ")
            )
            .into_bytes(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>".to_vec(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>".to_vec(),
        ];
        for (i, content) in self.pages.iter().enumerate() {
            objects.push(
                format!(
                    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {} {}] /Contents {} 0 R \
                     /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>",
                    num(PAGE_W),
                    num(PAGE_H),
                    6 + 2 * i
                )
                .into_bytes(),
            );
            let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
            let compressed = encoder.write_all(content.as_bytes()).and_then(|()| encoder.finish());
            let mut stream = match &compressed {
                Ok(data) => format!("<< /Length {} /Filter /FlateDecode >>\nstream\n", data.len()).into_bytes(),
                Err(_) => format!("<< /Length {} >>\nstream\n", content.len()).into_bytes(),
            };
            stream.extend_from_slice(compressed.as_deref().unwrap_or(content.as_bytes()));
            stream.extend_from_slice(b"\nendstream");
            objects.push(stream);
        }

        let mut pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n".to_vec();
        let mut offsets = Vec::with_capacity(objects.len());
        for (i, object) in objects.iter().enumerate() {
            offsets.push(pdf.len());
            pdf.extend_from_slice(format!("{} 0 obj\n", i + 1).as_bytes());
            pdf.extend_from_slice(object);
            pdf.extend_from_slice(b"\nendobj\n");
        }
        let xref = pdf.len();
        let mut trailer = format!("xref\n0 {}\n0000000000 65535 f \n", objects.len() + 1);
        for offset in offsets {
            let _ = writeln!(trailer, "{offset:010} 00000 n ");
        }
        let _ = write!(trailer, "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n", objects.len() + 1);
        pdf.extend_from_slice(trailer.as_bytes());
        pdf
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn widths_match_reportlab() {
        // `stringWidth('Qté : 3', 'Helvetica', 7)` and the bold one at 8.
        assert!((string_width("Qté : 3", Font::Helvetica, 7.0) - 21.014).abs() < 1e-9);
        assert!((string_width("Qté : 3", Font::HelveticaBold, 8.0) - 24.896).abs() < 1e-9);
        assert!((string_width("–·é€", Font::Helvetica, 1000.0) - 1946.0).abs() < 1e-9);
    }

    #[test]
    fn wraps_greedily() {
        assert_eq!(word_wrap("", Font::Helvetica, 7.0, 50.0), [""]);
        assert_eq!(word_wrap("one two three", Font::Helvetica, 7.0, 1000.0), ["one two three"]);
        assert_eq!(word_wrap("one two three", Font::Helvetica, 7.0, 25.0), ["one two", "three"]);
        assert_eq!(word_wrap("Supercalifragilistic x", Font::Helvetica, 7.0, 10.0), ["Supercalifragilistic", "x"]);
    }

    #[test]
    fn document_structure() {
        let mut doc = Document::new();
        doc.text(Font::Helvetica, 7.0, 10.0, 20.0, "Qté (x) – é\\");
        doc.new_page();
        doc.line(0.0, 0.0, 1.0, 1.0);
        let pdf = doc.finish();
        let text = String::from_utf8_lossy(&pdf);
        assert!(text.starts_with("%PDF-1.4"));
        assert!(text.contains("/Count 2"));
        assert!(text.ends_with("%%EOF\n"));
        assert_eq!(Document::new().finish().windows(8).filter(|w| w == b"/Count 1").count(), 1);
        assert_eq!(num(1.5), "1.5");
        assert_eq!(num(2.0), "2");
        assert_eq!(num(-0.00001), "0");
    }
}
