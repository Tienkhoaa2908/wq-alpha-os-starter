from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import fitz  # PyMuPDF
except ImportError as e:
    raise SystemExit("Missing PyMuPDF. Run: python -m pip install PyMuPDF") from e

DB_PATH = Path("data/db/wq_alpha_os.sqlite")
PDF_DEFAULT = Path("exports_raw/operators/WorldQuant BRAIN1.pdf")

CATEGORIES = {
    "Arithmetic", "Logical", "Time Series", "Cross Sectional",
    "Vector", "Transformational", "Group"
}

# A conservative signature detector for WorldQuant operator docs.
SIG_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*\(.*")
COMPARE_SIGS = {"input1 < input2", "input1 <= input2", "input1 == input2", "input1 > input2", "input1 >= input2", "input1!= input2"}


@dataclass
class OperatorBlock:
    operator_name: str
    signature: str
    category: str
    level: str
    description: str
    raw_text: str
    source_file: str


def pdf_to_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    parts = []
    for i, page in enumerate(doc, start=1):
        parts.append(f"\n--- PAGE {i} ---\n")
        parts.append(page.get_text("text"))
    return "\n".join(parts)


def clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("\u00a0", " ")).strip()


def normalize_signature_lines(lines: list[str], start: int) -> tuple[str, int]:
    """Merge wrapped operator signatures until the line before 'base'."""
    sig_parts = []
    i = start
    while i < len(lines):
        ln = clean_line(lines[i])
        if not ln:
            i += 1
            continue
        if ln.lower() == "base":
            break
        # Stop if we hit a section header unexpectedly.
        if ln in CATEGORIES and sig_parts:
            break
        sig_parts.append(ln)
        # Most signatures are within 1-3 lines before base; cap to avoid swallowing descriptions.
        if len(sig_parts) >= 4:
            break
        i += 1
    return " ".join(sig_parts), i


def operator_name_from_signature(signature: str) -> str:
    s = signature.strip()
    if s in COMPARE_SIGS:
        return s
    m = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)", s)
    return m.group(1) if m else s[:80]


def is_signature_candidate(lines: list[str], i: int) -> bool:
    ln = clean_line(lines[i])
    if not ln or ln in CATEGORIES:
        return False
    if ln in COMPARE_SIGS:
        return True
    if SIG_RE.match(ln):
        # Look ahead for 'base' within next 4 lines.
        for j in range(i + 1, min(i + 5, len(lines))):
            if clean_line(lines[j]).lower() == "base":
                return True
    return False


def parse_operator_blocks(text: str, source_file: str) -> list[OperatorBlock]:
    lines = [clean_line(x) for x in text.splitlines()]
    blocks: list[OperatorBlock] = []
    current_category = "Unknown"
    i = 0

    while i < len(lines):
        line = lines[i]
        if line in CATEGORIES:
            current_category = line
            i += 1
            continue

        if not is_signature_candidate(lines, i):
            i += 1
            continue

        signature, base_idx = normalize_signature_lines(lines, i)
        level = ""
        if base_idx < len(lines) and clean_line(lines[base_idx]).lower() == "base":
            level = "base"
            desc_start = base_idx + 1
        else:
            desc_start = i + 1

        # Description continues until next operator signature or category.
        desc_lines = []
        j = desc_start
        while j < len(lines):
            if lines[j] in CATEGORIES:
                break
            if is_signature_candidate(lines, j):
                break
            # Remove repeated site nav noise.
            if lines[j] and not lines[j].startswith("https://platform.worldquantbrain.com"):
                desc_lines.append(lines[j])
            j += 1

        raw_text = "\n".join([signature, level] + desc_lines).strip()
        description = " ".join([x for x in desc_lines if x and x.lower() not in {"show less", "show more"}])[:3000]
        blocks.append(OperatorBlock(
            operator_name=operator_name_from_signature(signature),
            signature=signature,
            category=current_category,
            level=level,
            description=description,
            raw_text=raw_text,
            source_file=source_file,
        ))
        i = max(j, i + 1)

    # Deduplicate by operator + signature, keep longest description.
    best: dict[tuple[str, str], OperatorBlock] = {}
    for b in blocks:
        key = (b.operator_name, b.signature)
        if key not in best or len(b.raw_text) > len(best[key].raw_text):
            best[key] = b
    return list(best.values())


def ensure_operator_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS operators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operator_name TEXT,
        category TEXT,
        level TEXT,
        signature TEXT,
        description TEXT,
        use_case TEXT,
        expected_effect TEXT,
        source_file TEXT,
        raw_text TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(operator_name, signature)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS operator_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operator_name TEXT,
        category TEXT,
        chunk_text TEXT,
        source_file TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()


def ingest_operators(pdf_path: Path = PDF_DEFAULT, db_path: Path = DB_PATH) -> int:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}. Run python -m src.ingest_raw first.")

    text = pdf_to_text(pdf_path)
    blocks = parse_operator_blocks(text, str(pdf_path))

    conn = sqlite3.connect(db_path)
    ensure_operator_tables(conn)
    conn.execute("DELETE FROM operator_chunks WHERE source_file = ?", (str(pdf_path),))

    inserted = 0
    for b in blocks:
        conn.execute("""
        INSERT INTO operators (
            operator_name, category, level, signature, description,
            use_case, expected_effect, source_file, raw_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(operator_name, signature) DO UPDATE SET
            category=excluded.category,
            level=excluded.level,
            description=excluded.description,
            source_file=excluded.source_file,
            raw_text=excluded.raw_text
        """, (
            b.operator_name, b.category, b.level, b.signature, b.description,
            "", "", b.source_file, b.raw_text
        ))
        conn.execute("""
        INSERT INTO operator_chunks (operator_name, category, chunk_text, source_file)
        VALUES (?, ?, ?, ?)
        """, (b.operator_name, b.category, b.raw_text, b.source_file))
        inserted += 1
    conn.commit()
    conn.close()
    print(f"Ingested {inserted} operators from {pdf_path}")
    return inserted


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("pdf", nargs="?", default=str(PDF_DEFAULT))
    p.add_argument("--db", default=str(DB_PATH))
    args = p.parse_args()
    ingest_operators(Path(args.pdf), Path(args.db))
