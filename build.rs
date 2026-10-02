//! Builds the templates into the binary (the image ships one file): writes
//! `$OUT_DIR/templates.rs`, a `TEMPLATES` list of `(name, source)` pairs that
//! `src/templates.rs` loads at startup — returning an error for a broken template rather
//! than panicking, as minijinja-embed's loader would.

use std::fmt::Write as _;
use std::path::{Path, PathBuf};

fn collect(dir: &Path, root: &Path, out: &mut Vec<(String, PathBuf)>) -> std::io::Result<()> {
    for entry in std::fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect(&path, root, out)?;
        } else if path.extension().is_some_and(|ext| ext == "html") {
            let name = path.strip_prefix(root).unwrap_or(&path).to_string_lossy().replace('\\', "/");
            out.push((name, path.canonicalize()?));
        }
    }
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = Path::new("templates");
    println!("cargo:rerun-if-changed=templates");
    let mut templates = Vec::new();
    collect(root, root, &mut templates)?;
    templates.sort();

    let mut code = String::from("pub static TEMPLATES: &[(&str, &str)] = &[\n");
    for (name, path) in &templates {
        writeln!(code, "    ({name:?}, include_str!({:?})),", path.to_string_lossy())?;
    }
    code.push_str("];\n");
    let out = PathBuf::from(std::env::var("OUT_DIR")?).join("templates.rs");
    std::fs::write(out, code)?;
    Ok(())
}
