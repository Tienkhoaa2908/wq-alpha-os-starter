import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def parse_percent(x: str | None) -> float | None:
    if not x:
        return None
    x = x.replace("%", "").replace(",", ".").strip()
    try:
        return float(x)
    except ValueError:
        return None


def parse_int(x: str | None) -> int | None:
    if not x:
        return None
    x = re.sub(r"[^\d-]", "", x)
    try:
        return int(x)
    except ValueError:
        return None


@dataclass
class ExportedPage:
    path: Path
    url: str
    title: str
    text: str
    tables: list[list[list[str]]]

    @classmethod
    def from_json(cls, path: str | Path) -> "ExportedPage":
        path = Path(path)
        obj = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            url=obj.get("url", ""),
            title=obj.get("title", ""),
            text=obj.get("visible_text", ""),
            tables=obj.get("tables", []),
        )


def detect_page_type(page: ExportedPage) -> str:
    t = page.text.lower()
    if "operators" in t and "operator" in t and "description" in t and "show less" in t:
        return "operators"
    if "data > datasets >" in t and "field" in t and "date coverage" in t:
        return "fields"
    if "data > datasets" in t and "dataset" in t and "value score" in t:
        return "datasets"
    if "is summary" in t and "sharpe" in t and "fitness" in t:
        return "simulation"
    if "categories" in t and "value score" in t and "datasets" in t:
        return "categories"
    return "unknown"


def infer_category_from_dataset(dataset_name: str | None) -> str | None:
    if not dataset_name:
        return None

    low = dataset_name.lower()

    if "price volume" in low or "relationship" in low or "universe" in low:
        return "Price Volume"

    if "fundamental" in low or "footnote" in low or "company fundamental" in low:
        return "Fundamental"

    if "model" in low or "risk metric" in low or "fundamental scores" in low:
        return "Model"

    if "analyst" in low:
        return "Analyst"

    if "news" in low:
        return "News"

    if "sentiment" in low:
        return "Sentiment"

    if "social" in low:
        return "Social Media"

    if "option" in low:
        return "Option"

    return None


def _get_dataset_name(lines: list[str]) -> str | None:
    for line in lines:
        if "Data > Datasets >" in line:
            parts = [p.strip() for p in line.split(">")]
            if len(parts) >= 3:
                return parts[-1]
    return None


def parse_fields_from_text(page: ExportedPage) -> list[dict[str, Any]]:
    lines = [x.strip() for x in page.text.splitlines() if x.strip()]
    dataset_name = _get_dataset_name(lines)
    category = infer_category_from_dataset(dataset_name)

    # Find header sequence: Field Description Type Coverage Date Coverage Alphas Date added
    start = None
    for i in range(len(lines) - 6):
        if [x.lower() for x in lines[i:i+7]] == [
            "field", "description", "type", "coverage", "date coverage", "alphas", "date added"
        ]:
            start = i + 7
            break
    if start is None:
        return []

    rows = []
    i = start
    while i + 6 < len(lines):
        if lines[i].lower() in {"page size", "prev", "next"}:
            break
        field_name, description, field_type = lines[i], lines[i+1], lines[i+2]
        coverage, date_coverage, alphas, date_added = lines[i+3], lines[i+4], lines[i+5], lines[i+6]
        if field_type not in {"Matrix", "Group", "Vector", "Symbol"}:
            i += 1
            continue
        rows.append({
            "field_name": field_name,
            "description": description,
            "field_type": field_type,
            "coverage": parse_percent(coverage),
            "date_coverage": parse_percent(date_coverage),
            "alphas_count": parse_int(alphas),
            "date_added": date_added,
            "dataset_name": dataset_name,
            "category": category,
            "source_file": str(page.path),
        })
        i += 7
    return rows


def parse_datasets_from_text(page: ExportedPage) -> list[dict[str, Any]]:
    """
    Parser chắc hơn cho trang Data > Datasets.
    Đọc theo pattern:
    Dataset
    Fields
    Coverage
    Date Coverage
    Value Score
    Alphas
    Last field added
    Resources

    Sau đó lấy từng row có dạng:
    dataset_name
    fields_count
    coverage
    date_coverage
    value_score
    alphas_count
    last_field_added
    """
    lines = [x.strip() for x in page.text.splitlines() if x.strip()]

    # Lấy category filter nếu có
    category = None
    for i, line in enumerate(lines):
        if line == "Category" and i + 1 < len(lines):
            category = lines[i + 1].replace("×", "").strip()
            break

    # Tìm header bảng dataset
    header_start = None
    for i in range(len(lines) - 7):
        if (
            lines[i] == "Dataset"
            and lines[i + 1] == "Fields"
            and lines[i + 2] == "Coverage"
            and lines[i + 3] == "Date Coverage"
            and lines[i + 4] == "Value Score"
            and lines[i + 5] == "Alphas"
            and lines[i + 6] == "Last field added"
        ):
            header_start = i
            break

    if header_start is None:
        return []

    rows = []
    i = header_start + 8  # bỏ qua cả Resources

    while i < len(lines):
        if lines[i].lower() in {"page size", "prev", "next"}:
            break

        if i + 6 >= len(lines):
            break

        dataset_name = lines[i]
        fields_count_raw = lines[i + 1]
        coverage_raw = lines[i + 2]
        date_coverage_raw = lines[i + 3]
        value_score_raw = lines[i + 4]
        alphas_raw = lines[i + 5]
        last_field_added = lines[i + 6]

        # Kiểm tra row hợp lệ
        fields_count = parse_int(fields_count_raw)
        coverage = parse_percent(coverage_raw)
        date_coverage = parse_percent(date_coverage_raw)
        value_score = parse_int(value_score_raw)
        alphas_count = parse_int(alphas_raw)

        if (
            dataset_name.lower() in {"resources", "page size", "prev", "next"}
            or fields_count is None
            or coverage is None
            or date_coverage is None
            or value_score is None
            or alphas_count is None
        ):
            i += 1
            continue

        rows.append({
            "category": category,
            "dataset_name": dataset_name,
            "fields_count": fields_count,
            "coverage": coverage,
            "date_coverage": date_coverage,
            "value_score": value_score,
            "alphas_count": alphas_count,
            "last_field_added": last_field_added,
            "region": "USA" if "Region\nUSA" in page.text else None,
            "delay": 1 if "Delay\n1" in page.text else None,
            "universe": "TOP3000" if "Universe\nTOP3000" in page.text else None,
            "source_file": str(page.path),
        })

        i += 7

        # Bỏ qua resource links như [1], [2] nếu có
        while i < len(lines) and re.fullmatch(r"\[\d+\],?", lines[i]):
            i += 1

    return rows

def parse_paginated_raw_fields(page: ExportedPage) -> list[dict]:
    """
    Parser cho file JSON được tạo bởi paginated raw-text exporter.
    Nó đọc payload.pages[*].text rồi parse các dòng field.
    """
    import json

    obj = json.loads(page.path.read_text(encoding="utf-8"))

    if obj.get("export_type") != "wq_paginated_raw_text":
        return []

    all_rows = []

    for p in obj.get("pages", []):
        text = p.get("text", "")
        fake_page = ExportedPage(
            path=page.path,
            url=obj.get("url", ""),
            title=obj.get("title", ""),
            text=text,
            tables=[]
        )

        rows = parse_fields_from_text(fake_page)
        all_rows.extend(rows)

    # remove duplicates
    seen = set()
    unique_rows = []

    for row in all_rows:
        key = (
            row.get("field_name"),
            row.get("dataset_name"),
            row.get("category")
        )

        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    return unique_rows