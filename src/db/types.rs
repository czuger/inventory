//! Column encodings that must match, byte for byte, what SQLAlchemy wrote: the rows the
//! Python app left behind and the ones written here sort and compare together.

use chrono::{NaiveDateTime, Utc};

/// SQLAlchemy's SQLite `DateTime`: naive UTC as `YYYY-MM-DD HH:MM:SS.ffffff`, always six
/// fractional digits. Borrowing history is ordered by this text, so a row written with a
/// shorter fraction (sqlx's own chrono encoding) would sort wrongly against the others.
const FORMAT: &str = "%Y-%m-%d %H:%M:%S%.6f";

/// `utcnow()` from `inventory/db/base.py`, ready to store.
pub fn utcnow_text() -> String {
    format_datetime(&Utc::now().naive_utc())
}

pub fn format_datetime(datetime: &NaiveDateTime) -> String {
    datetime.format(FORMAT).to_string()
}

/// Reads what SQLAlchemy wrote (with or without the fraction).
pub fn parse_datetime(text: &str) -> Option<NaiveDateTime> {
    NaiveDateTime::parse_from_str(text, "%Y-%m-%d %H:%M:%S%.f")
        .or_else(|_| NaiveDateTime::parse_from_str(text, "%Y-%m-%d %H:%M:%S"))
        .ok()
}

/// SQLAlchemy's `JSON` column for `images`: `json.dumps(list)`, i.e. `["a", "b"]` with
/// `", "` between items and non-ASCII escaped.
pub fn images_to_json(images: &[String]) -> String {
    let items: Vec<String> = images.iter().map(|image| python_json_string(image)).collect();
    format!("[{}]", items.join(", "))
}

pub fn images_from_json(json: &str) -> Result<Vec<String>, serde_json::Error> {
    serde_json::from_str(json)
}

/// A JSON string literal as Python's `json.dumps` writes it (`ensure_ascii=True`).
fn python_json_string(value: &str) -> String {
    let json = serde_json::Value::String(value.to_owned()).to_string();
    let mut out = String::with_capacity(json.len());
    for c in json.chars() {
        if c.is_ascii() {
            out.push(c);
        } else {
            let mut units = [0u16; 2];
            for unit in c.encode_utf16(&mut units) {
                out.push_str(&format!("\\u{unit:04x}"));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn datetimes_like_sqlalchemy() {
        let dt = parse_datetime("2026-10-01 14:03:07.000120").unwrap();
        assert_eq!(format_datetime(&dt), "2026-10-01 14:03:07.000120");
        let whole = parse_datetime("2024-12-06 09:00:00").unwrap();
        assert_eq!(format_datetime(&whole), "2024-12-06 09:00:00.000000");
        assert_eq!(utcnow_text().len(), "2026-10-01 14:03:07.000120".len());
        assert!(parse_datetime("yesterday").is_none());
    }

    #[test]
    fn images_like_json_dumps() {
        // json.dumps(['a.png', 'b c.jpg', 'été.png'])
        let images = vec!["a.png".to_owned(), "b c.jpg".to_owned(), "été.png".to_owned()];
        assert_eq!(images_to_json(&images), "[\"a.png\", \"b c.jpg\", \"\\u00e9t\\u00e9.png\"]");
        assert_eq!(images_to_json(&[]), "[]");
        assert_eq!(images_from_json(&images_to_json(&images)).unwrap(), images);
    }
}
