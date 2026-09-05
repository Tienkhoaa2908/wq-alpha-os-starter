# Tổng quan dự án WQ Alpha OS

Đây là điểm đọc đầu tiên cho mọi phiên làm việc. Mục tiêu là xây một hệ thống nghiên cứu alpha có bằng chứng, tự động hóa được phần lặp lại nhưng vẫn giữ các cổng semantic, novelty và simulation rõ ràng.

## Nguyên tắc lõi

Luồng mặc định **không phụ thuộc LLM**:

```text
BRAIN catalogue
  -> active operator registry
  -> Field Profiler
  -> semantic Path Templates
  -> deterministic AlphaPlan
  -> deterministic FASTEXPR compiler
  -> DSL/type/semantic gates
  -> duplicate + motif novelty gates
  -> BRAIN simulation
  -> evidence
  -> empirical memory
  -> scheduler: STOP / REFINE / BRANCH
```

LLM chỉ là reviewer/proposer tùy chọn. Không để LLM viết FASTEXPR trực tiếp trong research v2.

## Nguồn sự thật

- `data/db/alpha_lab.sqlite`: trạng thái thực nghiệm cục bộ.
- `data/evidence/`: bằng chứng mô phỏng và phản hồi model cục bộ.
- `docs/TRANG_THAI_HIEN_TAI.md`: snapshot ngắn.
- `docs/generated/research_state.json`: snapshot máy đọc được.
- `docs/generated/field_semantic_audit.json`: audit Field Profiler.
- `docs/generated/autonomous_v2_run_status.json`: trạng thái breadth runner không LLM.
- `docs/generated/autonomous_v2_dry_run.json`: đúng batch deterministic đang chờ review.
- `AGENTS.md`: quy tắc điều phối bắt buộc.

## Trạng thái nền

- 16 dataset.
- 7.642 field.
- 66 BRAIN operator active duy nhất.
- 66 operator semantic profile.
- 7.642 field profile.
- 14 path template.
- 14 simulation lịch sử, 13 hoàn tất.
- Alpha tốt nhất lịch sử: Sharpe 1.43, Fitness 0.98, turnover 0.028, self-correlation 0.9415.
- 1.267 artifact Gemini cũ giữ để truy vết nhưng đã bị cách ly khỏi research memory.

Số liệu hiện hành phải đọc từ `docs/generated/research_state.json`, không sửa tay trong file này.

## Trạng thái artifact bị loại

Hai status không được ảnh hưởng research memory:

- `legacy_unverified`: output hàng loạt từ Gemini cũ;
- `screened_out`: candidate local bị loại trước khi có BRAIN evidence.

Cả hai chỉ giữ provenance và bị loại khỏi:

- exact/near duplicate gate;
- motif novelty;
- subtree frequency;
- empirical motif memory.

## Autonomous semantic search

Nguồn chính: `src/wq_alpha_os/research/autonomous_search.py`.

Breadth stage đầu tiên chỉ dùng single-field candidate để tránh nổ không gian pair search. Candidate phải đi qua:

```text
profile confidence >= 0.70
+ non-generic MATRIX/VECTOR
+ mô tả tồn tại
+ lexical semantic consistency
+ eligible path hard gates
+ deterministic compiler
+ validation
+ anti-clone
```

Batch cuối phải có đúng 6 candidate và đủ breadth thật sự:

- >= 5 economic themes;
- >= 5 datasets;
- >= 4 path templates;
- tối đa 2 candidate dùng cùng một template;
- field không lặp.

### Audit breadth v1 ngày 2026-09-05

Runner v1 chạy thành công về mặt kỹ thuật: 409 candidate trong pool, 6 candidate được lưu, 6 theme và 6 dataset, không gọi network hay BRAIN simulation.

Tuy nhiên batch **không được phép simulation** vì chỉ dùng 3 template:

- `extremum_recency`: 3/6;
- `information_staleness`: 2/6;
- `risk_dispersion`: 1/6.

Audit còn phát hiện hai lỗi semantic đáng kể:

1. `mdl177_liquidityriskfactor_atmputvol_alt` được profile là `volume_liquidity`, nhưng marker `ATM put vol` là tín hiệu options/volatility rõ ràng;
2. `analyst_revision_rank_derivative` có cadence trung bình nhưng lại đi vào `information_staleness`, trong khi `days_from_last_change` chỉ có ý nghĩa khi unchanged-state phản ánh chu kỳ cập nhật chậm/sự kiện.

Vì vậy v1 được xem là **screened out before simulation**. Không tiêu BRAIN simulation cho batch đó.

### Search v2 sau audit

Search v2 đã thêm:

- hard gate: `information_staleness` chỉ nhận cadence `slow/event` hoặc sparsity tương ứng;
- lexical contradiction gate cho marker options-volatility rõ ràng;
- template diversity reward;
- tối đa 2 candidate/template;
- yêu cầu >= 4 template/6 candidate;
- khi rerun, batch autonomous cũ chưa simulate được chuyển sang `screened_out` trước khi batch thay thế được sinh;
- exact hash của candidate screened có thể được tái kích hoạt an toàn nếu selector mới vẫn chọn đúng candidate đó.

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

`multi_horizon_consensus` là robustness/sensitivity, không được tính là semantic novelty.

## Field Profiler

Mỗi field có tối thiểu:

- economic theme;
- semantic form;
- update cadence;
- signedness/domain;
- unit family;
- sparsity;
- peer dependence;
- direction prior;
- horizon prior;
- preferred/discouraged roles;
- confidence.

Profiler là prior, không phải chân lý. Candidate search phải có hard gate độc lập để bắt những mâu thuẫn lexical-semantic rõ ràng.

## Anti-clone

Mỗi artifact có nhiều fingerprint:

- exact;
- structural;
- role motif;
- semantic;
- parameter-normalized;
- subtree.

Đổi window/hằng số trên cùng field và cùng motif không được coi là ý tưởng mới, trừ controlled diagnostic/sensitivity có lineage rõ.

## Empirical memory và scheduler

Không học kiểu “operator X tốt”. Evidence phải gắn với context:

```text
field theme + semantic form + motif/path + horizon + settings
-> Sharpe / Fitness / turnover / self-correlation / annual stability / pass rate
```

Alpha tốt nhất hiện tại có self-correlation 0.9415 nên phải route `BRANCH_SEMANTIC`, tức đổi field hoặc economic mechanism; không cứu bằng micro-tuning window.

Research cycle chuẩn:

- 6 breadth simulations;
- sau khi có evidence mới chọn 3 targeted refinement;
- 3 diversity/robustness branch.

Không quyết định 6 slot sau trước khi breadth evidence tồn tại.

## Optional free-model stack

LLM free chỉ là lớp phụ. Có thể dùng Groq/OpenRouter qua `providers/free_stack.py`; nếu quota/model provider lỗi thì deterministic search vẫn chạy độc lập.

## Workflow phối hợp ChatGPT web với local code

ChatGPT web đóng vai trò supervisor/auditor qua GitHub. Local code chịu trách nhiệm vòng lặp tự động.

Sau thay đổi có ý nghĩa, dùng:

```powershell
.\scripts\finalize_task.ps1 -Message "<commit message>"
```

Runner autonomous dùng:

```powershell
.\scripts\run_autonomous_v2_discovery.ps1
```

## Cổng hiện tại

1. Pull `alpha-research-v2`.
2. Chạy lại autonomous breadth v2.
3. Batch cũ chưa simulation phải tự chuyển sang `screened_out`.
4. Audit `autonomous_v2_dry_run.json` mới: đúng 6 candidate, >=5 theme, >=5 dataset, >=4 template, không có semantic contradiction rõ ràng.
5. Chỉ khi gate này đạt mới mở 6 BRAIN simulations breadth đầu tiên.
