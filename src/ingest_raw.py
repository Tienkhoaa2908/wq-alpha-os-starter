from pathlib import Path
from sqlalchemy import select
from src.schema import make_session, Field, Dataset
from src.parsers import (
    ExportedPage,
    detect_page_type,
    parse_fields_from_text,
    parse_datasets_from_text,
    parse_paginated_raw_fields,
)
from src.classify_fields import classify_field


def upsert_field(session, row: dict):
    existing = session.execute(
        select(Field).where(
            Field.field_name == row["field_name"],
            Field.dataset_name == row.get("dataset_name"),
            Field.category == row.get("category")
        )
    ).scalar_one_or_none()
    classification = classify_field(
        row.get("field_name", ""),
        row.get("description", ""),
        row.get("category"),
        row.get("field_type", "")
    )
    payload = {**row, **classification}
    if existing:
        for k, v in payload.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
    else:
        session.add(Field(**payload))


def upsert_dataset(session, row: dict):
    existing = session.execute(
        select(Dataset).where(
            Dataset.dataset_name == row["dataset_name"],
            Dataset.category == row.get("category"),
            Dataset.region == row.get("region"),
            Dataset.delay == row.get("delay"),
            Dataset.universe == row.get("universe")
        )
    ).scalar_one_or_none()
    if existing:
        for k, v in row.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
    else:
        session.add(Dataset(**row))


def ingest_file(path: str | Path):
    page = ExportedPage.from_json(path)
    page_type = detect_page_type(page)

    Session = make_session()

    with Session() as session:
        if page_type == "fields":
            rows = parse_fields_from_text(page)

            if not rows:
                rows = parse_paginated_raw_fields(page)

            for row in rows:
                upsert_field(session, row)

            session.commit()
            print(f"[fields] {path}: {len(rows)} rows")

        elif page_type == "datasets":
            rows = parse_datasets_from_text(page)

            for row in rows:
                upsert_dataset(session, row)

            session.commit()
            print(f"[datasets] {path}: {len(rows)} rows")

        else:
            rows = parse_paginated_raw_fields(page)

            if rows:
                for row in rows:
                    upsert_field(session, row)

                session.commit()
                print(f"[paginated fields] {path}: {len(rows)} rows")
            else:
                print(f"[skip] {path}: detected page type = {page_type}")


def ingest_folder(folder: str = "exports_raw"):
    paths = list(Path(folder).rglob("*.json"))
    if not paths:
        print(f"No .json files found in {folder}")
        return
    for path in paths:
        ingest_file(path)


if __name__ == "__main__":
    ingest_folder()
