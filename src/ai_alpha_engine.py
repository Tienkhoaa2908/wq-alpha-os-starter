
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

DB_PATH = Path("data/db/wq_alpha_os.sqlite")
DEBUG_DIR = Path("data/debug")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """
You are a WorldQuant BRAIN alpha research assistant.

You must not generate isolated toy formulas. You generate research-valid alpha families.

Hard research rules:
1. Every alpha must express an economic hypothesis, not just a mathematical transformation.
2. Do not generate simple rank(field), rank(field1 + field2), or rank(field1 * field2).
3. Each alpha must combine at least two logical components, for example:
   - analyst revision direction + quality/value confirmation
   - valuation + profitability/quality confirmation
   - fundamental quality + liquidity/tradability filter
   - risk control + value/quality score
4. Always use group or time-series normalization:
   group_rank, group_neutralize, group_zscore, ts_rank, ts_zscore, ts_backfill, winsorize, normalize.
5. If field direction is uncertain, generate paired direction or clearly use reverse(...).
6. Use Price Volume only as liquidity/timing filter, not as the main alpha.
7. Avoid already weak ideas:
   - composite_factor_score_derivative alone
   - earnings_certainty_rank_derivative * analyst_revision_rank_derivative
   - raw rank(field1 + field2)
   - raw rank(field1 * field2)
8. Prefer alphas that might survive weak years such as 2019/2020/2023 by combining:
   - a slow fundamental/value/quality component
   - a model/analyst component
   - optional liquidity filter.

Return candidates in XML-like tags. Do not use markdown.

Format:
<CANDIDATES>
<CANDIDATE>
<expression>...</expression>
<family>...</family>
<fields_used>field1,field2</fields_used>
<operators_used>op1,op2</operators_used>
<region>USA</region>
<universe>TOP3000</universe>
<delay>1</delay>
<decay>6</decay>
<truncation>0.01</truncation>
<neutralization>Industry</neutralization>
<pasteurization>On</pasteurization>
<hypothesis>...</hypothesis>
<why_this_might_work>...</why_this_might_work>
<turnover_expectation>low|medium|high</turnover_expectation>
<risk_notes>...</risk_notes>
<first_mutation_if_sharpe_negative>...</first_mutation_if_sharpe_negative>
<first_mutation_if_turnover_high>...</first_mutation_if_turnover_high>
<priority_score>0-100</priority_score>
</CANDIDATE>
</CANDIDATES>
""".strip()


def connect(db_path: Path = DB_PATH):
    return sqlite3.connect(db_path)


def rows_to_dicts(cur) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_context(
    db_path: Path = DB_PATH,
    max_fields: int = 80,
    max_ops: int = 60,
    max_exps: int = 30,
) -> dict[str, Any]:
    conn = connect(db_path)
    conn.row_factory = sqlite3.Row

    field_query = """
    SELECT
        field_name, dataset_name, category, description, field_type,
        coverage, date_coverage, alphas_count,
        field_role, economic_theme, alpha_family,
        expected_turnover, missing_risk, recommended_operators
    FROM fields
    WHERE field_type = 'Matrix'
      AND COALESCE(category, '') IN ('Model', 'Fundamental', 'Price Volume')
      AND COALESCE(field_role, '') NOT IN ('identifier', 'group_control')
      AND COALESCE(field_name, '') NOT IN ('ticker','cusip','isin','sedol')
      AND COALESCE(coverage, 0) >= 40
      AND COALESCE(date_coverage, 0) >= 90
    ORDER BY
      CASE dataset_name
        WHEN 'Fundamental Scores' THEN 1
        WHEN 'Analysts'' Factor Model' THEN 2
        WHEN 'Systematic Risk Metrics' THEN 3
        WHEN 'Company Fundamental Data for Equity' THEN 4
        WHEN 'Price Volume Data for Equity' THEN 5
        ELSE 10
      END,
      CASE
        WHEN field_name IN (
          'analyst_revision_rank_derivative',
          'earnings_certainty_rank_derivative',
          'relative_valuation_rank_derivative',
          'growth_potential_rank_derivative',
          'cashflow_efficiency_rank_derivative',
          'fcf_yield_times_forward_roe',
          'fscore_total',
          'high_low_eps_revision_sum',
          'mdl177_2_deepvaluefactor_ttmcfp',
          'volume',
          'adv20'
        ) THEN 0
        ELSE 1
      END,
      coverage DESC,
      date_coverage DESC,
      alphas_count ASC
    LIMIT ?
    """
    fields = rows_to_dicts(conn.execute(field_query, (max_fields,)))

    op_query = """
    SELECT operator_name, category, signature, description
    FROM operators
    WHERE operator_name IN (
        'rank','ts_rank','ts_zscore','ts_backfill','group_backfill','winsorize',
        'group_rank','group_neutralize','group_zscore','group_mean','bucket','densify',
        'trade_when','hump','ts_decay_linear','normalize','quantile','ts_delta',
        'ts_mean','ts_sum','ts_std_dev','divide','multiply','add','subtract',
        'reverse','signed_power','kth_element','last_diff_value','days_from_last_change',
        'ts_regression'
    )
    ORDER BY category, operator_name
    LIMIT ?
    """
    try:
        operators = rows_to_dicts(conn.execute(op_query, (max_ops,)))
    except sqlite3.OperationalError:
        operators = []

    exp_query = """
    SELECT alpha_expression, sharpe, fitness, turnover, returns, drawdown, margin, fail_reasons
    FROM experiments
    ORDER BY created_at DESC
    LIMIT ?
    """
    try:
        experiments = rows_to_dicts(conn.execute(exp_query, (max_exps,)))
    except sqlite3.OperationalError:
        experiments = []

    conn.close()
    return {"fields": fields, "operators": operators, "recent_experiments": experiments}


def build_user_prompt(context: dict[str, Any], n: int = 5, extra_instruction: str = "") -> str:
    return f"""
Generate {n} WorldQuant BRAIN Fast Expression candidates.

The goal is NOT random exploration. The goal is to find a submit-capable alpha by following a family-research process.

Research observations so far:
- Pure Price Volume and short-term reversal had turnover/fitness problems.
- Many model-score alphas are direction ambiguous; reverse often performs better.
- analyst_revision_rank_derivative reverse had low turnover and some signal but weak 2019/2020/2023 robustness.
- Therefore new candidates must combine model/analyst direction with slow fundamental/value/quality confirmation.
- Avoid single-field single-transform alphas.

Allowed formula skeletons:
1. normalize(add(weighted_component_1, weighted_component_2, optional_component_3, filter=true), useStd=true, limit=3)
2. trade_when(volume > adv20, core_composite_signal, -1)
3. group_rank(ts_rank(FIELD, 60/120/252), industry/subindustry)
4. reverse(group_rank(ts_rank(FIELD, 60/120/252), industry/subindustry))
5. group_zscore(winsorize(ts_backfill(FUNDAMENTAL_FIELD, 252), std=4), subindustry)
6. group_neutralize(COMPOSITE_SIGNAL, industry)

Preferred component types:
- Analyst/model direction component: analyst revision, EPS revision, earnings certainty, model score.
- Value component: valuation, cash-flow-to-price, FCF yield.
- Quality component: fscore, cashflow efficiency, forward ROE, profitability.
- Liquidity/timing: volume > adv20 only as trade_when trigger.

Extra instruction from researcher:
{extra_instruction}

CONTEXT:
{json.dumps(context, ensure_ascii=False, indent=2)[:120000]}
""".strip()


def get_tag(block: str, tag: str, default: str = "") -> str:
    m = re.search(fr"<{tag}>\s*(.*?)\s*</{tag}>", block, flags=re.S | re.I)
    if not m:
        return default
    return m.group(1).strip()


def parse_candidates_from_text(text: str) -> dict[str, Any]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / "last_gemini_raw_response.txt").write_text(text, encoding="utf-8")

    # First try JSON in case model obeys JSON despite prompt.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "candidates" in obj:
            return obj
        if isinstance(obj, list):
            return {"candidates": obj}
    except Exception:
        pass

    candidates: list[dict[str, Any]] = []

    # Robust candidate splitting: match full blocks first.
    blocks = re.findall(r"<CANDIDATE>\s*(.*?)\s*</CANDIDATE>", text, flags=re.S | re.I)

    # If closing tags are missing, split by opening tag.
    if not blocks and "<CANDIDATE>" in text:
        parts = re.split(r"<CANDIDATE>", text, flags=re.I)
        blocks = [p for p in parts[1:] if "<expression>" in p]

    # Last fallback: one expression per line/tag.
    if not blocks and "<expression>" in text:
        blocks = re.findall(r"(<expression>.*?)(?=<expression>|$)", text, flags=re.S | re.I)

    for block in blocks:
        expression = get_tag(block, "expression")
        if not expression:
            m = re.search(r"<expression>\s*(.*?)(?:</expression>|<family>|$)", block, flags=re.S | re.I)
            if m:
                expression = m.group(1).strip()

        expression = clean_expression(expression)
        if not expression:
            continue

        ok, gate_reason = alpha_quality_gate(expression)
        if not ok:
            continue

        settings = {
            "region": get_tag(block, "region", "USA") or "USA",
            "universe": get_tag(block, "universe", "TOP3000") or "TOP3000",
            "delay": safe_int(get_tag(block, "delay", "1"), 1),
            "decay": safe_int(get_tag(block, "decay", "6"), 6),
            "truncation": safe_float(get_tag(block, "truncation", "0.01"), 0.01),
            "neutralization": get_tag(block, "neutralization", "Industry") or "Industry",
            "pasteurization": get_tag(block, "pasteurization", "On") or "On",
        }

        candidates.append({
            "expression": expression,
            "family": get_tag(block, "family", "gemini_research_family"),
            "fields_used": split_csv(get_tag(block, "fields_used")),
            "operators_used": split_csv(get_tag(block, "operators_used")),
            "settings": settings,
            "hypothesis": get_tag(block, "hypothesis"),
            "why_this_might_work": get_tag(block, "why_this_might_work"),
            "turnover_expectation": get_tag(block, "turnover_expectation", "medium"),
            "risk_notes": get_tag(block, "risk_notes", gate_reason),
            "first_mutation_if_sharpe_negative": get_tag(block, "first_mutation_if_sharpe_negative", "Test reverse(expression) or remove the weakest component."),
            "first_mutation_if_turnover_high": get_tag(block, "first_mutation_if_turnover_high", "Increase ts_rank window or decay."),
            "priority_score": safe_int(get_tag(block, "priority_score", "50"), 50),
        })

    if not candidates:
        preview = text[:1500]
        raise ValueError(
            "Gemini returned a response that could not be parsed into accepted candidates. "
            "Raw response saved to data/debug/last_gemini_raw_response.txt. "
            f"First 1500 chars: {preview}"
        )

    return {"candidates": candidates}


def clean_expression(expression: str) -> str:
    expr = (expression or "").strip()
    expr = re.sub(r"^```(?:text|json)?", "", expr, flags=re.I).strip()
    expr = re.sub(r"```$", "", expr).strip()
    expr = expr.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    # Remove accidental trailing tags.
    expr = re.split(r"</?[a-zA-Z_]+>", expr)[0].strip()
    return expr


def split_csv(s: str) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in re.split(r"[,;]", s) if x.strip()]


def safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(str(x).strip()))
    except Exception:
        return default


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return default


BAD_PATTERNS = [
    r"^\s*rank\s*\([^()]*\+[^()]*\)\s*$",
    r"^\s*rank\s*\([^()]*\*[^()]*\)\s*$",
    r"composite_factor_score_derivative\s*\)?\s*$",
    r"earnings_certainty_rank_derivative\s*\*\s*analyst_revision_rank_derivative",
]

REQUIRED_GOOD_OPERATORS = [
    "group_rank",
    "group_neutralize",
    "group_zscore",
    "ts_rank",
    "ts_zscore",
    "ts_backfill",
    "normalize",
    "winsorize",
    "trade_when",
]


def alpha_quality_gate(expression: str) -> tuple[bool, str]:
    expr = expression.strip()

    if len(expr) < 12:
        return False, "too short"

    for pat in BAD_PATTERNS:
        if re.search(pat, expr):
            return False, f"bad pattern: {pat}"

    if expr.count("(") != expr.count(")"):
        return False, "unbalanced parentheses"

    good_count = sum(1 for op in REQUIRED_GOOD_OPERATORS if op in expr)
    if good_count < 2:
        return False, "needs at least two research operators"

    # Reject single raw field wrapped once.
    if re.fullmatch(r"(reverse\()?rank\([a-zA-Z0-9_]+\)\)?", expr):
        return False, "single raw rank field"

    # Arithmetic combination must be normalized/grouped.
    if ("+" in expr or "*" in expr) and not any(op in expr for op in ["normalize", "group_rank", "group_neutralize", "ts_rank", "group_zscore"]):
        return False, "arithmetic without normalization"

    # Avoid absurd nesting. Some valid expressions are nested, but too deep is usually overfit.
    if expr.count("(") > 18:
        return False, "too deeply nested"

    return True, "accepted"


def call_gemini(prompt: str, model: str = "gemini-2.5-flash") -> dict[str, Any]:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found. Create .env with GEMINI_API_KEY=...")

    try:
        from google import genai
    except Exception as exc:
        raise RuntimeError("google-genai is not installed. Run: python -m pip install google-genai") from exc

    client = genai.Client(api_key=api_key)

    full_prompt = SYSTEM_PROMPT + "\n\n" + prompt

    response = client.models.generate_content(
        model=model,
        contents=full_prompt,
    )

    text = getattr(response, "text", None)
    if not text:
        text = str(response)

    return parse_candidates_from_text(text)


def save_ai_candidates(result: dict[str, Any], db_path: Path = DB_PATH) -> int:
    candidates = result.get("candidates", [])
    conn = connect(db_path)
    inserted_before = conn.total_changes

    for c in candidates:
        expr = c.get("expression", "").strip()
        if not expr:
            continue

        ok, reason = alpha_quality_gate(expr)
        if not ok:
            continue

        conn.execute("""
        INSERT OR IGNORE INTO alpha_candidates (
            expression, family, fields_used, operators_used,
            hypothesis, expected_turnover, expected_risk, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            expr,
            c.get("family", "gemini_research_family"),
            ",".join(c.get("fields_used", [])) if isinstance(c.get("fields_used"), list) else str(c.get("fields_used", "")),
            ",".join(c.get("operators_used", [])) if isinstance(c.get("operators_used"), list) else str(c.get("operators_used", "")),
            c.get("hypothesis", "") + "\n" + c.get("why_this_might_work", ""),
            c.get("turnover_expectation", ""),
            json.dumps({
                "settings": c.get("settings", {}),
                "risk_notes": c.get("risk_notes", ""),
                "mutation_if_sharpe_negative": c.get("first_mutation_if_sharpe_negative", ""),
                "mutation_if_turnover_high": c.get("first_mutation_if_turnover_high", ""),
                "priority_score": c.get("priority_score", 0),
            }, ensure_ascii=False),
            "ai_generated_gemini"
        ))

    conn.commit()
    inserted = conn.total_changes - inserted_before
    conn.close()
    return inserted


def generate_ai_alphas(
    n: int = 5,
    model: str = "gemini-2.5-flash",
    extra_instruction: str = "",
    max_fields: int = 80,
    max_ops: int = 60,
    max_exps: int = 30,
) -> dict[str, Any]:
    context = get_context(max_fields=max_fields, max_ops=max_ops, max_exps=max_exps)
    prompt = build_user_prompt(context, n=n, extra_instruction=extra_instruction)
    result = call_gemini(prompt, model=model)
    inserted = save_ai_candidates(result)
    result["_inserted"] = inserted
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument("--instruction", default="")
    p.add_argument("--max-fields", type=int, default=80)
    p.add_argument("--max-ops", type=int, default=60)
    p.add_argument("--max-exps", type=int, default=30)
    args = p.parse_args()

    out = generate_ai_alphas(
        n=args.n,
        model=args.model,
        extra_instruction=args.instruction,
        max_fields=args.max_fields,
        max_ops=args.max_ops,
        max_exps=args.max_exps,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
