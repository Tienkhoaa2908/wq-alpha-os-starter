# Trạng thái hiện tại

> Tệp này được tạo bởi `alpha-os snapshot`. Không chỉnh số liệu thủ công; hãy cập nhật từ SQLite rồi commit/push.

- Thời điểm: `2026-09-05T15:36:42.641759+00:00`
- Branch: `alpha-research-v2`
- Commit: `2df62e768dc83aea90c005a83f6c482d794b3e15`

## Danh mục và tri thức

- Dataset: **16**
- Field: **7642**; đã lập hồ sơ: **7642**
- BRAIN operator active: **66**; đã lập hồ sơ: **66**
- Path template: **14**

## Kho nghiên cứu

- Alpha artifact vật lý: **1281**
- Artifact đủ điều kiện tham gia nghiên cứu v2: **14**
- Legacy Gemini bị cách ly: **1267**
- Motif đang hoạt động: **14**; empirical context: **8**
- Hypothesis card: **0**; AlphaPlan: **0**

Legacy policy: giữ lại record cũ để truy vết, nhưng không cho chúng ảnh hưởng novelty, subtree frequency hay empirical memory của v2.

## Mô phỏng

- Tổng: **14**
- Trạng thái: `{"COMPLETE": 13, "ERROR": 1}`

## Alpha tốt nhất theo Sharpe hiện có

- Family: `value_cashflow_multihorizon`
- Sharpe: **1.43**; Fitness: **0.98**; Turnover: **0.028**
- Self-correlation: **0.9415**
- Annual: `{"min_sharpe": 0.59, "positive_sharpe_years": 5, "years": 5}`

```text
normalize(add(multiply(0.75, hump(reverse(group_rank(ts_rank(mdl177_2_deepvaluefactor_ttmcfp, 756), industry)), hump=0.01)), multiply(0.25, reverse(group_rank(ts_rank(mdl177_2_deepvaluefactor_ttmcfp, 252), industry))), filter=true), useStd=true, limit=3)
```

## Cổng tiếp theo

Audit chất lượng phân loại field và packet tác tử v2 trước khi tiêu thêm lượt mô phỏng BRAIN.

Nguồn chi tiết máy đọc được: `docs/generated/research_state.json`.
