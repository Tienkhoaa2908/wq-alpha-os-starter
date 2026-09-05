"""Kho tri thức chỉ đọc cho vòng khám phá giả thuyết.

Mô-đun này không sinh biểu thức, không gọi mô hình và không ghi vào SQLite.
Nó biến danh mục trường dữ liệu cùng kết quả mô phỏng đã có thành ba đầu vào
nhỏ, có thể chuyển thẳng cho một tác tử nghiên cứu:

* ``failure_ledger``: những cách làm đã thất bại và bài học có căn cứ;
* ``hypothesis_cards``: các giả thuyết theo chủ đề, chưa phải alpha;
* ``build_discovery_context``: gói JSON ngắn kết hợp hai phần trên.

Việc để mô hình ngôn ngữ bắt đầu từ thẻ giả thuyết thay vì biểu thức giúp
ngăn nó chỉ thay hằng số của alpha cũ. Mọi kết luận trong sổ tri thức đều
được gắn với dữ liệu mô phỏng cục bộ hoặc lý do bị từ chối đã lưu.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any, Iterable

from ..config import load_defaults
from .scorer import check_summary
from .taxonomy import normalize_theme


DISCOVERY_CONTEXT_VERSION = "discovery-v1"

__all__ = [
    "DISCOVERY_CONTEXT_VERSION",
    "build_discovery_context",
    "failure_ledger",
    "hypothesis_cards",
]


# Các mẫu dưới đây chỉ tạo ngôn ngữ cho một giả thuyết có thể bác bỏ. Chúng
# không phải là công thức alpha, không suy luận hiệu quả và không chọn toán tử
# cụ thể thay cho bước thiết kế tiếp theo.
THEME_TEMPLATES: dict[str, dict[str, str]] = {
    "value": {
        "statement": "Kiểm tra liệu định giá tương đối theo dòng tiền còn mang thông tin dự báo sau khi loại bớt khác biệt nhóm.",
        "mechanism": "Nếu thị trường điều chỉnh chậm với dòng tiền bền vững, doanh nghiệp rẻ tương đối có thể được định giá lại dần.",
        "horizon": "Trung hạn; bắt đầu bằng một khung thời gian, không phối nhiều khung ngay.",
    },
    "profitability": {
        "statement": "Kiểm tra liệu chất lượng lợi nhuận phân biệt được doanh nghiệp có hiệu quả vận hành bền vững.",
        "mechanism": "Khả năng sinh lời và chất lượng bảng cân đối có thể được phản ánh không đồng đều giữa các doanh nghiệp cùng nhóm.",
        "horizon": "Trung hạn; ưu tiên tín hiệu ổn định hơn là thay đổi giá ngắn hạn.",
    },
    "analyst_revision": {
        "statement": "Kiểm tra liệu thay đổi trong kỳ vọng của nhà phân tích chứa thông tin chưa được hấp thụ hoàn toàn.",
        "mechanism": "Sự điều chỉnh dự báo có thể dẫn dắt quá trình cập nhật định giá, nhưng dấu phải được kiểm tra bằng thí nghiệm chẩn đoán.",
        "horizon": "Ngắn đến trung hạn; cần kiểm soát vòng quay trước khi ghép nhánh khác.",
    },
    "earnings_surprise": {
        "statement": "Kiểm tra liệu mức phân tán hoặc bất ngờ trong kỳ vọng lợi nhuận phản ánh bất định đang bị định giá thiếu.",
        "mechanism": "Khác biệt quan điểm của thị trường có thể tạo ra lợi nhuận sau khi thông tin mới được giải quyết.",
        "horizon": "Sự kiện đến trung hạn; phải xác định dấu riêng cho từng trường dữ liệu.",
    },
    "growth": {
        "statement": "Kiểm tra liệu thay đổi bền vững về tăng trưởng được phản ánh chậm trong định giá chéo.",
        "mechanism": "Thị trường có thể phản ứng chưa đầy đủ khi quỹ đạo tăng trưởng thay đổi nhưng chất lượng của thay đổi còn chưa rõ.",
        "horizon": "Trung hạn; tách kiểm tra mức độ và tốc độ thay đổi.",
    },
    "leverage": {
        "statement": "Kiểm tra liệu rủi ro đòn bẩy tương đối dự báo khác biệt lợi nhuận sau khi so trong cùng nhóm.",
        "mechanism": "Khả năng chịu đựng chu kỳ và chi phí vốn khác nhau có thể làm mức đòn bẩy được định giá lại.",
        "horizon": "Trung hạn; hướng âm chỉ là giả định cần được bác bỏ hoặc xác nhận.",
    },
    "risk_volatility": {
        "statement": "Kiểm tra liệu mức rủi ro riêng lẻ hoặc biến động tương đối chứa phần bù rủi ro có thể khai thác.",
        "mechanism": "Rủi ro thực tế, rủi ro được kỳ vọng và nhu cầu phòng hộ có thể tạo ra chênh lệch định giá.",
        "horizon": "Ngắn đến trung hạn; bắt buộc theo dõi vòng quay và độ ổn định theo năm.",
    },
    "price": {
        "statement": "Kiểm tra một cơ chế giá hoặc thanh khoản riêng biệt thay vì sao chép động lượng tổng quát.",
        "mechanism": "Dòng lệnh, thanh khoản và quá trình hấp thụ thông tin có thể khác nhau giữa các doanh nghiệp cùng nhóm.",
        "horizon": "Ngắn hạn; chỉ dùng một biến đổi thời gian để đo cơ chế trước.",
    },
    "options": {
        "statement": "Kiểm tra liệu chênh lệch kỳ vọng rủi ro từ dữ liệu quyền chọn dự báo lợi nhuận cổ phiếu tương đối.",
        "mechanism": "Định giá biến động và nhu cầu phòng hộ có thể truyền thông tin chưa phản ánh hết sang thị trường cơ sở.",
        "horizon": "Ngắn đến trung hạn; không ghép với giá cơ sở trước khi có bằng chứng độc lập.",
    },
    "sentiment_news": {
        "statement": "Kiểm tra liệu thông tin hoặc tâm lý mới có độ bền sau khi loại ảnh hưởng theo nhóm.",
        "mechanism": "Thông tin công khai có thể được hấp thụ dần, hoặc phản ứng ban đầu có thể quá mức; dấu cần kiểm tra chẩn đoán.",
        "horizon": "Ngắn hạn; ưu tiên kiểm tra độ suy giảm và kiểm soát vòng quay.",
    },
    "short_interest": {
        "statement": "Kiểm tra liệu áp lực bán khống tương đối phản ánh thông tin tiêu cực hoặc rủi ro ép mua.",
        "mechanism": "Mức bán khống có thể đồng thời chứa thông tin cơ bản và ràng buộc giao dịch, nên hướng không được giả định trước.",
        "horizon": "Ngắn đến trung hạn; thử dấu riêng trước khi kết hợp.",
    },
    "insider": {
        "statement": "Kiểm tra liệu hoạt động của người nội bộ truyền tải thông tin về giá trị hoặc thời điểm doanh nghiệp.",
        "mechanism": "Người nội bộ có thể hành động khi nhận thức của họ khác với định giá hiện tại, nhưng độ trễ công bố cần được xem xét.",
        "horizon": "Sự kiện đến trung hạn; kiểm tra độ phủ và độ trễ trước.",
    },
    "relationship": {
        "statement": "Kiểm tra liệu thông tin từ quan hệ doanh nghiệp lan truyền giữa các công ty liên quan.",
        "mechanism": "Tin tức và cú sốc tại khách hàng, nhà cung cấp hoặc mạng lưới có thể chưa được phản ánh đồng thời.",
        "horizon": "Sự kiện đến trung hạn; bắt đầu bằng một quan hệ, không trộn với giá trị hoặc động lượng.",
    },
}


_MODE_ORDER = (
    "platform_error",
    "brain_check_failed",
    "missing_metrics",
    "negative_sharpe",
    "low_fitness",
    "low_turnover",
    "high_turnover",
    "high_self_correlation",
    "exact_duplicate",
    "near_duplicate",
    "validation_failed",
    "candidate_rejected",
)

_MODE_LESSONS = {
    "platform_error": "Không suy luận chất lượng từ lỗi nền tảng; chỉ thử lại khi bằng chứng yêu cầu hoặc phản hồi đã đầy đủ.",
    "brain_check_failed": "Xem điều kiện kiểm tra thất bại trước khi tinh chỉnh tham số; không dùng điểm tổng hợp để che lỗi điều kiện.",
    "missing_metrics": "Chưa có đủ bằng chứng định lượng; không dùng nhánh này làm cha cho biến thể mới.",
    "negative_sharpe": "Chỉ cho phép một phép đảo chiều chẩn đoán; nếu vẫn yếu thì chuyển sang cơ chế khác.",
    "low_fitness": "Không quét dày trọng số hoặc cửa sổ; giữ tối đa một biến thể chẩn đoán rồi đổi cơ chế hoặc trường dữ liệu.",
    "low_turnover": "Kiểm tra tín hiệu có thực sự biến thiên trước khi kéo dài thêm cửa sổ thời gian.",
    "high_turnover": "Ưu tiên kiểm soát độ ổn định trước khi ghép thêm nhánh; không vừa đổi cơ chế vừa sửa vòng quay.",
    "high_self_correlation": "Dừng các biến thể chỉ đổi tham số; phải đổi chủ đề, trường dữ liệu hoặc cơ chế kinh tế.",
    "exact_duplicate": "Giữ dấu vân tay hiện có; đề xuất mới phải thay cơ chế hoặc trường dữ liệu chứ không chỉ đổi hằng số.",
    "near_duplicate": "Không tái thử cấu trúc gần giống nếu không phải phép kiểm tra độ nhạy có cha rõ ràng.",
    "validation_failed": "Sửa ràng buộc kiểu dữ liệu hoặc toán tử trước; lỗi cú pháp không phải bằng chứng về giả thuyết.",
    "candidate_rejected": "Đọc lý do từ chối trước khi sinh lại cùng họ alpha.",
}


def _safe_json(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str):
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed


def _string_list(value: Any, limit: int = 8) -> list[str]:
    parsed = _safe_json(value, [])
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()][:limit]


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _rounded(value: Any, digits: int = 4) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _limits() -> dict[str, float]:
    research = load_defaults().get("research", {})
    return {
        "fitness": float(research.get("promotion_min_fitness", 1.0)),
        "self_correlation": float(research.get("promotion_max_self_correlation", 0.7)),
        "min_coverage": float(research.get("min_field_coverage", 70)),
    }


def _ordered_modes(modes: Iterable[str]) -> list[str]:
    unique = set(modes)
    ordered = [mode for mode in _MODE_ORDER if mode in unique]
    return ordered + sorted(unique.difference(ordered))


def _failure_modes(row: sqlite3.Row, limits: dict[str, float]) -> tuple[list[str], list[str]]:
    """Return compact failure labels and failed BRAIN check names for one run."""
    modes: list[str] = []
    failed_checks: list[str] = []
    status = str(row["platform_status"] or "").upper()
    if status != "COMPLETE":
        modes.append("platform_error")
    checks = _safe_json(row["checks_json"], [])
    _, failed, failures = check_summary(checks)
    if failed:
        modes.append("brain_check_failed")
        failed_checks.extend(failures[:3])
    if status != "COMPLETE":
        return _ordered_modes(modes), failed_checks

    sharpe = _number(row["sharpe"])
    fitness = _number(row["fitness"])
    turnover = _number(row["turnover"])
    self_correlation = _number(row["self_correlation"])
    if sharpe is None or fitness is None:
        modes.append("missing_metrics")
    else:
        if sharpe <= 0:
            modes.append("negative_sharpe")
        if fitness < limits["fitness"]:
            modes.append("low_fitness")
    if turnover is not None:
        if turnover < 0.01:
            modes.append("low_turnover")
        elif turnover > 0.7:
            modes.append("high_turnover")
    if self_correlation is not None and self_correlation > limits["self_correlation"]:
        modes.append("high_self_correlation")
    return _ordered_modes(modes), failed_checks


def _summarize_numbers(values: Iterable[float | None]) -> dict[str, float | None]:
    # Các truy vấn nguồn được sắp theo thời gian giảm dần, nên phần tử đầu là
    # quan sát mới nhất của nhóm; phần còn lại chỉ dùng để nêu biên độ.
    clean = [value for value in values if value is not None]
    if not clean:
        return {"best": None, "worst": None, "latest": None}
    return {
        "best": round(max(clean), 4),
        "worst": round(min(clean), 4),
        "latest": round(clean[0], 4),
    }


def _lesson(modes: Iterable[str]) -> str:
    snippets = [_MODE_LESSONS[mode] for mode in _ordered_modes(modes) if mode in _MODE_LESSONS]
    return " ".join(snippets[:2]) or "Chưa có bài học đủ rõ để tái sử dụng."


def failure_ledger(connection: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    """Tổng hợp thất bại từ SQLite thành sổ tri thức ngắn, chỉ đọc.

    Một mục có thể gộp nhiều lần mô phỏng cùng họ và cùng kiểu thất bại. Nó
    không bao giờ trả biểu thức alpha đầy đủ, nhằm tránh làm mô hình ngôn ngữ
    bắt chước một biến thể thất bại. ``limit`` áp dụng sau khi gộp.
    """
    if limit <= 0:
        return []
    limits = _limits()
    scan_limit = max(80, limit * 20)
    rows = connection.execute(
        """SELECT a.family,a.field_names_json,a.operator_names_json,a.mutation,
                  r.platform_status,r.sharpe,r.fitness,r.turnover,r.self_correlation,
                  r.checks_json,r.error_text,r.started_at,r.finished_at
           FROM simulation_runs r
           JOIN alpha_artifacts a ON a.id=r.artifact_id
           WHERE a.status!='legacy_unverified'
           ORDER BY coalesce(r.finished_at,r.started_at) DESC LIMIT ?""",
        (scan_limit,),
    ).fetchall()
    grouped: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    for row in rows:
        modes, failed_checks = _failure_modes(row, limits)
        if not modes:
            continue
        family = str(row["family"] or "unknown")
        key = ("simulation", family, tuple(modes))
        entry = grouped.setdefault(
            key,
            {
                "origin": "simulation",
                "family": family,
                "failure_modes": modes,
                "count": 0,
                "latest_at": "",
                "fields": set(),
                "operators": set(),
                "failed_checks": set(),
                "mutations": set(),
                "sharpe": [],
                "fitness": [],
                "turnover": [],
                "self_correlation": [],
            },
        )
        entry["count"] += 1
        entry["latest_at"] = max(str(row["finished_at"] or row["started_at"] or ""), entry["latest_at"])
        entry["fields"].update(_string_list(row["field_names_json"]))
        entry["operators"].update(_string_list(row["operator_names_json"]))
        entry["failed_checks"].update(failed_checks)
        if row["mutation"]:
            entry["mutations"].add(str(row["mutation"]))
        entry["sharpe"].append(_number(row["sharpe"]))
        entry["fitness"].append(_number(row["fitness"]))
        entry["turnover"].append(_number(row["turnover"]))
        entry["self_correlation"].append(_number(row["self_correlation"]))

    rejected = connection.execute(
        """SELECT family,reason,details_json,created_at
           FROM rejected_candidates ORDER BY created_at DESC LIMIT ?""",
        (scan_limit,),
    ).fetchall()
    for row in rejected:
        reason = str(row["reason"] or "candidate_rejected")
        normalized = reason if reason in _MODE_LESSONS else "candidate_rejected"
        family = str(row["family"] or "unknown")
        key = ("candidate_rejection", family, (normalized,))
        entry = grouped.setdefault(
            key,
            {
                "origin": "candidate_rejection",
                "family": family,
                "failure_modes": [normalized],
                "count": 0,
                "latest_at": "",
                "fields": set(),
                "operators": set(),
                "failed_checks": set(),
                "mutations": set(),
                "sharpe": [],
                "fitness": [],
                "turnover": [],
                "self_correlation": [],
            },
        )
        entry["count"] += 1
        entry["latest_at"] = max(str(row["created_at"] or ""), entry["latest_at"])

    result: list[dict[str, Any]] = []
    for entry in grouped.values():
        result.append(
            {
                "origin": entry["origin"],
                "family": entry["family"],
                "failure_modes": entry["failure_modes"],
                "count": entry["count"],
                "latest_at": entry["latest_at"] or None,
                "fields": sorted(entry["fields"])[:6],
                "operator_shape": sorted(entry["operators"])[:8],
                "failed_checks": sorted(entry["failed_checks"])[:4],
                "mutations": sorted(entry["mutations"])[:3],
                "metrics": {
                    "sharpe": _summarize_numbers(entry["sharpe"]),
                    "fitness": _summarize_numbers(entry["fitness"]),
                    "turnover": _summarize_numbers(entry["turnover"]),
                    "self_correlation": _summarize_numbers(entry["self_correlation"]),
                },
                "lesson": _lesson(entry["failure_modes"]),
            }
        )
    priority = {mode: len(_MODE_ORDER) - index for index, mode in enumerate(_MODE_ORDER)}
    result.sort(
        key=lambda entry: (
            sum(priority.get(mode, 1) for mode in entry["failure_modes"]),
            int(entry["count"]),
            str(entry["latest_at"] or ""),
        ),
        reverse=True,
    )
    return result[:limit]


def _active_artifact_fields(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        """SELECT field_names_json FROM alpha_artifacts
           WHERE status!='legacy_unverified'"""
    ).fetchall()
    result: set[str] = set()
    for row in rows:
        result.update(_string_list(row[0], limit=100))
    return result


def _completed_family_summary(connection: sqlite3.Connection, limit: int = 12) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT a.family,COUNT(r.id) completed_runs,MAX(r.sharpe) best_sharpe,
                  MAX(r.fitness) best_fitness,MIN(r.self_correlation) min_self_correlation
           FROM alpha_artifacts a
           LEFT JOIN simulation_runs r ON r.artifact_id=a.id AND r.platform_status='COMPLETE'
           WHERE a.status!='legacy_unverified'
           GROUP BY a.family
           HAVING COUNT(r.id)>0
           ORDER BY completed_runs DESC,best_fitness DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [
        {
            "family": str(row["family"]),
            "completed_runs": int(row["completed_runs"]),
            "best_sharpe": _rounded(row["best_sharpe"]),
            "best_fitness": _rounded(row["best_fitness"]),
            "min_self_correlation": _rounded(row["min_self_correlation"]),
        }
        for row in rows
    ]


def _field_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    min_coverage = _limits()["min_coverage"]
    rows = connection.execute(
        """SELECT name,dataset_name,description,data_type,coverage,semantic_theme,semantic_direction,alpha_count
           FROM fields
           WHERE upper(coalesce(data_type,'MATRIX')) IN ('MATRIX','VECTOR')
             AND (coverage IS NULL OR coverage>=?)
             AND coalesce(semantic_theme,'generic')!='generic'
           ORDER BY coalesce(coverage,0) DESC,coalesce(alpha_count,0) ASC,name""",
        (min_coverage,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["semantic_theme"] = normalize_theme(item.get("semantic_theme"))
        result.append(item)
    return result


def _field_card(row: dict[str, Any]) -> dict[str, Any]:
    description = " ".join(str(row.get("description") or "").split())
    if len(description) > 180:
        description = description[:177].rstrip() + "..."
    data_type = str(row.get("data_type") or "MATRIX").upper()
    note = None
    if data_type == "VECTOR":
        note = "Dạng véc-tơ; phải rút về một giá trị bằng toán tử véc-tơ trước biến đổi theo thời gian hoặc xếp hạng chéo."
    return {
        "name": str(row.get("name") or ""),
        "dataset": str(row.get("dataset_name") or "unknown"),
        "coverage": _rounded(row.get("coverage"), 2),
        "data_type": data_type,
        "description": description or None,
        "note": note,
    }


def _direction_text(direction: str) -> str:
    if direction == "reverse":
        return "Ưu tiên kiểm tra hướng ngược, nhưng vẫn phải có một kiểm tra dấu chẩn đoán."
    return "Chưa xác định hướng; chỉ kiểm tra một dấu tại một thời điểm và lưu kết quả âm lẫn dương."


def hypothesis_cards(
    connection: sqlite3.Connection,
    limit: int = 6,
    *,
    fields_per_card: int = 3,
) -> list[dict[str, Any]]:
    """Tạo thẻ giả thuyết mới từ danh mục, không tạo biểu thức alpha.

    Các chủ đề chưa từng xuất hiện trong alpha hoạt động được xếp trước. Trong
    một chủ đề, trường chưa thử được ưu tiên trước trường đã xuất hiện, giúp
    tác tử không tái tạo biến thể của alpha cũ chỉ bằng thay đổi tham số.
    """
    if limit <= 0 or fields_per_card <= 0:
        return []
    active_fields = _active_artifact_fields(connection)
    rows = _field_rows(connection)
    by_name = {str(row.get("name") or ""): row for row in rows}
    explored_themes = {
        str(by_name[name].get("semantic_theme") or "generic")
        for name in active_fields
        if name in by_name
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        theme = str(row.get("semantic_theme") or "generic")
        if theme in THEME_TEMPLATES:
            grouped[theme].append(row)

    cards: list[dict[str, Any]] = []
    for theme, candidates in grouped.items():
        template = THEME_TEMPLATES.get(theme)
        if not template:
            continue
        candidates.sort(
            key=lambda row: (
                str(row.get("name") or "") in active_fields,
                -(_number(row.get("coverage")) or 0.0),
                _number(row.get("alpha_count")) or 0.0,
                str(row.get("name") or ""),
            )
        )
        selected: list[dict[str, Any]] = []
        datasets: set[str] = set()
        for row in candidates:
            # Prefer data-source diversity while retaining a useful fallback
            # when one data set is the only available source in this theme.
            dataset = str(row.get("dataset_name") or "unknown")
            if dataset in datasets and len(selected) < fields_per_card - 1:
                continue
            selected.append(_field_card(row))
            datasets.add(dataset)
            if len(selected) >= fields_per_card:
                break
        if not selected:
            continue
        direction = str(candidates[0].get("semantic_direction") or "ambiguous")
        cards.append(
            {
                "card_id": f"theme:{theme}",
                "family": f"{theme}_discovery",
                "theme": theme,
                "novelty": "chủ đề mới" if theme not in explored_themes else "trường mới trong chủ đề đã có",
                "statement": template["statement"],
                "mechanism": template["mechanism"],
                "expected_direction": _direction_text(direction),
                "horizon": template["horizon"],
                "field_candidates": selected,
                "construction_order": [
                    "Bắt đầu từ một trường dữ liệu và cơ chế kinh tế duy nhất.",
                    "Chọn một biến đổi phù hợp với tốc độ cập nhật của trường.",
                    "Chỉ sau đó mới xếp hạng hoặc kiểm soát theo nhóm.",
                    "Chuẩn hóa và kiểm soát vòng quay ở lớp cuối.",
                ],
                "combination_rule": "Không ghép các trường trong thẻ ngay. Chỉ ghép tối đa hai nhánh khi từng nhánh đã có bằng chứng và tương quan lãi/lỗ thấp.",
                "falsification": "Nếu kiểm tra dấu chẩn đoán không cải thiện chất lượng hoặc cho tương quan cao với alpha đang có, đóng thẻ thay vì quét thêm tham số.",
            }
        )
    cards.sort(
        key=lambda card: (
            card["novelty"] != "chủ đề mới",
            str(card["theme"]),
        )
    )
    return cards[:limit]


def _compact_json(context: dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _context_card(card: dict[str, Any]) -> dict[str, Any]:
    """Bỏ các quy tắc lặp lại khỏi một thẻ trước khi đưa vào ngữ cảnh LLM."""
    fields = []
    for field in card["field_candidates"]:
        compact = dict(field)
        description = compact.get("description")
        if isinstance(description, str) and len(description) > 96:
            compact["description"] = description[:93].rstrip() + "..."
        fields.append(compact)
    return {
        "card_id": card["card_id"],
        "family": card["family"],
        "theme": card["theme"],
        "novelty": card["novelty"],
        "statement": card["statement"],
        "mechanism": card["mechanism"],
        "expected_direction": card["expected_direction"],
        "horizon": card["horizon"],
        "field_candidates": fields,
    }


def _context_ledger_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Giữ đủ bằng chứng để tránh lặp, bỏ số liệu phụ của bản ghi dài."""
    observed = {
        name: values.get("latest")
        for name, values in entry.get("metrics", {}).items()
        if isinstance(values, dict) and values.get("latest") is not None
    }
    return {
        "origin": entry["origin"],
        "family": entry["family"],
        "failure_modes": entry["failure_modes"],
        "count": entry["count"],
        "fields": entry["fields"][:4],
        "operator_shape": entry["operator_shape"][:5],
        "failed_checks": entry["failed_checks"],
        "observed": observed,
        "lesson": entry["lesson"],
    }


def build_discovery_context(
    connection: sqlite3.Connection,
    limit: int = 6,
    *,
    failure_limit: int = 6,
    fields_per_card: int = 2,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Trả gói ngữ cảnh nhỏ, tuần tự và chỉ đọc cho tác tử khám phá.

    ``limit`` là số thẻ giả thuyết tối đa. ``max_chars`` giới hạn kích thước
    JSON nén để lời gọi mô hình không lãng phí ngữ cảnh; khi cần cắt bớt, sổ
    thất bại ít ưu tiên bị bỏ trước, rồi đến thẻ cuối danh sách. Gói trả về
    luôn tự mô tả là *chưa phải* đề xuất alpha để tách bước khám phá khỏi
    bước biên dịch biểu thức.
    """
    cards = [_context_card(card) for card in hypothesis_cards(
        connection, limit, fields_per_card=fields_per_card
    )]
    ledger = [_context_ledger_entry(entry) for entry in failure_ledger(connection, failure_limit)]
    family_summary = _completed_family_summary(connection)
    active_fields = sorted(_active_artifact_fields(connection))[:24]
    context: dict[str, Any] = {
        "version": DISCOVERY_CONTEXT_VERSION,
        "purpose": "Khám phá giả thuyết kinh tế khác họ alpha cũ; chưa được sinh biểu thức hay suy luận alpha sẽ tốt.",
        "response_contract": [
            "Chọn tối đa hai thẻ và giải thích cơ chế có thể bác bỏ.",
            "Không trả công thức alpha trong bước này.",
            "Nêu rõ trường dữ liệu được chọn, dấu cần kiểm tra và lý do không phải biến thể của họ đã thử.",
        ],
        "anti_clone_rules": [
            "Không chỉ đổi trọng số, cửa sổ hoặc bọc thêm toán tử quanh alpha cũ.",
            "Không ghép nhiều trường trước khi từng nhánh có bằng chứng riêng.",
            "Một phép kiểm tra chỉ thay một ý chính và phải giữ dấu vết cha-con.",
        ],
        "hypothesis_design_rules": [
            "Bắt đầu từ một trường dữ liệu và cơ chế kinh tế duy nhất.",
            "Chọn một biến đổi phù hợp với tốc độ cập nhật của trường, rồi mới xếp hạng hoặc kiểm soát theo nhóm.",
            "Chỉ ghép tối đa hai nhánh khi từng nhánh đã có bằng chứng và tương quan lãi/lỗ thấp.",
            "Nếu kiểm tra dấu không cải thiện chất lượng hoặc có tương quan cao, đóng thẻ thay vì quét thêm tham số.",
        ],
        "tested_families": family_summary,
        "tested_field_names": active_fields,
        "hypothesis_cards": cards,
        "failure_ledger": ledger,
        "truncated": False,
    }
    if max_chars <= 0:
        return context
    # Không cắt từng chuỗi ở giữa, để JSON và ý nghĩa của một thẻ luôn còn
    # nguyên vẹn. Giữ tối thiểu ba bài học thất bại và hai thẻ khi có thể;
    # đây là hai đầu vào cần thiết để tác tử vừa sáng tạo vừa không lặp lại.
    while len(_compact_json(context)) > max_chars and len(context["failure_ledger"]) > 3:
        context["failure_ledger"].pop()
        context["truncated"] = True
    while len(_compact_json(context)) > max_chars and len(context["hypothesis_cards"]) > 2:
        context["hypothesis_cards"].pop()
        context["truncated"] = True
    while len(_compact_json(context)) > max_chars and context["tested_field_names"]:
        context["tested_field_names"].pop()
        context["truncated"] = True
    while len(_compact_json(context)) > max_chars and context["failure_ledger"]:
        context["failure_ledger"].pop()
        context["truncated"] = True
    while len(_compact_json(context)) > max_chars and context["hypothesis_cards"]:
        context["hypothesis_cards"].pop()
        context["truncated"] = True
    return context
