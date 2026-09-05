# Nhiệm vụ kế tiếp: hiệu chuẩn research v2 trước Gemini/simulation

Đọc `AGENTS.md`, `00_TONG_QUAN_DU_AN.md`, `docs/TRANG_THAI_HIEN_TAI.md`, `docs/generated/field_semantic_audit.json`, `docs/generated/agent_packet_preview.json` trước.

## Kết luận audit hiện tại

Research v2 CHƯA được phép gọi Gemini discovery hoặc tiêu simulation mới.

Snapshot mới nhất đã xác nhận:

- 1.267 `legacy_unverified` đã bị cách ly; chỉ 14 artifact nghiên cứu tham gia motif memory.
- yearly parser đã phục hồi đúng alpha tốt nhất: 5 năm, 5 năm Sharpe dương, min Sharpe 0.59.
- 7.642 field đã có profile, nhưng chất lượng semantic chưa đạt cổng.
- packet hiện có 36 field nhưng 29/36 đến từ `Analysts' Factor Model`, 5 từ `Options Analytics`, 2 từ `US News Data`; diversity theo dataset chưa đạt.
- `cycle_plan` hiện trả `diversity_parents=[]` dù alpha tốt nhất có Sharpe 1.43, Fitness 0.98, self-corr 0.9415; scheduler routing đang sai so với policy `BRANCH_SEMANTIC`.
- `family_trial_stats` snapshot vẫn có `effective_trial_count=0` cho các family đã có simulation; trial-burden memory chưa materialize đúng.

Các ví dụ misclassification quan sát trực tiếp trong packet/audit:

- `mdl77_opricemomentumfactor_normalmf60d` bị gán `analyst_revision/flow` dù tên cho thấy price momentum/model factor.
- `mdl77_liquidityriskfactor_monchgsip` bị gán `growth/slow` dù tên cho thấy liquidity-risk/change.
- `previous_day_open_close_change_pct_all` bị gán `value/vector_count` dù tên là price change.
- `news_vol_stddev` bị gán `price/dispersion` dù ngữ nghĩa gần news-volume dispersion.
- `average_true_range_fourteen_periods` trong US News bị gán `sentiment_news/vector_event` chỉ vì dataset, dù ATR là price/risk measure.
- review candidates đang chứa `top3000`, `top500`, ... kiểu `UNIVERSE`; đây là metadata hạ tầng, không phải alpha field để gửi Gemini.

## Nguyên nhân kiến trúc cần sửa

1. `field_profiles.py` đang trộn `dataset_name` vào cùng text keyword với name/description; ví dụ từ `Analysts' Factor Model` làm nhiều field bị gán `analyst_revision` giả.
2. Keyword quá rộng như `vol` có thể đụng `volume`; substring matching gây false positive.
3. Legacy `semantic_theme` hiện có thể được ưu tiên quá mạnh thay vì chỉ là weak prior.
4. Direction prior đang mặc định negative cho toàn bộ `value`; điều này không an toàn vì earnings yield và P/E có polarity khác nhau.
5. `path_templates._matches()` hiện dùng `theme_ok OR form_ok`; semantic gate quá rộng. Khi template có cả preferred theme và form, mặc định phải yêu cầu cả hai phù hợp, trừ exception được ghi rõ.
6. `discovery_v2` diversify theo theme nhưng không giới hạn dataset, nên một dataset lớn/high-confidence chiếm packet.
7. Candidate packet chưa gửi description ngắn cho Gemini; với field cryptic, LLM không đủ dữ kiện để nêu cơ chế kinh tế.
8. `scheduler.diagnose_run()` early-return `DIAGNOSE_CHECK` trước khi metric/high-correlation routing, khiến LOW_FITNESS/LOW_SHARPE check che mất `BRANCH_SEMANTIC`.
9. Trial counters của historical research-eligible runs chưa rebuild vào `family_trial_stats`.
10. Theme taxonomy không thống nhất hoàn toàn (`earnings_dispersion` vs `earnings_surprise`) giữa profiler, reviewer, templates/knowledge.

## Nhiệm vụ triển khai

### A. Field Profiler v3

- Semantic matching chính dùng `name + description`; KHÔNG quét keyword trực tiếp trên `dataset_name`.
- Dataset chỉ là fallback prior có trọng số thấp khi name/description không đủ bằng chứng.
- Dùng token/phrase-aware rules; loại broad substring `vol` và các substring dễ false-positive.
- Legacy `semantic_theme` là weak prior, không override bằng chứng rõ từ name/description.
- Chuẩn hóa một taxonomy theme dùng chung cho profiler, field reviewer, path templates, knowledge templates.
- Direction mặc định `ambiguous`; chỉ gán positive/negative khi field semantics đủ rõ. Không gán negative cho toàn bộ `value`.
- Signedness phải xét change/delta/return/revision trước khi suy ra nonnegative từ `sales/assets/volume`.
- Infrastructure types `UNIVERSE`, `GROUP`, `SYMBOL` không được đi vào discovery/review candidate pool.

### B. Candidate packet v3

- Chỉ primary candidate `MATRIX` hoặc `VECTOR`.
- Mặc định exclude `generic` và profile confidence < 0.70 khỏi discovery; chúng có thể đi qua semantic review riêng.
- Dataset cap: không dataset nào chiếm quá 25% packet khi còn field hợp lệ từ dataset khác.
- Theme cap tương tự để tránh một theme chiếm packet.
- Với `count=6`, target packet khoảng 24 field thay vì 36 nếu vẫn đủ diversity.
- Cố gắng có >= 6 dataset khác nhau khi catalog hợp lệ cho phép; ưu tiên source diversity: analyst, fundamentals/scores, news/Ravenpack, options/volatility, relationship, price-volume/sentiment.
- Thêm `description` rút gọn (ví dụ <= 220 ký tự) vào mỗi candidate field; vẫn không gửi formula/operator.
- Giữ coverage, data_type, semantic profile, local_uses, alpha_count nếu hữu ích.
- Audit output phải báo dataset cap, theme cap và gate verdict.

### C. Field semantic review

- Không review `UNIVERSE/GROUP/SYMBOL`.
- Không batch-review hàng nghìn unknown-unit field chỉ vì unit unknown.
- Review ưu tiên: candidate discovery có semantic mơ hồ, high-coverage generic/low-confidence, hoặc field từ dataset chiến lược chưa phân loại tốt.
- Packet review phải có name, description, dataset, type, current profile.
- Chuẩn hóa taxonomy với Field Profiler v3.

### D. Path gate

- Sửa `_matches`: theme + form đều phải hợp khi template khai cả hai; exception phải explicit.
- Hai-field template phải kiểm tra compatibility của từng field và cặp field, không chỉ `any(_matches(...))`.
- Thêm regression tests chống semantic eligibility quá rộng.

### E. Scheduler + trial memory

- Phân biệt BRAIN checks:
  - metric-derived checks (`LOW_FITNESS`, `LOW_SHARPE`, `LOW_TURNOVER`, `LOW_SUB_UNIVERSE_SHARPE`, tương tự) KHÔNG được early-return trước metric diagnosis;
  - structural/platform checks thực sự mới có thể route `DIAGNOSE_CHECK` ưu tiên.
- Với alpha tốt nhất hiện tại Sharpe 1.43, Fitness 0.98, corr 0.9415, `diagnose_run()` bắt buộc trả `BRANCH_SEMANTIC`.
- `controlled_cycle_plan(12)` phải đưa alpha này vào `diversity_parents` nếu chưa stopped.
- Rebuild `family_trial_stats` từ research-eligible artifacts/simulations hiện có. Ít nhất family có 8 completed runs không được có `effective_trial_count=0`.
- Parameter-only/sensitivity trials phải tăng trial burden nhưng không tăng semantic novelty.

### F. Audit outputs

Cập nhật `scripts/export_field_semantic_audit.py` và `scripts/export_agent_packet_preview.py` để GitHub cho ChatGPT audit được mà không cần SQLite:

- field audit thêm top misclassification-risk samples theo dataset + description;
- packet audit thêm `gate_pass`, lý do fail/pass, dataset count, theme count, max dataset share, low-confidence count, generic count, infrastructure count;
- cycle-plan summary trong packet audit phải cho thấy diversity/refinement parent counts.

## Acceptance criteria

Không gọi Gemini, không gọi BRAIN simulation trong task này.

Task chỉ đạt khi:

1. toàn bộ unit tests pass;
2. best alpha fixture/routing test => `BRANCH_SEMANTIC`;
3. family trial counter fixture > 0 sau historical completed runs;
4. discovery packet không chứa UNIVERSE/GROUP/SYMBOL;
5. packet có description;
6. max dataset share <= 0.25 nếu >= 4 dataset hợp lệ tồn tại;
7. field reviewer không nhận infrastructure types;
8. path eligibility không còn OR quá rộng;
9. taxonomy theme thống nhất;
10. chạy trên SQLite thật bằng `finalize_task.ps1`, cập nhật bốn snapshot/audit và push GitHub.

Kết thúc bằng:

```powershell
.\scripts\finalize_task.ps1 -Message "refactor: calibrate field semantics packet diversity and scheduler"
```

Sau khi push chỉ báo commit SHA, test result, field audit quality, packet audit gate và cycle-plan parent counts. Không simulate/Gemini.
