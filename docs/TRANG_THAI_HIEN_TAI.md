# Trạng thái hiện tại

> Snapshot phối hợp tạm thời từ lần chạy cục bộ gần nhất. Sau khi pull branch mới, chạy `scripts/finalize_task.ps1` để tệp này được tạo lại trực tiếp từ SQLite.

- Branch làm việc: `alpha-research-v2`
- Test cục bộ gần nhất: **47/47 đạt**.
- Knowledge build cục bộ gần nhất trước khi áp dụng legacy quarantine:
  - 66/66 operator đã có semantic profile;
  - 7.642/7.642 field đã có field profile;
  - 14 path template;
  - 1.281 motif đã từng được materialize;
  - 13 simulation hoàn tất tạo 8 empirical context.

## Catalog

- Dataset: **16**
- Field: **7.642**
- BRAIN operator active duy nhất: **66**

## Artifact

- Tổng artifact vật lý trong SQLite: **1.281**
- `legacy_unverified`: **1.267**
- `tested`: **13**
- `validated`: **1**

1.267 `legacy_unverified` là output hàng loạt của generator Gemini cũ và không được xem là research evidence v2.

Code hiện tại trên branch đã đổi policy thành:

```text
legacy_unverified
→ giữ record để truy vết
→ loại khỏi novelty
→ loại khỏi subtree frequency
→ loại khỏi empirical motif memory
→ không dùng cho scheduler/trial evidence
```

Sau khi máy cục bộ pull branch mới và chạy lại `alpha-os knowledge build`, motif memory phải được rebuild chỉ từ artifact nghiên cứu hợp lệ. Với trạng thái hiện tại, kỳ vọng khoảng **14 artifact** được materialize thay vì 1.281; con số chính xác phải lấy từ lần chạy cục bộ sau pull.

## Simulation

- Đã gửi: **14**
- Hoàn tất: **13**
- Lỗi: **1**
- Promoted: **0**

## Alpha tốt nhất lịch sử

- Family: `value_cashflow_multihorizon`
- Sharpe: **1.43**
- Fitness: **0.98**
- Turnover: **0.028**
- Self-correlation: **0.9415**

Kết luận nghiên cứu: core signal có sức mạnh nhưng diversity quá thấp. Scheduler v2 phải `BRANCH_SEMANTIC`, không tiếp tục đổi window/weight lân cận.

## Tiến độ research v2

Đã có:

- active BRAIN operator registry;
- Operator Knowledge Base cho 66 operator;
- Field Profiler cho 7.642 field;
- 14 path template;
- AlphaPlan + deterministic compiler;
- semantic validator;
- exact/structural/motif/semantic/parameter/subtree fingerprints;
- empirical motif memory;
- scheduler theo failure mode;
- multi-objective scoring;
- state snapshot exporter;
- `scripts/finalize_task.ps1` để test → rebuild → snapshot → commit → push.

## Cổng tiếp theo

1. Pull branch `alpha-research-v2` mới nhất.
2. Chạy lại test.
3. Chạy `alpha-os knowledge build` để loại 1.267 legacy khỏi motif memory.
4. Chạy `scripts/finalize_task.ps1` để snapshot sạch được push lên GitHub.
5. Audit phân phối semantic của 7.642 field và `agent packet --count 6`.
6. Chưa simulate batch mới cho tới khi audit trên đạt.
