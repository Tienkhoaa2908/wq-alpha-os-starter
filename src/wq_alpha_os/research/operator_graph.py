"""Đồ thị tương thích có cấu trúc cho các toán tử FASTEXPR.

Mô-đun này mô tả *tương thích cấu trúc*, không khẳng định tương quan lợi
nhuận giữa các toán tử.  Tương quan PnL chỉ được phép kết luận sau khi có
bằng chứng mô phỏng.  Đầu ra của các hàm công khai đều là kiểu Python thuần
(dict, list, str), vì vậy có thể đưa thẳng vào câu nhắc cho mô hình ngôn ngữ
hoặc lưu thành JSON mà không cần truy cập cơ sở dữ liệu hay gọi mạng.

Các nhóm ``alternative`` là nhóm thay thế về vai trò.  Một nhánh tín hiệu chỉ
nên chọn tối đa một toán tử từ mỗi nhóm, trừ khi đang làm phép loại bỏ thành
phần hoặc kiểm tra độ nhạy có chủ đích.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..dsl.nodes import Binary, Call, Identifier, Node, Number, String, Unary, walk
from ..dsl.parser import ParseError, parse
from ..dsl.specs import GROUP_IDENTIFIERS, LITERALS, SPECS


# Vai trò có thể chồng lên nhau.  Ví dụ ``ts_decay_linear`` vừa là biến đổi
# chuỗi thời gian vừa là một cách làm trơn, nhưng nó chỉ thuộc một cụm lựa chọn
# để không buộc mô hình ngôn ngữ phải xem đây là hai ý tưởng độc lập.
ROLE_MEMBERS: dict[str, frozenset[str]] = {
    "vector_reduce": frozenset({"vec_avg", "vec_sum"}),
    "missing_data": frozenset({"ts_backfill", "group_backfill", "kth_element", "last_diff_value"}),
    "time_position": frozenset({"ts_rank", "ts_quantile", "ts_zscore", "ts_scale"}),
    "time_change": frozenset({"ts_delta", "ts_av_diff", "ts_delay", "ts_step", "days_from_last_change"}),
    "time_smoothing": frozenset({"ts_mean", "ts_sum", "ts_product", "ts_decay_linear"}),
    "time_dispersion": frozenset({"ts_std_dev", "ts_count_nans", "ts_arg_max", "ts_arg_min"}),
    "time_relation": frozenset({"ts_corr", "ts_covariance", "ts_regression"}),
    "cross_section_rank": frozenset({"rank", "quantile"}),
    "cross_section_standardize": frozenset({"zscore", "scale", "normalize", "winsorize"}),
    "group_control": frozenset(
        {"group_rank", "group_zscore", "group_neutralize", "group_scale", "group_mean"}
    ),
    "group_builder": frozenset({"bucket", "densify"}),
    "arithmetic": frozenset({"add", "subtract", "multiply", "divide", "max", "min"}),
    "direction": frozenset({"reverse", "inverse", "sign"}),
    "nonlinear": frozenset({"abs", "log", "power", "signed_power", "sqrt"}),
    "conditional": frozenset({"trade_when", "if_else"}),
    "logical": frozenset({"and", "or", "not", "is_nan"}),
    "turnover_control": frozenset({"hump"}),
    "transform": frozenset({"densify", "bucket"}),
}


@dataclass(frozen=True)
class OperatorCluster:
    """Một cụm toán tử có ý nghĩa gần nhau về cấu trúc.

    ``selection`` luôn là mô tả cấu trúc, không phải khẳng định về PnL hay
    Sharpe.  Nó giúp tác tử không xếp chồng các phép gần như cùng vai trò chỉ
    để làm biểu thức dài hơn.
    """

    id: str
    members: tuple[str, ...]
    max_per_branch: int
    selection: str
    rationale: str

    def to_dict(self, available: set[str] | None = None) -> dict[str, Any]:
        members = [name for name in self.members if available is None or name in available]
        return {
            "id": self.id,
            "members": members,
            "max_per_branch": self.max_per_branch,
            "selection": self.selection,
            "rationale": self.rationale,
        }


OPERATOR_CLUSTERS: tuple[OperatorCluster, ...] = (
    OperatorCluster(
        "vector_reducer", ("vec_avg", "vec_sum"), 1, "alternative",
        "Trường VECTOR phải được giảm còn MATRIX; chọn phép gộp phù hợp ý nghĩa dữ liệu.",
    ),
    OperatorCluster(
        "missing_value_repair", ("ts_backfill", "group_backfill", "kth_element", "last_diff_value"), 1,
        "alternative", "Chỉ sửa thiếu dữ liệu khi mô tả trường cho thấy cần thiết; đặt trước tín hiệu chính.",
    ),
    OperatorCluster(
        "time_position", ("ts_rank", "ts_quantile", "ts_zscore", "ts_scale"), 1, "alternative",
        "Các phép đo vị trí tương đối của chuỗi thời gian; một nhánh thường chỉ cần một phép.",
    ),
    OperatorCluster(
        "time_change", ("ts_delta", "ts_av_diff", "ts_delay", "ts_step", "days_from_last_change"), 1,
        "alternative", "Các phép đo thay đổi/sự mới của chuỗi; chọn theo cơ chế kinh tế, không chồng bừa.",
    ),
    OperatorCluster(
        "time_smoothing", ("ts_mean", "ts_sum", "ts_product", "ts_decay_linear"), 1, "alternative",
        "Các phép làm trơn/tích lũy theo thời gian; dùng tối đa một trước phép xếp hạng thời gian.",
    ),
    OperatorCluster(
        "cross_section_rank", ("rank", "group_rank"), 1, "alternative",
        "Chọn xếp hạng toàn thị trường hoặc trong nhóm, tùy giả thuyết trung hòa ngành.",
    ),
    OperatorCluster(
        "cross_section_standardize", ("zscore", "group_zscore", "scale", "group_scale", "normalize"), 1,
        "alternative", "Các phép chuẩn hóa chéo thường thay thế nhau; tránh xếp chồng nếu không có lý do rõ.",
    ),
    OperatorCluster(
        "group_adjustment", ("group_neutralize", "group_mean"), 1, "alternative",
        "Các phép loại thành phần nhóm; dùng sau khi đã tạo tín hiệu, không dùng để thay thế cơ chế kinh tế.",
    ),
    OperatorCluster(
        "direction", ("reverse", "inverse", "sign"), 1, "alternative",
        "Điều chỉnh chiều tín hiệu; chỉ một phép cho mỗi nhánh, trừ kiểm tra dấu có chủ đích.",
    ),
    OperatorCluster(
        "turnover_control", ("hump", "ts_decay_linear"), 1, "alternative",
        "Giảm tốc thay đổi vị thế; ưu tiên đặt gần ngoài cùng của nhánh hay alpha hoàn chỉnh.",
    ),
)


# Các cạnh hướng từ thành phần *trong* ra thành phần *ngoài*.  Đây là quy tắc
# ưu tiên khi dựng cây biểu thức, không phải danh sách duy nhất hợp lệ của
# FASTEXPR.  Nhờ vậy mô hình ngôn ngữ có khung suy luận nhưng không bị ép vào
# một alpha duy nhất.
RECOMMENDED_EDGES: tuple[tuple[str, str, str], ...] = (
    ("field", "vector_reduce", "VECTOR phải được giảm trước các phép MATRIX."),
    ("field", "missing_data", "Sửa thiếu dữ liệu trước khi đo tín hiệu."),
    ("vector_reduce", "missing_data", "Sau giảm VECTOR có thể sửa thiếu dữ liệu."),
    ("missing_data", "time_position", "Đo vị trí chuỗi sau khi đã xử lý thiếu dữ liệu."),
    ("missing_data", "time_change", "Đo thay đổi chuỗi sau khi đã xử lý thiếu dữ liệu."),
    ("missing_data", "time_smoothing", "Làm trơn sau khi đã xử lý thiếu dữ liệu."),
    ("time_smoothing", "time_position", "Làm trơn rồi mới xếp hạng theo lịch sử là một cấu trúc có ý nghĩa."),
    ("time_change", "time_smoothing", "Có thể làm trơn thay đổi trước kiểm soát chéo."),
    ("time_position", "cross_section_rank", "Xếp hạng chéo sau khi có tín hiệu thời gian."),
    ("time_position", "group_control", "Kiểm soát nhóm sau khi có tín hiệu thời gian."),
    ("time_change", "cross_section_rank", "Kiểm soát chéo sau khi đo thay đổi."),
    ("time_smoothing", "cross_section_rank", "Kiểm soát chéo sau khi làm trơn."),
    ("arithmetic", "cross_section_rank", "Ghép hai nhánh độc lập rồi kiểm soát chéo."),
    ("arithmetic", "cross_section_standardize", "Ghép hai nhánh độc lập rồi chuẩn hóa đầu ra."),
    ("cross_section_rank", "direction", "Đảo chiều sau xếp hạng nếu cơ chế dự báo trái dấu."),
    ("group_control", "direction", "Đảo chiều sau kiểm soát nhóm nếu cần."),
    ("cross_section_rank", "turnover_control", "Hạn chế thay đổi vị thế ở gần đầu ra."),
    ("group_control", "turnover_control", "Hạn chế thay đổi vị thế ở gần đầu ra."),
    ("direction", "turnover_control", "Đảo chiều trước khi hạn chế thay đổi vị thế."),
    ("turnover_control", "cross_section_standardize", "Chuẩn hóa cuối cùng khi cần giới hạn độ lớn vị thế."),
)


@dataclass(frozen=True)
class OperatorProfile:
    name: str
    roles: tuple[str, ...]
    category: str
    signature: str
    supported_by_dsl: bool
    hard_requirements: tuple[str, ...]
    cluster_ids: tuple[str, ...]
    minimum_args: int | None
    maximum_args: int | None
    allowed_kwargs: tuple[str, ...]
    group_positions: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "roles": list(self.roles),
            "category": self.category,
            "signature": self.signature,
            "supported_by_dsl": self.supported_by_dsl,
            "hard_requirements": list(self.hard_requirements),
            "clusters": list(self.cluster_ids),
            "argument_contract": {
                "minimum_args": self.minimum_args,
                "maximum_args": self.maximum_args,
                "allowed_kwargs": list(self.allowed_kwargs),
                "group_positions": [position + 1 for position in self.group_positions],
            },
        }


def _as_mapping(item: object) -> Mapping[str, Any]:
    """Chấp nhận dict, sqlite3.Row, hay đối tượng có ``keys`` mà không cần import sqlite3."""

    if isinstance(item, Mapping):
        return item
    keys = getattr(item, "keys", None)
    if callable(keys):
        return {str(key): item[key] for key in keys()}
    raise TypeError("Mỗi mục danh mục phải là mapping hoặc sqlite3.Row")


def _catalog_index(catalog_operators: Iterable[object] | None) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in catalog_operators or ():
        row = _as_mapping(item)
        name = str(row.get("name") or "").strip().lower()
        if not name:
            continue
        # Bản ghi tải từ BRAIN giàu thông tin hơn bản typed_registry nội bộ.
        current = indexed.get(name)
        score = 0 if str(row.get("category") or "").lower() == "typed_registry" else 1
        current_score = -1
        if current is not None:
            current_score = 0 if str(current.get("category") or "").lower() == "typed_registry" else 1
        if score >= current_score:
            indexed[name] = row
    return indexed


def _roles_for(name: str) -> tuple[str, ...]:
    return tuple(role for role, names in ROLE_MEMBERS.items() if name in names)


def _clusters_for(name: str) -> tuple[str, ...]:
    return tuple(cluster.id for cluster in OPERATOR_CLUSTERS if name in cluster.members)


def _fallback_signature(name: str) -> str:
    spec = SPECS[name]
    maximum = "n" if spec.maximum_args == 99 else str(spec.maximum_args)
    return f"{name}({spec.minimum_args}..{maximum})"


def _hard_requirements(name: str) -> tuple[str, ...]:
    spec = SPECS[name]
    requirements: list[str] = []
    for position in spec.group_positions:
        requirements.append(f"Đối số vị trí {position + 1} phải là GROUP.")
    if name in ROLE_MEMBERS["vector_reduce"]:
        requirements.append("Đầu vào có thể là VECTOR; đầu ra là MATRIX.")
    if name in {"trade_when", "if_else"}:
        requirements.append("Đối số đầu tiên phải là điều kiện BOOLEAN hoặc tín hiệu kích hoạt 0/1.")
    if name in {"ts_corr", "ts_covariance", "ts_regression"}:
        requirements.append("Hai đối số đầu là MATRIX; đối số cửa sổ là SCALAR.")
    if name in {"rank", "zscore", "normalize", "scale", "winsorize", "quantile"}:
        requirements.append("Đầu vào phải là MATRIX, không phải VECTOR chưa giảm.")
    return tuple(requirements)


def build_operator_profiles(
    catalog_operators: Iterable[object] | None = None,
    *,
    include_unsupported: bool = False,
) -> dict[str, OperatorProfile]:
    """Ghép registry DSL với danh mục toán tử đã tải về.

    ``catalog_operators`` là một iterable chứa các mapping có khóa ``name``,
    ``category`` và ``signature`` (các khóa khác được bỏ qua).  Không có truy
    vấn cơ sở dữ liệu trong hàm này; caller có thể truyền các ``sqlite3.Row``
    đã đọc sẵn nếu muốn.
    """

    catalog = _catalog_index(catalog_operators)
    names = set(SPECS)
    if include_unsupported:
        names.update(catalog)
    profiles: dict[str, OperatorProfile] = {}
    for name in sorted(names):
        row = catalog.get(name, {})
        supported = name in SPECS
        category = str(row.get("category") or ("typed_registry" if supported else "catalog_only"))
        signature = str(row.get("signature") or (_fallback_signature(name) if supported else ""))
        profiles[name] = OperatorProfile(
            name=name,
            roles=_roles_for(name),
            category=category,
            signature=signature,
            supported_by_dsl=supported,
            hard_requirements=_hard_requirements(name) if supported else (),
            cluster_ids=_clusters_for(name),
            minimum_args=SPECS[name].minimum_args if supported else None,
            maximum_args=SPECS[name].maximum_args if supported else None,
            allowed_kwargs=tuple(sorted(SPECS[name].allowed_kwargs)) if supported else (),
            group_positions=SPECS[name].group_positions if supported else (),
        )
    return profiles


def operator_roles(name: str, catalog_operators: Iterable[object] | None = None) -> tuple[str, ...]:
    """Trả vai trò cấu trúc của một toán tử, với tên thường hóa về chữ thường."""

    return build_operator_profiles(catalog_operators, include_unsupported=True).get(
        name.strip().lower(), OperatorProfile("", (), "", "", False, (), (), None, None, (), ())
    ).roles


def catalog_field_types(catalog_fields: Iterable[object]) -> dict[str, str]:
    """Rút gọn danh mục trường thành ``{tên_trường: kiểu}`` cho kiểm tra cấu trúc.

    Chỉ giữ các kiểu mà DSL biết (MATRIX, VECTOR, GROUP, BOOLEAN, SCALAR);
    kiểu thiếu hoặc lạ trở thành UNKNOWN.  Hàm này không đọc cơ sở dữ liệu.
    """

    known = {"MATRIX", "VECTOR", "GROUP", "BOOLEAN", "SCALAR"}
    result: dict[str, str] = {}
    for item in catalog_fields:
        row = _as_mapping(item)
        name = str(row.get("name") or "").strip().lower()
        if not name:
            continue
        kind = str(row.get("data_type") or "UNKNOWN").upper()
        result[name] = kind if kind in known else "UNKNOWN"
    return result


def _available_names(available_operators: Iterable[object] | None) -> set[str]:
    if available_operators is None:
        return set(SPECS)
    names: set[str] = set()
    for item in available_operators:
        if isinstance(item, str):
            names.add(item.lower())
        else:
            row = _as_mapping(item)
            name = str(row.get("name") or "").strip().lower()
            if name:
                names.add(name)
    return names & set(SPECS)


def _slot(
    name: str,
    role: str,
    options: Iterable[str],
    available: set[str],
    *,
    minimum: int = 0,
    maximum: int = 1,
    cluster: str | None = None,
    rationale: str,
) -> dict[str, Any]:
    choices = [item for item in options if item in available]
    return {
        "name": name,
        "role": role,
        "operators": choices,
        "min_select": minimum,
        "max_select": maximum,
        "cluster": cluster,
        "rationale": rationale,
    }


def _path_available(path: dict[str, Any]) -> bool:
    return all(
        not (slot["min_select"] > 0 and len(slot["operators"]) < slot["min_select"])
        for slot in path["slots"]
    )


def compatible_paths(
    input_kind: str = "MATRIX",
    *,
    available_operators: Iterable[object] | None = None,
    include_conditional: bool = False,
) -> list[dict[str, Any]]:
    """Trả các khuôn đường đi hợp lý theo thứ tự từ trong ra ngoài.

    Đây là các khuôn xây alpha, không phải biểu thức cần mô phỏng.  Mỗi slot
    chứa các lựa chọn hợp lệ theo DSL và một giới hạn chọn.  Nếu caller truyền
    danh mục toán tử bị rút gọn, đường đi thiếu toán tử bắt buộc sẽ tự biến mất.
    """

    kind = input_kind.strip().upper()
    if kind not in {"MATRIX", "VECTOR"}:
        raise ValueError("input_kind phải là MATRIX hoặc VECTOR")
    available = _available_names(available_operators)
    temporal = ("ts_rank", "ts_zscore", "ts_quantile", "ts_delta", "ts_av_diff", "ts_mean", "ts_decay_linear")
    cross = ("group_rank", "group_zscore", "group_neutralize", "rank", "zscore")
    terminal = ("normalize", "hump")
    paths: list[dict[str, Any]] = []

    if kind == "MATRIX":
        paths.append({
            "id": "single_matrix_signal",
            "input_kind": "MATRIX",
            "ordered_roles": ["field", "missing_data?", "time_signal?", "cross_section", "direction?", "turnover_control?", "output_control?"],
            "slots": [
                _slot("repair", "missing_data", ("ts_backfill", "group_backfill"), available, cluster="missing_value_repair", rationale="Chỉ dùng khi trường có thiếu dữ liệu."),
                _slot("time_signal", "time", temporal, available, cluster=None, rationale="Chọn một cơ chế thời gian phù hợp giả thuyết."),
                _slot("cross_section", "cross_section", cross, available, minimum=1, cluster=None, rationale="Kiểm soát chéo hoặc theo nhóm cho tín hiệu."),
                _slot("direction", "direction", ("reverse",), available, cluster="direction", rationale="Chỉ đảo chiều nếu cơ chế dự báo yêu cầu."),
                _slot("turnover_control", "turnover_control", ("hump",), available, cluster="turnover_control", rationale="Dùng để kiểm tra giảm vòng quay, gần đầu ra."),
                _slot("output_control", "cross_section_standardize", ("normalize",), available, cluster="cross_section_standardize", rationale="Chuẩn hóa cuối alpha khi cần."),
            ],
            "independence_rule": "Một trường hoặc một cơ chế kinh tế rõ ràng; không dùng nhiều phép cùng cụm thay thế trong một nhánh.",
            "example_skeleton": "normalize(hump(reverse(group_rank(ts_rank(FIELD, WINDOW), GROUP)), hump=HUMP), useStd=true, limit=LIMIT)",
        })
        paths.append({
            "id": "two_branch_composite",
            "input_kind": "MATRIX",
            "ordered_roles": ["field_a/field_b", "branch_time?", "branch_cross_section?", "arithmetic_combine", "output_control"],
            "slots": [
                _slot("branch_time", "time", temporal, available, cluster=None, rationale="Mỗi nhánh chọn tối đa một cơ chế chính."),
                _slot("branch_cross_section", "cross_section", cross, available, cluster=None, rationale="Kiểm soát từng nhánh hoặc sau khi ghép, không làm cả hai nếu không có lý do."),
                _slot("combine", "arithmetic", ("add", "subtract"), available, minimum=1, cluster=None, rationale="Ghép tối đa hai nhánh độc lập bằng trọng số rõ ràng."),
                _slot("output_control", "cross_section_standardize", terminal, available, cluster=None, rationale="Hạn chế thay đổi vị thế và chuẩn hóa sau khi ghép."),
            ],
            "independence_rule": "Hai nhánh phải khác nguồn dữ liệu hoặc cơ chế; không tạo nhánh thứ hai chỉ bằng đổi cửa sổ của nhánh thứ nhất.",
            "example_skeleton": "normalize(add(multiply(W1, BRANCH_A), multiply(W2, BRANCH_B), filter=true), useStd=true, limit=LIMIT)",
        })
        paths.append({
            "id": "relative_two_field_signal",
            "input_kind": "MATRIX",
            "ordered_roles": ["field_a/field_b", "relative_arithmetic", "time_signal?", "cross_section", "output_control?"],
            "slots": [
                _slot("relative", "arithmetic", ("subtract", "divide"), available, minimum=1, cluster=None, rationale="So sánh hai đại lượng có cùng đơn vị hoặc cơ chế kinh tế liên quan."),
                _slot("time_signal", "time", temporal, available, cluster=None, rationale="Đo độ bền hay thay đổi của tín hiệu tương đối."),
                _slot("cross_section", "cross_section", cross, available, minimum=1, cluster=None, rationale="Kiểm soát chéo sau khi tạo tín hiệu tương đối."),
                _slot("output_control", "cross_section_standardize", terminal, available, cluster=None, rationale="Chuẩn hóa hoặc hạn chế vòng quay ở đầu ra."),
            ],
            "independence_rule": "Chỉ ghép trường có đơn vị phù hợp; divide không dùng khi mẫu số có thể gần 0 mà không có bảo vệ.",
            "example_skeleton": "normalize(group_rank(ts_rank(subtract(FIELD_A, FIELD_B), WINDOW), GROUP), useStd=true, limit=LIMIT)",
        })
    else:
        paths.append({
            "id": "vector_event_signal",
            "input_kind": "VECTOR",
            "ordered_roles": ["vector_field", "vector_reduce", "missing_data?", "time_signal?", "cross_section", "output_control?"],
            "slots": [
                _slot("reduce", "vector_reduce", ("vec_avg", "vec_sum"), available, minimum=1, cluster="vector_reducer", rationale="Bắt buộc giảm VECTOR về MATRIX trước mọi phép tiếp theo."),
                _slot("repair", "missing_data", ("ts_backfill", "group_backfill"), available, cluster="missing_value_repair", rationale="Chỉ dùng nếu dữ liệu sự kiện có thiếu."),
                _slot("time_signal", "time", temporal, available, cluster=None, rationale="Đo cường độ hoặc độ mới của sự kiện."),
                _slot("cross_section", "cross_section", cross, available, minimum=1, cluster=None, rationale="So sánh tín hiệu sự kiện giữa các mã hoặc trong ngành."),
                _slot("output_control", "cross_section_standardize", terminal, available, cluster=None, rationale="Chuẩn hóa đầu ra khi cần."),
            ],
            "independence_rule": "Không trộn trực tiếp VECTOR với MATRIX; sau vec_avg/vec_sum mới xét ghép nhánh.",
            "example_skeleton": "normalize(group_rank(ts_rank(vec_avg(VECTOR_FIELD), WINDOW), GROUP), useStd=true, limit=LIMIT)",
        })

    if include_conditional:
        paths.append({
            "id": "event_gated_signal",
            "input_kind": kind,
            "ordered_roles": ["condition", "base_signal", "conditional", "output_control?"],
            "slots": [
                _slot("condition", "logical", ("is_nan", "and", "or", "not"), available, minimum=1, cluster=None, rationale="Điều kiện phải có cơ chế sự kiện riêng, không lấy từ chính alpha rồi tự xác nhận."),
                _slot("gate", "conditional", ("trade_when", "if_else"), available, minimum=1, cluster=None, rationale="Dùng điều kiện để bật/tắt alpha đã có, không thay cơ chế chính."),
                _slot("output_control", "cross_section_standardize", terminal, available, cluster=None, rationale="Chuẩn hóa sau điều kiện nếu thích hợp."),
            ],
            "independence_rule": "Điều kiện và alpha nền phải dùng nguồn thông tin khác nhau để giảm tự tham chiếu.",
            "example_skeleton": "trade_when(CONDITION, BASE_SIGNAL, 0)",
        })

    return [path for path in paths if _path_available(path)]


def _kind(value: object) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "UNKNOWN").upper()
    return text if text in {"MATRIX", "VECTOR", "GROUP", "BOOLEAN", "SCALAR"} else "UNKNOWN"


@dataclass(frozen=True)
class _Inference:
    kind: str
    roles: frozenset[str]
    clusters: frozenset[str]


def _issue(severity: str, code: str, message: str, *, operator: str | None = None) -> dict[str, str]:
    payload = {"severity": severity, "code": code, "message": message}
    if operator:
        payload["operator"] = operator
    return payload


def _infer_structure(
    node: Node,
    field_types: Mapping[str, object],
    issues: list[dict[str, str]],
) -> _Inference:
    if isinstance(node, (Number, String)):
        return _Inference("SCALAR", frozenset(), frozenset())
    if isinstance(node, Identifier):
        name = node.name.lower()
        if name in GROUP_IDENTIFIERS:
            return _Inference("GROUP", frozenset({"field"}), frozenset())
        if name in {"true", "false"}:
            return _Inference("BOOLEAN", frozenset({"field"}), frozenset())
        if name in LITERALS:
            return _Inference("SCALAR", frozenset({"field"}), frozenset())
        return _Inference(_kind(field_types.get(name)), frozenset({"field"}), frozenset())
    if isinstance(node, Unary):
        return _infer_structure(node.operand, field_types, issues)
    if isinstance(node, Binary):
        left = _infer_structure(node.left, field_types, issues)
        right = _infer_structure(node.right, field_types, issues)
        if "VECTOR" in {left.kind, right.kind}:
            issues.append(_issue("error", "vector_requires_reduction", "VECTOR phải qua vec_avg hoặc vec_sum trước phép nhị phân."))
        kind = "BOOLEAN" if node.operator in {">", ">=", "<", "<=", "==", "!="} else (
            left.kind if left.kind != "SCALAR" else right.kind
        )
        return _Inference(kind, left.roles | right.roles | frozenset({"arithmetic"}), left.clusters | right.clusters)
    if not isinstance(node, Call):
        return _Inference("UNKNOWN", frozenset(), frozenset())

    name = node.name.lower()
    children = [_infer_structure(arg, field_types, issues) for arg in node.args]
    kwargs = [_infer_structure(value, field_types, issues) for _, value in node.kwargs]
    all_children = children + kwargs
    child_roles = frozenset().union(*(child.roles for child in all_children)) if all_children else frozenset()
    child_clusters = frozenset().union(*(child.clusters for child in all_children)) if all_children else frozenset()
    if name not in SPECS:
        issues.append(_issue("error", "unsupported_operator", f"Toán tử {name} không có trong DSL typed registry.", operator=name))
        return _Inference("UNKNOWN", child_roles, child_clusters)

    roles = frozenset(_roles_for(name))
    clusters = frozenset(_clusters_for(name))
    spec = SPECS[name]
    for position in spec.group_positions:
        if position >= len(children) or children[position].kind != "GROUP":
            issues.append(_issue("error", "group_argument_required", f"Đối số {position + 1} của {name} phải là GROUP.", operator=name))
    if name not in ROLE_MEMBERS["vector_reduce"] and any(child.kind == "VECTOR" for child in children):
        issues.append(_issue("error", "vector_requires_reduction", f"{name} nhận VECTOR trực tiếp; cần vec_avg hoặc vec_sum trước đó.", operator=name))
    if name in {"trade_when", "if_else"} and children and children[0].kind not in {"BOOLEAN", "UNKNOWN", "MATRIX"}:
        issues.append(_issue("warning", "condition_not_boolean", f"Điều kiện đầu của {name} nên là BOOLEAN hoặc tín hiệu 0/1.", operator=name))
    if name in {"ts_corr", "ts_covariance", "ts_regression"}:
        for position in (0, 1):
            if position < len(children) and children[position].kind not in {"MATRIX", "UNKNOWN"}:
                issues.append(_issue("error", "time_relation_requires_matrix", f"Đối số {position + 1} của {name} phải là MATRIX.", operator=name))

    for cluster in OPERATOR_CLUSTERS:
        if cluster.id in clusters and cluster.id in child_clusters and cluster.max_per_branch == 1:
            issues.append(_issue(
                "warning", "repeated_alternative_cluster",
                f"{name} xếp chồng với toán tử cùng cụm {cluster.id}; chỉ giữ khi đây là kiểm tra có chủ đích.",
                operator=name,
            ))
    if (roles & {"time_position", "time_change", "time_smoothing", "time_dispersion", "time_relation"}) and (
        child_roles & {"cross_section_rank", "cross_section_standardize", "group_control"}
    ):
        issues.append(_issue(
            "warning", "time_after_cross_section",
            f"{name} đang đặt ngoài kiểm soát chéo/nhóm; thường nên đo chuỗi thời gian trước rồi mới kiểm soát chéo.",
            operator=name,
        ))
    if "missing_data" in roles and child_roles & {
        "time_position", "time_change", "time_smoothing", "cross_section_rank", "cross_section_standardize", "group_control"
    }:
        issues.append(_issue(
            "warning", "repair_after_signal",
            f"{name} đang sửa thiếu dữ liệu sau khi đã tạo tín hiệu; thường nên đặt ở gần trường đầu vào.",
            operator=name,
        ))

    if name in ROLE_MEMBERS["vector_reduce"]:
        if children and children[0].kind == "MATRIX":
            issues.append(_issue("warning", "unnecessary_vector_reduction", f"{name} nhận MATRIX; chỉ dùng reducer cho VECTOR.", operator=name))
        result_kind = "MATRIX"
    elif name in {"and", "or", "not", "is_nan"}:
        result_kind = "BOOLEAN"
    elif name in {"if_else", "trade_when"} and len(children) >= 2:
        result_kind = children[1].kind
    elif name in {"bucket", "densify"}:
        result_kind = "GROUP" if name == "bucket" else (children[0].kind if children else "UNKNOWN")
    else:
        result_kind = next((child.kind for child in children if child.kind not in {"SCALAR", "BOOLEAN"}), children[0].kind if children else "UNKNOWN")
    return _Inference(result_kind, child_roles | roles, child_clusters | clusters)


def inspect_expression(
    expression: str,
    *,
    field_types: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Kiểm tra các ràng buộc và khuyến nghị của đồ thị cho một biểu thức.

    ``field_types`` có thể lấy từ :func:`catalog_field_types`.  Không truyền nó
    vẫn cho phép kiểm tra thứ tự toán tử, nhưng không thể phát hiện VECTOR dùng
    sai.  ``valid_structure`` chỉ phản ánh lỗi cứng của đồ thị, không thay thế
    ``validate_expression`` là bộ xác thực DSL đầy đủ.
    """

    try:
        root = parse(expression)
    except ParseError as exc:
        return {
            "valid_structure": False,
            "issues": [_issue("error", "parse_error", str(exc))],
            "operators": [],
            "root_kind": "UNKNOWN",
        }
    normalized_fields = {str(name).lower(): value for name, value in (field_types or {}).items()}
    issues: list[dict[str, str]] = []
    inferred = _infer_structure(root, normalized_fields, issues)
    operators = sorted({item.name.lower() for item in walk(root) if isinstance(item, Call)})
    return {
        "valid_structure": not any(issue["severity"] == "error" for issue in issues),
        "issues": issues,
        "operators": operators,
        "roles": sorted(inferred.roles),
        "root_kind": inferred.kind,
    }


def graph_payload(
    catalog_operators: Iterable[object] | None = None,
    *,
    compact: bool = True,
    operator_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Tạo payload JSON an toàn để đưa vào câu nhắc của tác tử nghiên cứu.

    Với ``compact=True`` (mặc định), chỉ phát hành toán tử được DSL hỗ trợ và
    các quy tắc cần để sinh biểu thức; không chèn mô tả dài của danh mục nên
    tiết kiệm dung lượng câu nhắc.  ``operator_names`` cho phép tác tử chỉ gửi
    một tập toán tử đã chọn theo giả thuyết vào mô hình ngôn ngữ.
    """

    # Materialize once so a caller may safely pass a generator of catalog rows.
    catalog_items = tuple(catalog_operators) if catalog_operators is not None else None
    available = _available_names(catalog_items) if catalog_items is not None else set(SPECS)
    if operator_names is not None:
        available &= {str(name).strip().lower() for name in operator_names}
    profiles = build_operator_profiles(catalog_items)
    profile_payload = [profiles[name].to_dict() for name in sorted(profiles) if name in available]
    clusters = [
        cluster.to_dict(available)
        for cluster in OPERATOR_CLUSTERS
        if any(name in available for name in cluster.members)
    ]
    paths = compatible_paths("MATRIX", available_operators=available) + compatible_paths(
        "VECTOR", available_operators=available
    )
    edges: list[dict[str, str]] = [
        {"from": source, "to": target, "reason": reason}
        for source, target, reason in RECOMMENDED_EDGES
    ]
    if compact:
        # Mặc định được nhúng vào prompt nên bỏ các câu giải thích lặp lại ở
        # từng toán tử.  Bản đầy đủ vẫn có sẵn cho tài liệu hoặc gỡ lỗi.
        profile_payload = [
            {
                "name": item["name"],
                "roles": item["roles"],
                "category": item["category"],
                "signature": item["signature"],
                "clusters": item["clusters"],
                "argument_contract": item["argument_contract"],
            }
            for item in profile_payload
        ]
        clusters = [
            {
                "id": item["id"],
                "members": item["members"],
                "max_per_branch": item["max_per_branch"],
                "selection": item["selection"],
            }
            for item in clusters
        ]
        edges = [{"from": item["from"], "to": item["to"]} for item in edges]
        paths = [
            {
                "id": path["id"],
                "input_kind": path["input_kind"],
                "ordered_roles": path["ordered_roles"],
                "slots": [
                    {
                        key: slot[key]
                        for key in ("name", "role", "operators", "min_select", "max_select", "cluster")
                    }
                    for slot in path["slots"]
                ],
                "independence_rule": path["independence_rule"],
            }
            for path in paths
        ]
    payload: dict[str, Any] = {
        "version": "operator-graph-v1",
        "scope": "Tương thích cấu trúc, không phải tương quan PnL đã đo.",
        "operators": profile_payload,
        "clusters": clusters,
        "recommended_edges": edges,
        "hard_constraints": [
            "Chỉ dùng toán tử có supported_by_dsl=true.",
            "VECTOR phải qua vec_avg hoặc vec_sum trước phép chuỗi thời gian, chéo, nhóm hay số học.",
            "Các vị trí GROUP trong DSL phải nhận market, sector, industry, subindustry, country, exchange hoặc currency.",
            "Không coi các cụm alternative là bằng chứng tương quan PnL; phải đo bằng mô phỏng sau này.",
        ],
        "parameter_guidance": [
            "Cửa sổ của toán tử ts_* phải là số nguyên dương và xuất phát từ chân trời của giả thuyết, không quét hàng loạt để dò may mắn.",
            "Khi ghép hai nhánh bằng multiply/add, cố định tổng trọng số trước rồi chỉ thay một tham số trong mỗi phép kiểm tra độ nhạy.",
            "Chỉ dùng keyword nằm trong argument_contract.allowed_kwargs của toán tử tương ứng.",
        ],
        "paths": paths,
    }
    if not compact:
        payload["all_supported_operator_names"] = sorted(SPECS)
        payload["catalog_available_operator_names"] = sorted(available)
    return payload


__all__ = [
    "OPERATOR_CLUSTERS",
    "RECOMMENDED_EDGES",
    "OperatorCluster",
    "OperatorProfile",
    "build_operator_profiles",
    "catalog_field_types",
    "compatible_paths",
    "graph_payload",
    "inspect_expression",
    "operator_roles",
]
