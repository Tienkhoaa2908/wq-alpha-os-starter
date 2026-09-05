# Trang thai hien tai

```yaml
snapshot_time: "2026-09-05T20:27:35+07:00"
commit_at_snapshot: "87a4f04 Initial project structure"
database: "data/db/alpha_lab.sqlite"
configuration:
  instrument_type: EQUITY
  region: USA
  universe: TOP3000
  delay: 1
  decay: 6
  neutralization: INDUSTRY
  truncation: 0.01
  pasteurization: ON
  nan_handling: OFF
  unit_handling: VERIFY
  promotion_min_sharpe: 1.25
  promotion_min_fitness: 1.0
  promotion_max_self_correlation: 0.7
catalog:
  datasets: 16
  fields: 7642
  operators: 127
research:
  hypothesis_cards: 0
  candidates: 14
  candidates_validated: 1
simulations:
  submitted: 14
  completed: 13
  failed: 1
  pending: 0
promotion:
  promoted: 0
best_alpha:
  expression: "normalize(add(multiply(0.75, hump(reverse(group_rank(ts_rank(mdl177_2_deepvaluefactor_ttmcfp, 756), industry)), hump=0.01)), multiply(0.25, reverse(group_rank(ts_rank(mdl177_2_deepvaluefactor_ttmcfp, 252), industry))), filter=true), useStd=true, limit=3)"
  family: value_cashflow_multihorizon
  sharpe: 1.43
  fitness: 0.98
  turnover: 0.028
  self_correlation: 0.9415
  annual_stability: "5 nam co Sharpe duong; nam thap nhat 0.59"
  not_promoted_reason: "Fitness duoi 1.0; tuong quan tu than 0.9415 vuot nguong 0.7 va phep kiem tra tuong quan dang cho"
families_tried:
  - value_cashflow_multihorizon
  - analyst_revision_acceleration
  - quality_profitability_persistence
  - low_idiosyncratic_risk
  - revision_quality_confirmation
  - value_revision_confirmation
families_frozen:
  - analyst_revision_acceleration
  - quality_profitability_persistence
  - low_idiosyncratic_risk
  - revision_quality_confirmation
  - value_revision_confirmation
lessons_confirmed:
  - "value_cashflow_multihorizon la nhom co ket qua tot nhat hien tai"
  - "Sharpe dat nhung Fitness va tuong quan tu than van co the chan day alpha"
  - "Cac bien the cung mot tin hieu co tuong quan cao; can doi truong hoac co che"
  - "13/14 lan mo phong hoan tat; mot lan loi can duoc giu lam nhat ky"
known_defects:
  - "Chua co hypothesis card moi tu luong tac tu Gemini"
  - "Chua co alpha duoc promoted"
  - "Kiem tra tuong quan tu than cua alpha tot nhat dang pending"
  - "Du lieu legacy trong SQLite chua tach hoan toan khoi thong ke nghien cuu"
next_agreed_work:
  - "Cho phep va chay agent discover/design bang Gemini khi nguoi dung yeu cau"
  - "Bat buoc tao gia thuyet moi truoc khi viet cong thuc"
  - "Mo phong lo nho, loc Fitness >= 1.0 va self-correlation <= 0.7"
  - "Khong tu dong nop; chi xuat duong dan de nguoi dung bam mo phong"
```

Nguon: truy van truc tiep SQLite cuc bo tai thoi diem snapshot. Khong luu thong tin dang nhap, khoa truy cap, phan hoi API thô, hoac PnL theo ma chung khoan.
