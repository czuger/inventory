//! The printed inventory list: a title, then a table (name, details, quantity, location)
//! whose header repeats on every page (`make_list_pdf` in `pdf.py`).
//!
//! It reproduces the layout reportlab's platypus computed — frame padding, the title's
//! leading and space after, each row as tall as its tallest wrapped cell, the table split
//! between rows — so the list breaks across pages where it used to. The tests pin page
//! counts measured with reportlab.

use super::{Document, Font, MM, PAGE_H, PAGE_W, string_width, word_wrap};

const MARGIN: f64 = 15.0 * MM;
/// `Frame`'s default padding on every side.
const FRAME_PAD: f64 = 6.0;
const COL_FRACTIONS: [f64; 4] = [0.39, 0.26, 0.06, 0.29];
const HEADERS: [&str; 4] = ["Nom / Type", "Détails", "Qté", "Emplacement"];

const TITLE_SIZE: f64 = 18.0;
const TITLE_LEADING: f64 = 22.0;
const TITLE_SPACE_AFTER: f64 = 6.0;
const SPACER: f64 = 6.0 * MM;

const CELL_SIZE: f64 = 8.0;
const CELL_LEADING: f64 = 10.0;
const PAD_TOP: f64 = 3.0;
const PAD_BOTTOM: f64 = 3.0;
const PAD_SIDE: f64 = 4.0;
/// reportlab's `_FUZZ` when checking whether a flowable fits.
const FUZZ: f64 = 1e-6;

fn hex(rgb: u32) -> (f64, f64, f64) {
    let channel = |shift: u32| f64::from((rgb >> shift) & 0xFF) / 255.0;
    (channel(16), channel(8), channel(0))
}

struct Row {
    /// Wrapped lines per cell.
    cells: [Vec<String>; 4],
    height: f64,
}

fn layout_row(values: [String; 4], font: Font, widths: &[f64; 4]) -> Row {
    let cells = std::array::from_fn(|i| {
        // A Paragraph of nothing has no lines at all (height 0), unlike a sticker line.
        if values[i].trim().is_empty() {
            Vec::new()
        } else {
            word_wrap(&values[i], font, CELL_SIZE, widths[i] - 2.0 * PAD_SIDE)
        }
    });
    let tallest = cells.iter().map(Vec::len).max().unwrap_or(0);
    Row { cells, height: tallest as f64 * CELL_LEADING + PAD_TOP + PAD_BOTTOM }
}

/// Draws rows `range` of the table (row 0 is the header) with its top at `top`.
fn draw_rows(doc: &mut Document, rows: &[Row], indices: &[usize], widths: &[f64; 4], x0: f64, top: f64) {
    let table_w: f64 = widths.iter().sum();
    // Backgrounds: the header, and every other data row by its original index.
    let mut y = top;
    for &index in indices {
        let row = &rows[index];
        let background = match index {
            0 => Some(hex(0x4a4a4a)),
            i if i >= 2 && i % 2 == 0 => Some(hex(0xf5f5f5)),
            _ => None,
        };
        if let Some((r, g, b)) = background {
            doc.fill_rgb(r, g, b);
            doc.fill_rect(x0, y - row.height, table_w, row.height);
        }
        y -= row.height;
    }

    // Grid around the data cells, and a white line under the header.
    let mut y = top;
    for &index in indices {
        let height = rows[index].height;
        if index == 0 {
            let (r, g, b) = hex(0xffffff);
            doc.stroke_rgb(r, g, b);
            doc.line_width(0.5);
            doc.line(x0, y - height, x0 + table_w, y - height);
        } else {
            let (r, g, b) = hex(0xcccccc);
            doc.stroke_rgb(r, g, b);
            doc.line_width(0.3);
            let mut x = x0;
            for width in widths {
                doc.stroke_rect(x, y - height, *width, height);
                x += width;
            }
        }
        y -= height;
    }

    // Cell text, top-aligned.
    let mut y = top;
    for &index in indices {
        let (font, gray) = if index == 0 { (Font::HelveticaBold, 1.0) } else { (Font::Helvetica, 0.0) };
        doc.fill_rgb(gray, gray, gray);
        let mut x = x0;
        for (cell, width) in rows[index].cells.iter().zip(widths) {
            for (line_no, line) in cell.iter().enumerate() {
                // reportlab puts a paragraph's first baseline one font size below its top.
                let baseline = y - PAD_TOP - CELL_SIZE - line_no as f64 * CELL_LEADING;
                doc.text(font, CELL_SIZE, x + PAD_SIDE, baseline, line);
            }
            x += width;
        }
        y -= rows[index].height;
    }
}

/// `rows` are `(name, details, quantity, location)`.
pub fn make_list_pdf(title: &str, rows: &[(String, String, i64, String)]) -> Vec<u8> {
    let available_w = PAGE_W - 2.0 * MARGIN;
    let widths: [f64; 4] = COL_FRACTIONS.map(|fraction| available_w * fraction);
    let inner_x = MARGIN + FRAME_PAD;
    let inner_w = available_w - 2.0 * FRAME_PAD;
    let frame_top = PAGE_H - MARGIN - FRAME_PAD;
    let frame_bottom = MARGIN + FRAME_PAD;
    // The table is wider than the frame's inner width; centered, it overhangs both sides.
    let table_x = inner_x + (inner_w - widths.iter().sum::<f64>()) / 2.0;

    let mut table = vec![layout_row(HEADERS.map(str::to_owned), Font::HelveticaBold, &widths)];
    table.extend(rows.iter().map(|(name, details, quantity, location)| {
        layout_row([name.clone(), details.clone(), quantity.to_string(), location.clone()], Font::Helvetica, &widths)
    }));

    let mut doc = Document::new();

    // Title, centered, Helvetica-Bold 18 on a 22pt leading; for one line reportlab drew it
    // at (48.519 + 206.6028, 793.3708 - 18): the frame's inner top-left, centered.
    let mut y = frame_top;
    doc.fill_rgb(0.0, 0.0, 0.0);
    for line in word_wrap(title, Font::HelveticaBold, TITLE_SIZE, inner_w) {
        let x = inner_x + (inner_w - string_width(&line, Font::HelveticaBold, TITLE_SIZE)) / 2.0;
        doc.text(Font::HelveticaBold, TITLE_SIZE, x, y - TITLE_SIZE, &line);
        y -= TITLE_LEADING;
    }
    y -= TITLE_SPACE_AFTER + SPACER;

    // The table, split between rows, the header repeated on each part. A part must hold
    // at least one data row, or the whole rest moves to the next page.
    let mut next = 1;
    loop {
        let available = y - frame_bottom;
        let mut used = table[0].height;
        let mut end = next;
        while end < table.len() && used + table[end].height <= available + FUZZ {
            used += table[end].height;
            end += 1;
        }
        let whole_table_left = next == 1 && end == table.len();
        if end > next || whole_table_left {
            let indices: Vec<usize> = std::iter::once(0).chain(next..end).collect();
            draw_rows(&mut doc, &table, &indices, &widths, table_x, y);
            next = end;
        }
        if next >= table.len() {
            break;
        }
        doc.new_page();
        y = frame_top;
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

    fn short(n: usize) -> Vec<(String, String, i64, String)> {
        (0..n).map(|i| (format!("Item {i}"), "x".to_owned(), 1, "Cave".to_owned())).collect()
    }

    fn long(n: usize) -> Vec<(String, String, i64, String)> {
        let row = (
            "Space Marines Tactical Squad with plasma gun and heavy bolter painted".to_owned(),
            "Bolt Action · 28mm · Western front".to_owned(),
            12,
            "Grenier – Étagère du fond, carton bleu".to_owned(),
        );
        vec![row; n]
    }

    // Page counts measured with reportlab and the Flask app's make_list_pdf.
    #[test]
    fn breaks_pages_where_reportlab_did() {
        assert_eq!(pages(&make_list_pdf("Inventaire", &[])), 1);
        assert_eq!(pages(&make_list_pdf("Inventaire", &short(42))), 1);
        assert_eq!(pages(&make_list_pdf("Inventaire", &short(43))), 2);
        assert_eq!(pages(&make_list_pdf("Inventaire", &short(87))), 2);
        assert_eq!(pages(&make_list_pdf("Inventaire", &short(88))), 3);
        assert_eq!(pages(&make_list_pdf("Inventaire", &short(150))), 4);
        assert_eq!(pages(&make_list_pdf("Inventaire", &long(26))), 1);
        assert_eq!(pages(&make_list_pdf("Inventaire", &long(27))), 2);
        assert_eq!(pages(&make_list_pdf("Inventaire", &long(54))), 2);
        assert_eq!(pages(&make_list_pdf("Inventaire", &long(55))), 3);
        let title = "A very long category title that will certainly need to wrap onto a second line in eighteen \
                     point bold";
        assert_eq!(pages(&make_list_pdf(title, &short(41))), 1);
    }
}
