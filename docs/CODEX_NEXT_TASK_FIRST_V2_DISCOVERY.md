# Nhiệm vụ kế tiếp: semantic adjudication + 6 hypothesis đầu tiên + AlphaPlan dry-run

Đọc `AGENTS.md`, `00_TONG_QUAN_DU_AN.md`, `docs/TRANG_THAI_HIEN_TAI.md`, `docs/generated/field_semantic_audit.json`, `docs/generated/agent_packet_preview.json` trước.

## Kết luận sau calibration commit `5aacada`

Cổng hạ tầng đã đạt để chuyển sang vòng khám phá đầu tiên, nhưng CHƯA được phép gửi simulation BRAIN trong task này.

Đã xác nhận:

- 67/67 test pass và CI xanh.
- 1.267 legacy Gemini cũ vẫn được cách ly; 14 artifact nghiên cứu thật tham gia memory.
- yearly evidence của alpha tốt nhất đã đúng: Sharpe 1.43, Fitness 0.98, corr 0.9415, 5/5 năm Sharpe dương, min 0.59.
- family trial memory đã rebuild: `value_cashflow_multihorizon` có 8 effective trials, trong đó 7 parameter-only.
- packet discovery hiện đạt formal gate: 24 field, 13 dataset, 14 theme, max dataset share 8.33%, max theme share 20.83%, không generic/low-confidence/infrastructure/missing-description.
- cycle plan hiện có 3 diversity parents và 1 refinement parent.

Tuy nhiên vẫn còn một số ví dụ cho thấy semantic profile high-confidence không phải ground truth tuyệt đối. Ví dụ:

- `news_vol_stddev`: description nói z-score của volume so với 30-day average/std; primary theme `sentiment_news` có thể không phải cách diễn giải tốt nhất.
- `snt_buzz_ret`: description nói negative return của relative sentiment volume nhưng form hiện là `count`.
- `deferred_tax_assets_valuation_allowance_value` và `fn_def_tax_assets_liab_net_a`: chữ “valuation” là accounting allowance/tax asset, không tự động đồng nghĩa economic `value`.
- `net_profit_adjusted_min_guidance` và `max_net_debt_guidance`: underlying theme có thể đúng, nhưng semantic form nên được kiểm tra là guidance/forecast thay vì chỉ level.

Vì vậy task này phải thêm một lớp **candidate semantic adjudication** chỉ cho packet 24 field trước khi Gemini được phép nêu hypothesis.

---

## Mục tiêu duy nhất

Tạo vòng nghiên cứu đầu tiên của v2 theo chuỗi:

```text
24-field packet
    ↓
Gemini semantic adjudication (không alpha)
    ↓
rebuild/re-audit packet
    ↓
Gemini hypothesis discovery
    ↓
independent hypothesis critic
    ↓
6 accepted hypothesis cards
    ↓
Gemini high-level plan intent
    ↓
independent plan critic
    ↓
deterministic AlphaPlan resolve/compile
    ↓
type + semantic + novelty gates
    ↓
sanitzed dry-run audit on GitHub
```

KHÔNG simulate BRAIN trong task này.

---

# A. Candidate semantic adjudication v3

Thêm một function riêng, không tái dùng `_rows()` hiện tại của `review_ambiguous_fields`, vì 24 candidate hiện đều có confidence cao nhưng vẫn có thể sai semantic.

Gợi ý module:

`src/wq_alpha_os/research/candidate_review.py`

Input chính xác là `build_discovery_context(...)[candidate_fields]` của packet đã qua gate.

Gemini chỉ được nhận:

- `name`
- `description`
- `dataset`
- `data_type`
- current theme/form/cadence/signedness/unit/direction
- coverage

Tuyệt đối không gửi:

- expression
- FASTEXPR
- operator/operator name
- PnL
- Sharpe/Fitness của alpha riêng lẻ
- credentials/session

Output JSON mỗi field:

```json
{
  "name": "...",
  "verdict": "accept" | "correct" | "reject_for_discovery",
  "economic_theme": "...",
  "secondary_themes": ["..."],
  "semantic_form": "...",
  "update_cadence": "...",
  "signedness": "...",
  "unit_family": "...",
  "direction_prior": "positive|negative|ambiguous",
  "confidence": 0.0,
  "reason": "grounded in name/description"
}
```

Quy tắc:

1. Không được sửa chỉ vì “LLM nghĩ vậy”; reason phải bám name/description.
2. `direction_prior` mặc định ambiguous; chỉ positive/negative nếu semantic thật sự rõ.
3. Nếu description không đủ để phân loại, `reject_for_discovery` thay vì bịa.
4. Chỉ apply correction vào `field_profiles` nếu confidence >= 0.80.
5. Confidence LLM cap <= 0.92.
6. Mọi exchange lưu evidence local.
7. Tạo research_event provenance riêng.
8. Không review field ngoài packet.

Sau review:

- rebuild field/knowledge cần thiết;
- rebuild packet;
- packet phải pass lại toàn bộ gate;
- nếu candidate bị reject/correct làm packet thiếu diversity, deterministic discovery selector phải refill từ catalog rồi audit lại.

---

# B. Discovery packet v3 improvements

Packet gửi Gemini hypothesis phải thêm:

- `secondary_themes` nếu có;
- `semantic_review_source`: deterministic_v3 hoặc gemini_candidate_review_v3;
- `semantic_review_confidence`;
- description đầy đủ đã truncate an toàn.

Không gửi operator/template concrete ở discovery stage.

Giữ hard gates hiện tại:

- MATRIX/VECTOR only;
- generic = 0;
- low-confidence = 0;
- infrastructure = 0;
- missing description = 0;
- max dataset share <= 0.25;
- max theme share <= 0.25;
- ít nhất 6 dataset khi catalog cho phép.

---

# C. Hypothesis discovery: 6 breadth hypotheses

Chỉ sau semantic adjudication gate pass mới gọi Gemini discovery.

Tạo đúng 6 hypothesis breadth cho phase đầu của cycle 12.

Mỗi hypothesis card bắt buộc có:

- family mới;
- statement;
- economic mechanism duy nhất;
- field_names: 1 hoặc 2 field chính xác từ reviewed packet;
- expected_direction;
- horizon bucket;
- falsifier;
- novelty explanation;
- primary theme;
- source datasets;

Hard constraints:

1. Không FASTEXPR.
2. Không operator name.
3. Không parameter/window integer cụ thể ngoài coarse horizon bucket.
4. Không clone `value_cashflow_multihorizon` bằng field/window khác.
5. Không dùng cùng một field cho >1 hypothesis trong breadth batch trừ khi explicit relational hypothesis và có lý do mạnh.
6. Ít nhất 5/6 hypothesis phải khác primary economic theme.
7. Ít nhất 5 dataset khác nhau phải xuất hiện trên 6 hypothesis nếu packet cho phép.
8. Không có >2 hypothesis từ cùng một dataset.
9. Không multi-horizon ở breadth stage.
10. Không orthogonal two-branch composite nếu từng branch chưa có logic độc lập rõ; ưu tiên single-mechanism diagnostics.

---

# D. Independent hypothesis critic

Hiện plan critic đã tồn tại, nhưng hypothesis discovery cần critic riêng trước design.

Thêm stage thứ hai dùng Gemini với prompt độc lập, chỉ nhận 6 cards + failure ledger + candidate descriptions liên quan.

Critic đánh giá:

- economic mechanism có thực sự rõ không;
- field description có hỗ trợ mechanism không;
- expected direction có bị bịa không;
- falsifier có thực sự bác bỏ được không;
- novelty có khác 14 artifact cũ không;
- pairwise diversity giữa 6 cards;
- field/theme/dataset concentration.

Output:

```json
{
  "decisions": [
    {
      "card_id": "...",
      "verdict": "accept" | "reject",
      "reasons": ["..."],
      "semantic_concerns": ["..."]
    }
  ],
  "batch_verdict": "accept" | "repair",
  "batch_reasons": ["..."]
}
```

Nếu <6 card survive:

- cho phép **tối đa 1** repair discovery call để tạo replacements;
- không loop vô hạn;
- replacements cũng phải qua critic.

Mục tiêu cuối: 6 accepted hypothesis cards hoặc fail task rõ ràng, không tự hạ gate.

---

# E. Design: đúng 1 plan/hypothesis ở breadth stage

Với 6 accepted cards:

- `limit=6`
- `per_card=1`

Không tạo 2-4 plan trên cùng hypothesis ở bước breadth.

Gemini chỉ chọn intent cấp cao:

- template_id từ allowed templates;
- fields;
- coarse horizon;
- direction;
- group;
- relative_mode/extremum nếu template cần;
- turnover_control mặc định false ở breadth, trừ hypothesis event cực nhanh có rationale rõ;
- output_control;
- rationale.

Không FASTEXPR/operator.

Plan critic hiện có phải chạy độc lập.

---

# F. Deterministic compilation + gates

Mỗi accepted plan phải qua:

1. `resolve_request()`;
2. `compile_plan()`;
3. parser/DSL validation;
4. semantic validator;
5. exact duplicate gate;
6. structural duplicate gate;
7. role-motif duplicate/novelty gate;
8. semantic fingerprint gate;
9. parameter-normalized fingerprint gate;
10. subtree novelty check.

Breadth hypothesis không được accept nếu chỉ là parameter-normalized clone của existing artifact.

Nếu compile/gate fail:

- không cho Gemini sửa FASTEXPR;
- ghi exact reason;
- chỉ cho deterministic plan-level repair nếu issue là safe enum/template mismatch;
- nếu semantic hypothesis sai thì reject card, không patch công thức.

---

# G. Dry-run audit xuất lên GitHub

Tạo:

`docs/generated/candidate_semantic_review.json`

và:

`docs/generated/first_v2_hypothesis_dry_run.json`

Repo hiện vẫn public, do đó **không commit FASTEXPR đầy đủ** vào hai file này.

`candidate_semantic_review.json` gồm:

- reviewed count;
- accept/correct/reject counts;
- corrections;
- reason summaries;
- packet gate trước/sau review;
- final packet field count/dataset/theme diversity.

`first_v2_hypothesis_dry_run.json` gồm cho từng card:

- family;
- statement;
- mechanism;
- field names + descriptions;
- source datasets;
- expected direction;
- horizon bucket;
- falsifier;
- novelty rationale;
- hypothesis critic verdict;
- selected template;
- high-level plan metadata;
- plan critic verdict;
- compile success bool;
- DSL/type gate;
- semantic gate;
- exact/structural/role/semantic/parameter-normalized novelty verdicts;
- motif id/hash;
- AST node count/depth nếu có;
- **không include exact compiled expression**;
- compiled expression chỉ giữ local SQLite/evidence.

Batch summary:

- accepted hypothesis count;
- accepted plan count;
- theme count;
- dataset count;
- max dataset share;
- max theme share;
- duplicate rejection count;
- semantic rejection count;
- ready_for_first_simulation: bool;
- gate reasons.

---

# H. Update coordination state

Cập nhật:

- `docs/TRANG_THAI_HIEN_TAI.md`
- `docs/generated/research_state.json`
- `00_TONG_QUAN_DU_AN.md`

Next gate nếu dry-run pass phải là:

> Run exactly the 6 breadth simulations of the first v2 cycle, then stop and analyze evidence before allocating the 3 refinement + 3 diversity slots.

Không mô phỏng trong task này.

---

# Acceptance criteria

Task chỉ đạt khi:

1. toàn bộ test pass;
2. semantic adjudication chỉ review đúng candidate packet;
3. post-review packet gate pass;
4. 6 accepted hypothesis cards;
5. >=5 primary themes across 6 cards;
6. >=5 datasets across 6 cards nếu packet cho phép;
7. <=2 cards từ cùng dataset;
8. 1 plan/card;
9. hypothesis critic và plan critic đều chạy;
10. tất cả accepted plans compile + DSL/type + semantic gates pass;
11. không exact/parameter-normalized clone với 14 artifact active;
12. `first_v2_hypothesis_dry_run.json` không chứa FASTEXPR/expression surface;
13. `ready_for_first_simulation=true` chỉ khi đủ 6 plans sạch;
14. không gọi BRAIN simulation;
15. Gemini chỉ được gọi cho semantic adjudication, hypothesis discovery/repair và critics/design nói trên;
16. chạy finalize, commit, push `alpha-research-v2`.

Kết thúc bằng:

```powershell
.\scripts\finalize_task.ps1 -Message "feat: build first reviewed v2 hypothesis dry run"
```

Sau khi push chỉ báo:

- commit SHA;
- tests pass;
- candidate semantic review accept/correct/reject;
- final packet dataset/theme count;
- 6 hypothesis families + dataset/theme (không formula);
- hypothesis critic pass count;
- plan critic pass count;
- compiled/gated plan count;
- `ready_for_first_simulation`;
- xác nhận BRAIN simulation = 0.
