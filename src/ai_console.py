
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

from src.ingest_operators_pdf import ingest_operators
from src.ai_alpha_engine import generate_ai_alphas, get_context

DB_PATH = Path("data/db/wq_alpha_os.sqlite")
ENGINE = create_engine(f"sqlite:///{DB_PATH}", future=True)

st.set_page_config(page_title="WQ AI Console - Gemini", layout="wide")
st.title("WQ Alpha OS — Gemini Research Console")


def read_sql(q: str, params=None):
    with ENGINE.connect() as conn:
        return pd.read_sql(text(q), conn, params=params or {})


def exec_sql(q: str, params=None):
    with ENGINE.begin() as conn:
        conn.execute(text(q), params or {})


def parse_id_list(s: str) -> list[int]:
    ids: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.strip().isdigit() and b.strip().isdigit():
                ids.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            ids.append(int(part))
    return sorted(set(ids))


tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "1. Operators",
    "2. Gemini Generate",
    "3. Candidates",
    "4. Context Debug",
    "5. Experiment Notes",
])

with tab0:
    st.subheader("Ingest operator PDF")
    st.write("Copy `WorldQuant BRAIN1.pdf` vào `exports_raw/operators/`, rồi chạy ingest tại đây.")
    pdf_path = st.text_input("PDF path", "exports_raw/operators/WorldQuant BRAIN1.pdf")
    if st.button("Ingest operators PDF"):
        try:
            n = ingest_operators(Path(pdf_path), DB_PATH)
            st.success(f"Ingested {n} operators")
        except Exception as e:
            st.error(str(e))

    try:
        ops = read_sql("""
            SELECT category, operator_name, signature, substr(description,1,250) AS description
            FROM operators
            ORDER BY category, operator_name
        """)
        st.dataframe(ops, use_container_width=True)
    except Exception as e:
        st.warning(f"Operators table not ready: {e}")

with tab1:
    st.subheader("Gemini generate alpha families")
    st.write("Gemini đọc fields + operators + experiment history, nhưng đã bị ép sinh alpha theo family/economic logic.")

    model = st.text_input("Gemini model", "gemini-2.5-flash")
    n = st.number_input("Number of candidates", min_value=1, max_value=20, value=5)
    c1, c2, c3 = st.columns(3)
    with c1:
        max_fields = st.number_input("Max fields sent", min_value=20, max_value=300, value=80)
    with c2:
        max_ops = st.number_input("Max operators sent", min_value=10, max_value=120, value=60)
    with c3:
        max_exps = st.number_input("Max experiments sent", min_value=0, max_value=100, value=30)

    default_extra = """Prioritize robust multi-component Model/Fundamental alphas.
Do not generate one-field one-function alphas.
Every alpha must combine at least two economic components, such as analyst revision + value, value + quality, or quality + liquidity filter.
Avoid pure price-volume.
Avoid rank(field1 + field2) and rank(field1 * field2).
Weak years 2019, 2020, and 2023 matter; prefer slow fundamental/value/quality confirmation to reduce regime fragility.
For direction-ambiguous model fields, include reverse or explain direction."""
    extra = st.text_area("Extra instruction", default_extra, height=180)

    if st.button("Generate with Gemini"):
        with st.spinner("Calling Gemini API..."):
            try:
                result = generate_ai_alphas(
                    n=int(n),
                    model=model,
                    extra_instruction=extra,
                    max_fields=int(max_fields),
                    max_ops=int(max_ops),
                    max_exps=int(max_exps),
                )
                st.success(f"Gemini candidates generated. Inserted: {result.get('_inserted', 0)}")
                st.json(result)
            except Exception as e:
                st.error(str(e))

with tab2:
    st.subheader("Candidates")
    status_options = [
        "ai_generated_gemini",
        "direction_scout",
        "research_family",
        "new",
        "test_next",
        "tested",
        "bad",
        "passed",
        "archived",
    ]

    status = st.multiselect("Status", status_options, default=["ai_generated_gemini", "direction_scout", "research_family"])
    keyword = st.text_input("Keyword filter", "")

    where_parts = []
    params = {}

    if status:
        placeholders = ",".join([f":s{i}" for i in range(len(status))])
        where_parts.append(f"status IN ({placeholders})")
        params.update({f"s{i}": s for i, s in enumerate(status)})

    if keyword.strip():
        where_parts.append("(expression LIKE :kw OR fields_used LIKE :kw OR family LIKE :kw OR hypothesis LIKE :kw)")
        params["kw"] = f"%{keyword.strip()}%"

    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    df = read_sql(f"""
        SELECT id, status, family, expression, fields_used, operators_used,
               expected_turnover, expected_risk, hypothesis
        FROM alpha_candidates
        {where}
        ORDER BY id DESC
    """, params)

    st.dataframe(df, use_container_width=True)
    st.download_button(
        "Download candidates CSV",
        df.to_csv(index=False).encode("utf-8-sig"),
        "gemini_candidates.csv",
        "text/csv",
    )

    st.subheader("Update / delete")
    ids = st.text_input("IDs, comma or range, e.g. 1,2,10-15", "")
    new_status = st.selectbox("New status", ["test_next", "tested", "bad", "passed", "archived"])
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Update selected status") and ids.strip():
            id_list = parse_id_list(ids)
            for i in id_list:
                exec_sql("UPDATE alpha_candidates SET status=:status WHERE id=:id", {"status": new_status, "id": i})
            st.success(f"Updated {len(id_list)} candidates")
    with col_b:
        if st.button("Delete selected") and ids.strip():
            id_list = parse_id_list(ids)
            for i in id_list:
                exec_sql("DELETE FROM alpha_candidates WHERE id=:id", {"id": i})
            st.success(f"Deleted {len(id_list)} candidates")

with tab3:
    st.subheader("Context sent to Gemini")
    max_fields_dbg = st.slider("Fields", 20, 300, 80)
    max_ops_dbg = st.slider("Operators", 10, 120, 60)
    max_exp_dbg = st.slider("Experiments", 0, 100, 30)
    ctx = get_context(max_fields=max_fields_dbg, max_ops=max_ops_dbg, max_exps=max_exp_dbg)
    st.json(ctx)

with tab4:
    st.subheader("Manual experiment logging reminder")
    st.write("""
Use the main dashboard `src/app.py` to save experiment metrics.
Important: store both TRAIN and TEST notes when possible.
For WQ metrics, enter displayed values directly:
- Turnover 1.73% -> 1.73
- Margin 11.96‰ -> 11.96
""")

    try:
        exps = read_sql("""
            SELECT id, alpha_expression, sharpe, fitness, turnover, returns, drawdown, margin, fail_reasons, created_at
            FROM experiments
            ORDER BY created_at DESC
            LIMIT 50
        """)
        st.dataframe(exps, use_container_width=True)
    except Exception as e:
        st.warning(f"Experiments table not ready: {e}")
