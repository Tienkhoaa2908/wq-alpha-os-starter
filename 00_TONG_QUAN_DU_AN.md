# Tổng quan dự án WQ Alpha OS

Đây là điểm đọc đầu tiên cho mọi phiên làm việc. Mục tiêu là giúp ChatGPT/Codex hiểu đúng dự án mà không phải audit toàn repo.

## Mục tiêu

Xây một hệ thống nghiên cứu alpha có bằng chứng, trong đó LLM chỉ làm phần giả thuyết và lựa chọn ý định nghiên cứu; code cục bộ chịu trách nhiệm biên dịch biểu thức, kiểm tra kiểu/ngữ nghĩa, chống clone, mô phỏng, lưu bằng chứng và học từ kết quả.

Không dùng mô hình cục bộ để sinh alpha. Không để LLM viết FASTEXPR trực tiếp trong luồng v2.

## Nguồn sự thật

- `data/db/alpha_lab.sqlite`: trạng thái thực nghiệm cục bộ.
- `data/evidence/`: bằng chứng mô phỏng và phản hồi model cục bộ.
- `docs/TRANG_THAI_HIEN_TAI.md`: snapshot ngắn cho người đọc.
- `docs/generated/research_state.json`: snapshot máy đọc được để ChatGPT/Codex đọc trực tiếp trên GitHub.
- `AGENTS.md`: quy tắc vận hành bắt buộc.

Sau mỗi thay đổi có ý nghĩa phải chạy `scripts/finalize_task.ps1` để test, rebuild knowledge, cập nhật snapshot, commit và push GitHub.

## Trạng thái nền hiện biết

- 16 dataset.
- 7.642 field.
- 66 BRAIN operator active duy nhất.
- 66 operator semantic profile.
- 7.642 field profile.
- 14 path template.
- 14 simulation lịch sử, 13 hoàn tất.
- 0 alpha promoted.
- Alpha tốt nhất lịch sử: Sharpe 1.43, Fitness 0.98, turnover 0.028, self-correlation 0.9415.

Chi tiết hiện hành phải đọc từ `docs/TRANG_THAI_HIEN_TAI.md` vì file này chỉ giữ bức tranh kiến trúc lâu dài.

## Chính sách đối với 1.267 alpha Gemini cũ

Các artifact có status `legacy_unverified` là đầu ra hàng loạt từ generator Gemini cũ. Chúng không được xem là 1.267 ý tưởng nghiên cứu hợp lệ.

Chính sách v2:

- giữ record trong SQLite để truy vết nguồn gốc;
- không đưa vào novelty score;
- không đưa vào subtree frequency;
- không đưa vào empirical motif stats;
- không dùng làm trial count hoặc scheduler evidence;
- không dùng để chặn alpha mới chỉ vì giống output rác cũ.

`alpha-os knowledge build` phải rebuild motif memory chỉ từ artifact nghiên cứu hợp lệ.

## Kiến trúc research v2

```text
BRAIN catalogue
      │
      ├── active operator registry
      │       ↓
      │   Operator Knowledge Base
      │
      └── field catalogue
              ↓
          Field Profiler
              │
              ▼
        Hypothesis LLM
              │
              ▼
           AlphaPlan
              │
              ▼
      semantic path planner
              │
              ▼
      deterministic compiler
              │
      ┌───────┴────────┐
      ▼                ▼
 DSL/type gates   semantic gates
      └───────┬────────┘
              ▼
       novelty/clone gate
              │
              ▼
          simulation
              │
              ▼
           evidence
              │
              ▼
      empirical motif memory
              │
              ▼
         scheduler v2
       STOP / REFINE / BRANCH
```

## Operator Knowledge Base

66 operator active được phân theo vai trò semantic chứ không chỉ category BRAIN.

Các phân biệt bắt buộc:

- `hump` ≠ `ts_decay_linear`;
- `reverse` ≠ `inverse` ≠ `sign`;
- `winsorize` ≠ `zscore`;
- `group_mean` ≠ `group_neutralize`;
- `ts_sum` ≠ `ts_mean`;
- `ts_arg_max/min` là timing, không phải dispersion;
- `ts_count_nans` là missingness/coverage feature;
- `ts_delay` là lag/anchor, không phải change operator.

## Field Profiler

Mỗi field được mô tả ít nhất theo:

- economic theme;
- semantic form;
- update cadence;
- signedness/domain;
- unit family;
- sparsity;
- peer dependence;
- direction prior;
- horizon prior;
- preferred/discouraged operator roles;
- confidence.

Field semantics quyết định grammar. VECTOR không được đi thẳng vào time-series operator nếu chưa reduce.

## 14 path template

1. `slow_level_peer`
2. `slow_change_peer`
3. `relative_ratio`
4. `vector_event_intensity`
5. `vector_event_novelty`
6. `extremum_recency`
7. `information_staleness`
8. `two_series_correlation`
9. `regression_residual`
10. `risk_dispersion`
11. `peer_residual`
12. `state_gated_core`
13. `multi_horizon_consensus`
14. `orthogonal_confirmation`

`multi_horizon_consensus` là robustness/sensitivity, không được tính là novelty.

## Anti-clone v2

Mỗi artifact có nhiều fingerprint:

- exact;
- structural;
- role motif;
- semantic;
- parameter-normalized;
- subtree.

Thay window trên cùng field/cùng motif không được coi là ý tưởng mới, trừ controlled diagnostic/sensitivity có lineage rõ.

## Empirical memory

Không học câu kiểu “`ts_rank` tốt”. Hệ thống học theo context:

```text
field theme
+ semantic form
+ motif/path
+ horizon bucket
+ settings
→ Sharpe / Fitness / turnover / self-correlation / annual stability / pass rate
```

Chỉ simulation hoàn tất và artifact hợp lệ mới được dùng làm bằng chứng.

## Scheduler v2

Scheduler phải chẩn đoán failure mode trước khi sinh child.

Ví dụ alpha hiện tại Sharpe 1.43, Fitness 0.98, corr 0.9415 phải đi vào:

```text
BRANCH_SEMANTIC
```

Tức đổi field hoặc economic mechanism, không đổi 756 thành một window lân cận.

Một research cycle chuẩn có budget 12:

- 6 hypothesis mới;
- 3 targeted refinement;
- 3 diversity/robustness branch.

## Workflow phối hợp ChatGPT ↔ Codex

ChatGPT web dùng GitHub làm nguồn trạng thái chung. Codex trong VS Code có quyền đọc SQLite/evidence cục bộ và sau mỗi task phải đưa phần trạng thái an toàn lên GitHub.

Kết thúc task bằng:

```powershell
.\scripts\finalize_task.ps1 -Message "<commit message>"
```

Không được coi task là xong nếu chưa cập nhật `docs/TRANG_THAI_HIEN_TAI.md`, `docs/generated/research_state.json`, commit và push branch hiện tại.

## Cổng tiếp theo

Trước khi tiêu simulation mới:

1. rebuild knowledge sau khi cách ly 1.267 legacy artifact;
2. kiểm tra motif active chỉ còn artifact nghiên cứu thật;
3. audit chất lượng phân loại 7.642 field;
4. đọc `alpha-os agent packet --count 6` và kiểm tra field/path diversity;
5. chỉ khi packet hợp lý mới cho Gemini tạo hypothesis card;
6. dry-run AlphaPlan trước;
7. sau đó mới tiêu batch 12 simulation đầu tiên của v2.
