# Tổng quan dự án WQ Alpha OS

Đây là điểm đọc đầu tiên cho mọi phiên làm việc. Mục tiêu là giúp ChatGPT/Codex hiểu đúng dự án mà không phải audit toàn repo.

## Mục tiêu

Xây một hệ thống nghiên cứu alpha có bằng chứng, trong đó code cục bộ chịu trách nhiệm cho phần lặp lại và quyết định có thể kiểm chứng: chọn field theo semantic profile, chọn path template, biên dịch biểu thức, kiểm tra kiểu/ngữ nghĩa, chống clone, mô phỏng, lưu bằng chứng và học từ kết quả.

LLM không còn là dependency bắt buộc. Luồng ưu tiên mới là **deterministic semantic search**: Field Profiler + Path Template + AlphaPlan compiler có thể tự sinh một breadth batch hợp lệ mà không gọi API. LLM chỉ là lớp reviewer/proposer tùy chọn ở phía trên, tuyệt đối không viết FASTEXPR trực tiếp.

## Nguồn sự thật

- `data/db/alpha_lab.sqlite`: trạng thái thực nghiệm cục bộ.
- `data/evidence/`: bằng chứng mô phỏng và phản hồi model cục bộ.
- `docs/TRANG_THAI_HIEN_TAI.md`: snapshot ngắn cho người đọc.
- `docs/generated/research_state.json`: snapshot máy đọc được để ChatGPT/Codex đọc trực tiếp trên GitHub.
- `docs/generated/field_semantic_audit.json`: phân phối/chất lượng Field Profiler đã được rút gọn an toàn.
- `docs/generated/agent_packet_preview.json`: packet cho nhánh LLM tùy chọn.
- `docs/generated/autonomous_v2_run_status.json`: trạng thái runner deterministic không LLM.
- `docs/generated/autonomous_v2_dry_run.json`: audit 6 AlphaPlan deterministic khi runner thành công.
- `docs/generated/first_v2_run_status.json`: trạng thái nhánh LLM cũ/tùy chọn.
- `AGENTS.md`: quy tắc vận hành bắt buộc.

Sau mỗi thay đổi có ý nghĩa phải chạy `scripts/finalize_task.ps1` để test, xuất audit + snapshot, commit và push GitHub.

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
- 1.267 artifact Gemini cũ đã được cách ly khỏi research memory; motif active hiện chỉ còn artifact nghiên cứu hợp lệ.

Chi tiết hiện hành phải đọc từ `docs/TRANG_THAI_HIEN_TAI.md` vì file này chỉ giữ bức tranh kiến trúc lâu dài.

## Chính sách đối với 1.267 alpha Gemini cũ

Các artifact có status `legacy_unverified` là đầu ra hàng loạt từ generator Gemini cũ. Chúng không được xem là 1.267 ý tưởng nghiên cứu hợp lệ.

Chính sách v2:

- giữ record trong SQLite để truy vết nguồn gốc;
- không đưa vào novelty score;
- không đưa vào subtree frequency;
- không đưa vào empirical motif stats;
- không dùng làm trial count hoặc scheduler evidence;
- không dùng trong exact/near-duplicate gate;
- không dùng để chặn alpha mới chỉ vì giống output rác cũ.

`alpha-os knowledge build` rebuild motif memory chỉ từ artifact nghiên cứu hợp lệ.

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
   deterministic semantic search
              │
              ├──────── optional LLM reviewer/proposer
              │
              ▼
           AlphaPlan
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

## Autonomous semantic search

Nguồn chính nằm ở `research/autonomous_search.py`.

Breadth stage đầu tiên:

- chỉ dùng field `MATRIX`/`VECTOR` đã có profile confidence >= 0.70;
- bỏ `generic`, infrastructure và field đã dùng ở artifact nghiên cứu hiện hành;
- chỉ lấy path template semantic-eligible;
- breadth đầu tiên chỉ dùng single-field motif, không random pair;
- loại `multi_horizon_consensus` khỏi novelty breadth;
- compile FASTEXPR bằng `plans.py`;
- chấm prior bằng confidence + coverage + motif novelty;
- chọn đúng 6 candidate với tối thiểu 5 theme và 5 dataset;
- chạy toàn bộ DSL/type/semantic/clone gates trước khi lưu;
- không gọi LLM, không gọi BRAIN simulation.

Một lệnh local:

```powershell
.\scripts\run_autonomous_v2_discovery.ps1
```

Runner phải sinh `autonomous_v2_run_status.json`; nếu thành công còn sinh `autonomous_v2_dry_run.json` rồi tự finalize/push GitHub.

## Optional free-model stack

LLM là lớp tùy chọn, không phải lõi. `providers/free_stack.py` thử các key có sẵn theo thứ tự:

1. Groq: `openai/gpt-oss-120b`, sau đó `qwen/qwen3.8-27b`;
2. OpenRouter: `inclusionai/ling-3.0-flash-fin:free`, `minimax/minimax-m2.7:free`, rồi `nvidia/nemotron-3-ultra-550b-a55b:free`.

Đặt `ALPHA_LLM_PROVIDER=auto_free` và chỉ lưu `GROQ_API_KEY`/`OPENROUTER_API_KEY` trong `.env`. Nếu mọi API free chết/hết quota thì deterministic semantic search vẫn chạy được.

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

## Field Profiler v3

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

Field Profiler v3 ưu tiên bằng chứng từ tên và mô tả. Dataset và nhãn semantic cũ chỉ là prior yếu khi không có bằng chứng trực tiếp. Bộ phân loại dùng token/cụm từ thay cho substring rộng, mặc định direction là `ambiguous`, và xét dấu của change/delta/return/revision trước dấu hiệu không âm.

Taxonomy economic theme là một nguồn dùng chung cho profiler, field review, path template và knowledge card. Các kiểu hạ tầng `UNIVERSE`, `GROUP`, `SYMBOL` không được vào discovery hoặc review.

Candidate packet v3 chỉ nhận `MATRIX`/`VECTOR`, loại `generic` và confidence dưới `0.70`, giữ mô tả tối đa 220 ký tự, áp trần 25% cho mỗi dataset và mỗi theme. Với 6 hypothesis, mục tiêu là 24 field và ít nhất 6 dataset khi catalogue cho phép.

Field Profiler chưa được coi là đáng tin chỉ vì đã materialize đủ 7.642 dòng. Trước simulation mới phải đọc `field_semantic_audit.json`, đặc biệt các mẫu có rủi ro phân loại sai và các field coverage cao nhưng semantic mơ hồ.

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

Thay window trên cùng field/cùng motif không được coi là ý tưởng mới, trừ controlled diagnostic/sensitivity có lineage rõ. `legacy_unverified` bị loại khỏi tất cả duplicate/novelty gates của research v2.

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

BRAIN yearly recordset phải được giải mã từ `schema + records[value=list]` một cách thống nhất trước khi dùng cho annual stability. Parser dùng chung nằm ở `research/recordsets.py`; snapshot, empirical memory và scheduler không được tự viết parser riêng lệch nhau.

## Scheduler v2

Scheduler phải chẩn đoán failure mode trước khi sinh child.

Ví dụ alpha hiện tại Sharpe 1.43, Fitness 0.98, corr 0.9415 phải đi vào:

```text
BRANCH_SEMANTIC
```

Tức đổi field hoặc economic mechanism, không đổi 756 thành một window lân cận.

Một research cycle chuẩn có budget 12:

- 6 breadth candidate mới;
- 3 targeted refinement;
- 3 diversity/robustness branch.

6 slot sau chỉ được quyết định sau khi 6 breadth simulations đầu có evidence.

## Workflow phối hợp ChatGPT web ↔ local code

ChatGPT web dùng GitHub làm nguồn trạng thái chung và đóng vai trò supervisor/auditor. Không cố dùng ChatGPT web như một API cục bộ. Code local chịu trách nhiệm các vòng tự động.

Kết thúc task bằng:

```powershell
.\scripts\finalize_task.ps1 -Message "<commit message>"
```

Các runner tự động phải tạo file status/audit phù hợp rồi finalize để ChatGPT đọc được trên GitHub.

## Cổng tiếp theo

Ưu tiên nhánh deterministic, không chờ Gemini:

1. chạy `git pull origin alpha-research-v2`;
2. chạy `.\scripts\run_autonomous_v2_discovery.ps1`;
3. đọc `docs/generated/autonomous_v2_run_status.json`;
4. nếu thành công, audit đúng 6 candidate trong `autonomous_v2_dry_run.json`;
5. chỉ sau audit mới cho phép 6 BRAIN simulations breadth đầu tiên;
6. từ 6 kết quả đó mới phân bổ 3 refinement + 3 diversity/robustness.

Free LLM stack chỉ dùng như reviewer/reranker tùy chọn; nếu quota/model provider lỗi thì không được làm gián đoạn deterministic search.
