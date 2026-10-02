//! Item photos on disk: `UPLOADS_DIR/<category_snake>/<item id>/<uuid>_<name>`.

use std::path::{Path, PathBuf};

use unicode_normalization::UnicodeNormalization as _;

/// Python's `str.split()` whitespace, as far as ASCII goes (it includes the
/// \x1c-\x1f separators, which Rust's `char::is_whitespace` does not).
fn is_python_space(c: char) -> bool {
    matches!(c, ' ' | '\t' | '\n' | '\x0b' | '\x0c' | '\r' | '\x1c'..='\x1f')
}

/// werkzeug's `secure_filename`, as it behaves on Linux: ASCII only, whitespace runs to
/// `_`, path separators removed, no leading or trailing `.`/`_`. May return an empty
/// string (the uuid prefix keeps the stored name unique anyway).
pub fn secure_filename(filename: &str) -> String {
    let ascii: String = filename.nfkd().filter(char::is_ascii).collect();
    let spaced = ascii.replace('/', " ");
    let joined = spaced.split(is_python_space).filter(|part| !part.is_empty()).collect::<Vec<_>>().join("_");
    let kept: String = joined.chars().filter(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '-')).collect();
    kept.trim_matches(|c| c == '.' || c == '_').to_owned()
}

/// The stored name of an upload: `<uuid4>_<secure name>`.
pub fn stored_name(original: &str) -> String {
    format!("{}_{}", uuid::Uuid::new_v4(), secure_filename(original))
}

pub fn item_dir(uploads_dir: &Path, category_snake: &str, item_id: i64) -> PathBuf {
    uploads_dir.join(category_snake).join(item_id.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn like_werkzeug() {
        // The examples of werkzeug's docstring, then a few more checked against it.
        assert_eq!(secure_filename("My cool movie.mov"), "My_cool_movie.mov");
        assert_eq!(secure_filename("../../../etc/passwd"), "etc_passwd");
        assert_eq!(secure_filename("i contain cool \u{fc}ml\u{e4}uts.txt"), "i_contain_cool_umlauts.txt");
        assert_eq!(secure_filename("Photo été 2024 (1).JPG"), "Photo_ete_2024_1.JPG");
        assert_eq!(secure_filename("..."), "");
        assert_eq!(secure_filename("a\u{1c}b\tc"), "a_b_c");
        assert_eq!(secure_filename("ﬁle.png"), "file.png"); // NFKD splits the ligature
    }

    #[test]
    fn stored_names_are_unique() {
        let a = stored_name("x.png");
        assert!(a.ends_with("_x.png") && a.len() == 36 + "_x.png".len());
        assert_ne!(a, stored_name("x.png"));
    }
}
