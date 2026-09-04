from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text
from src.schema import make_engine

engine = make_engine()

st.set_page_config(page_title="WQ Alpha OS Control", layout="wide")
st.title("WorldQuant Alpha Research OS — Control Panel")


def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


def exec_sql(query: str, params: dict | None = None):
    with engine.begin() as conn:
        conn.execute(text(query), params or {})


def table_count(table: str) -> int:
    try:
        return int(read_sql(f"SELECT COUNT(*) AS n FROM {table}")["n"].iloc[0])
    except Exception:
        return 0


# ---------------- Sidebar summary ----------------
st.sidebar.header("Database")
for t in ["datasets", "fields", "alpha_candidates", "experiments"]:
    st.sidebar.metric(t, table_count(t))

page = st.sidebar.radio(
    "Page",
    ["Alpha Candidates", "Fields", "Datasets", "Experiments", "DB Admin", "SQL"],
)


# ---------------- Alpha Candidates ----------------
if page == "Alpha Candidates":
    st.header("Alpha Candidates")

    families = read_sql("SELECT DISTINCT family FROM alpha_candidates ORDER BY family")
    family_opts = families["family"].dropna().tolist() if not families.empty else []
    chosen_family = st.multiselect("Family", family_opts)

    status_df = read_sql("SELECT DISTINCT status FROM alpha_candidates ORDER BY status")
    status_opts = status_df["status"].dropna().tolist() if not status_df.empty else []
    chosen_status = st.multiselect("Status", status_opts, default=status_opts if status_opts else [])

    keyword = st.text_input("Search expression / field", "")

    query = """
        SELECT id, family, expression, fields_used, operators_used,
               hypothesis, expected_turnover, expected_risk, status, created_at
        FROM alpha_candidates
        WHERE 1=1
    """
    params = {}

    if chosen_family:
        query += " AND family IN :families"
        params["families"] = tuple(chosen_family)

    if chosen_status:
        query += " AND status IN :statuses"
        params["statuses"] = tuple(chosen_status)

    if keyword.strip():
        query += " AND (expression LIKE :kw OR fields_used LIKE :kw OR hypothesis LIKE :kw)"
        params["kw"] = f"%{keyword.strip()}%"

    query += " ORDER BY id ASC"

    try:
        df = read_sql(query, params)
    except Exception:
        # SQLite/sqlalchemy tuple binding fallback
        df = read_sql("""
            SELECT id, family, expression, fields_used, operators_used,
                   hypothesis, expected_turnover, expected_risk, status, created_at
            FROM alpha_candidates
            ORDER BY id ASC
        """)
        if chosen_family:
            df = df[df["family"].isin(chosen_family)]
        if chosen_status:
            df = df[df["status"].isin(chosen_status)]
        if keyword.strip():
            k = keyword.strip().lower()
            df = df[df.apply(lambda r: k in str(r.to_dict()).lower(), axis=1)]

    st.caption(f"Showing {len(df)} candidates")
    st.dataframe(df, use_container_width=True, height=520)

    st.subheader("Actions")
    col1, col2, col3 = st.columns(3)

    with col1:
        ids_text = st.text_area("Candidate IDs", placeholder="Example: 1,2,3 or 10-20")

    def parse_ids(s: str) -> list[int]:
        ids: set[int] = set()
        for part in s.replace("\n", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                if a.strip().isdigit() and b.strip().isdigit():
                    ids.update(range(int(a), int(b) + 1))
            elif part.isdigit():
                ids.add(int(part))
        return sorted(ids)

    ids = parse_ids(ids_text)

    with col2:
        new_status = st.selectbox("Set status", ["new", "watch", "test_next", "tested", "bad", "passed", "archived"])
        if st.button("Update status", type="primary", disabled=not ids):
            with engine.begin() as conn:
                for i in ids:
                    conn.execute(text("UPDATE alpha_candidates SET status=:s WHERE id=:id"), {"s": new_status, "id": i})
            st.success(f"Updated {len(ids)} candidates to status={new_status}")
            st.rerun()

    with col3:
        if st.button("Delete selected", disabled=not ids):
            with engine.begin() as conn:
                for i in ids:
                    conn.execute(text("DELETE FROM alpha_candidates WHERE id=:id"), {"id": i})
            st.warning(f"Deleted {len(ids)} candidates")
            st.rerun()

    if ids:
        selected = df[df["id"].isin(ids)]
        if not selected.empty:
            st.subheader("Selected expressions")
            expr_text = "\n\n".join(selected["expression"].astype(str).tolist())
            st.code(expr_text, language="text")
            st.download_button(
                "Download selected candidates CSV",
                selected.to_csv(index=False).encode("utf-8-sig"),
                "selected_alpha_candidates.csv",
                "text/csv",
            )


# ---------------- Fields ----------------
elif page == "Fields":
    st.header("Fields")
    df = read_sql("""
        SELECT id, category, dataset_name, field_name, description, field_type,
               coverage, date_coverage, alphas_count, date_added,
               field_role, economic_theme, alpha_family,
               expected_turnover, missing_risk, recommended_operators, notes
        FROM fields
        ORDER BY category, dataset_name, field_name
    """)

    if df.empty:
        st.warning("No fields ingested yet.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cats = st.multiselect("Category", sorted(df["category"].dropna().unique()))
        with c2:
            dsets = st.multiselect("Dataset", sorted(df["dataset_name"].dropna().unique()))
        with c3:
            themes = st.multiselect("Theme", sorted(df["economic_theme"].dropna().unique()))
        with c4:
            kw = st.text_input("Keyword", "")

        view = df.copy()
        if cats:
            view = view[view["category"].isin(cats)]
        if dsets:
            view = view[view["dataset_name"].isin(dsets)]
        if themes:
            view = view[view["economic_theme"].isin(themes)]
        if kw.strip():
            k = kw.strip().lower()
            view = view[view.apply(lambda r: k in str(r.to_dict()).lower(), axis=1)]

        st.caption(f"Showing {len(view)} fields")
        st.dataframe(view, use_container_width=True, height=600)
        st.download_button("Download filtered fields CSV", view.to_csv(index=False).encode("utf-8-sig"), "fields_filtered.csv", "text/csv")


# ---------------- Datasets ----------------
elif page == "Datasets":
    st.header("Datasets")
    df = read_sql("""
        SELECT category, dataset_name, region, delay, universe, fields_count,
               coverage, date_coverage, value_score, alphas_count, last_field_added
        FROM datasets
        ORDER BY category, dataset_name
    """)
    st.dataframe(df, use_container_width=True)


# ---------------- Experiments ----------------
elif page == "Experiments":
    st.header("Experiments")

    st.subheader("Manual result entry")
    with st.form("add_experiment"):
        alpha_expression = st.text_area("Alpha expression")
        c1, c2, c3, c4 = st.columns(4)
        region = c1.text_input("Region", "USA")
        universe = c2.text_input("Universe", "TOP3000")
        delay = c3.number_input("Delay", value=1, step=1)
        decay = c4.number_input("Decay", value=5, step=1)

        c5, c6, c7, c8 = st.columns(4)
        truncation = c5.number_input("Truncation", value=0.01, step=0.01, format="%.4f")
        neutralization = c6.text_input("Neutralization", "Industry")
        pasteurization = c7.text_input("Pasteurization", "On")
        subuniverse_sharpe = c8.number_input("Subuniverse Sharpe", value=0.0, step=0.01)

        c9, c10, c11, c12, c13, c14 = st.columns(6)
        sharpe = c9.number_input("Sharpe", value=0.0, step=0.01)
        fitness = c10.number_input("Fitness", value=0.0, step=0.01)
        turnover = c11.number_input("Turnover", value=0.0, step=0.01)
        returns = c12.number_input("Returns", value=0.0, step=0.01)
        drawdown = c13.number_input("Drawdown", value=0.0, step=0.01)
        margin = c14.number_input("Margin", value=0.0, step=0.01)

        fail_reasons = st.text_area("Fail reasons / notes")
        submitted = st.form_submit_button("Save experiment")

        if submitted:
          params = {
        "alpha_expression": alpha_expression,
        "region": region,
        "universe": universe,
        "delay": delay,
        "decay": decay,
        "truncation": truncation,
        "neutralization": neutralization,
        "pasteurization": pasteurization,
        "sharpe": sharpe,
        "fitness": fitness,
        "turnover": turnover,
        "returns": returns,
        "drawdown": drawdown,
        "margin": margin,
        "subuniverse_sharpe": subuniverse_sharpe,
        "fail_reasons": fail_reasons,
    }

          exec_sql("""
        INSERT INTO experiments (
            alpha_expression, region, universe, delay, decay, truncation,
            neutralization, pasteurization, sharpe, fitness, turnover,
            returns, drawdown, margin, subuniverse_sharpe, fail_reasons
        ) VALUES (
            :alpha_expression, :region, :universe, :delay, :decay, :truncation,
            :neutralization, :pasteurization, :sharpe, :fitness, :turnover,
            :returns, :drawdown, :margin, :subuniverse_sharpe, :fail_reasons
        )
            """, params)
    st.success("Experiment saved")

    st.subheader("Saved experiments")
    df = read_sql("SELECT * FROM experiments ORDER BY created_at DESC")
    st.dataframe(df, use_container_width=True, height=450)


# ---------------- DB Admin ----------------
elif page == "DB Admin":
    st.header("DB Admin")
    st.warning("These actions modify your local SQLite database only.")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Delete all alpha candidates"):
            exec_sql("DELETE FROM alpha_candidates")
            st.warning("Deleted all alpha candidates")
            st.rerun()
    with c2:
        if st.button("Delete bad/archived candidates"):
            exec_sql("DELETE FROM alpha_candidates WHERE status IN ('bad','archived')")
            st.warning("Deleted bad/archived candidates")
            st.rerun()
    with c3:
        if st.button("Delete all experiments"):
            exec_sql("DELETE FROM experiments")
            st.warning("Deleted all experiments")
            st.rerun()

    st.subheader("Delete by family")
    fams = read_sql("SELECT family, COUNT(*) AS n FROM alpha_candidates GROUP BY family ORDER BY n DESC")
    st.dataframe(fams, use_container_width=True)
    family_to_delete = st.selectbox("Family to delete", [""] + fams["family"].dropna().tolist()) if not fams.empty else ""
    if st.button("Delete family", disabled=not family_to_delete):
        exec_sql("DELETE FROM alpha_candidates WHERE family=:f", {"f": family_to_delete})
        st.warning(f"Deleted family {family_to_delete}")
        st.rerun()


# ---------------- SQL ----------------
elif page == "SQL":
    st.header("SQL")
    q = st.text_area("Query", "SELECT family, COUNT(*) AS n FROM alpha_candidates GROUP BY family ORDER BY n DESC;")
    if st.button("Run"):
        try:
            st.dataframe(read_sql(q), use_container_width=True)
        except Exception as e:
            st.error(str(e))
