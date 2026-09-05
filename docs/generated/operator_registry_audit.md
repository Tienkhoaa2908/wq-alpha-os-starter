# Kiem toan nguon toan tu BRAIN dang hoat dong

- Nguon: `data/evidence/catalog/20260904T160247.712177Z/operators.json`
- Thoi diem ban chup nguon: `2026-09-04T23:06:35+07:00`
- Dong nguon BRAIN: 66
- Ten toan tu BRAIN duy nhat: 66
- Toan tu dang goi bang ham: 60
- Toan tu so sanh logic dung cu phap infix: 6
- Dong trung lap trong nguon: 0

## Chenh lech ho tro

- BRAIN co nhung DSL chua ho tro: khong co.
- DSL co nhung BRAIN khong co: `std`.
- So sanh logic duoc parser DSL ho tro bang infix, khong nam trong SPECS goi ham: `equal` (`==`), `not_equal` (`!=`), `greater` (`>`), `greater_equal` (`>=`), `less` (`<`), `less_equal` (`<=`).

## Kiem tra signature va kwargs

- Khong phat hien sai khac arity ro rang trong 60 toan tu goi ham.
- `ts_backfill`: BRAIN cong bo kwargs `lookback`, `k`; SPECS dang cho phep them `d`. Day la mismatch can sua trong mot luot thay doi compiler rieng.
- Cac kwargs con lai khop sau khi chuan hoa chu hoa/chu thuong.

## Kiem tra `std`

- Co trong SPECS: co.
- Co trong ban chup BRAIN dang hoat dong: khong.
- Duoc coi la active: khong.
- Ket luan: `std` chi la kha nang trong typed registry hien tai, khong phai toan tu active cua BRAIN.

## Nguyen nhan con so 127 va cach xu ly

Bang `operators` cu chua 61 dong `typed_registry` va 66 dong BRAIN trong cung ban chup, nen truy van `count(*)` tra 127. View `active_brain_operators` bay gio chi lay ban chup `brain_api` moi nhat, loai `typed_registry`, va deduplicate theo ten. Lenh `status` dung view nay nen active operator count la 66. SPECS van o `dsl/specs.py` lam metadata bien dich va khong duoc chen vao catalog nua.

Moi lan nhap BRAIN sau nay luu operator key theo `snapshot_id` va ten, khong xoa ban chup lich su. Tep JSON da lam sach tai `docs/generated/brain_operators_active.json` chi giu `name`, `category`, `definition`, `description`.
