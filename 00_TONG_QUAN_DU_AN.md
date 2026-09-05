# Tong quan du an WQ Alpha OS

File nay la diem doc dau tien cho cac phien lam viec sau. Muc tieu la tiet kiem dung luong hoi thoai: doc file nay truoc, chi mo them file khac khi can sua dung phan do.

## Snapshot trang thai

- Ban snapshot may-doc duoc nam tai `docs/TRANG_THAI_HIEN_TAI.md`.
- Snapshot hien tai: 16 dataset, 7642 truong, 127 toan tu, 14 ung vien, 14 lan mo phong (13 hoan tat, 1 loi), 0 promoted.
- Alpha tot nhat hien tai co Sharpe 1.43, Fitness 0.98, turnover 0.028 va self-correlation 0.9415; chua dat nguong de promoted.
- Moi tac nhan phai doc snapshot sau file nay truoc khi xem SQLite hoac bat dau viec moi.

## Quy tac lam viec ngan gon

- Khong dan nhat ky dai, danh sach alpha lon, ket qua lai lo, hoac toan bo co so du lieu vao hoi thoai.
- Khong in tai khoan, mat khau, khoa truy cap, ma phien. File `.env` chi nam cuc bo va khong dua vao Git.
- Uu tien viet ma de may tu chay: sinh y tuong, kiem tra cu phap, chong trung, mo phong, lay ket qua, cham diem, xuat tep.
- Khong tu dong nop alpha len WorldQuant BRAIN. He thong chi tao alpha, mo phong, luu bang chung va xuat duong dan.
- Sau khi sua ma, chay kiem thu toi thieu: `python -m unittest discover -s tests -v`.

## Cach mo dung du an

Thu muc du an nen dung rieng, khong de chung trong thu muc co nhieu bai C++/Python khac. Vi du tot:

```powershell
C:\Users\welcome\OneDrive\Desktop\wq-alpha-os-starter
```

Sau khi mo cua so lenh moi:

```powershell
Set-Location 'C:\Users\welcome\OneDrive\Desktop\wq-alpha-os-starter'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
alpha-os status
```

Neu moi truong ao bi hong sau khi chuyen thu muc, tao lai:

```powershell
Set-Location 'C:\Users\welcome\OneDrive\Desktop\wq-alpha-os-starter'
Remove-Item -LiteralPath .\.venv -Recurse -Force
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
alpha-os status
```

## Kien truc hien tai

- `src/wq_alpha_os/cli.py`: cua vao dong lenh `alpha-os`.
- `src/wq_alpha_os/config.py`: doc cau hinh tu `.env`.
- `src/wq_alpha_os/db.py`: tao va nang cap co so du lieu cuc bo SQLite.
- `src/wq_alpha_os/brain/`: dang nhap, dong bo danh muc, mo phong, lay ket qua tu WorldQuant BRAIN.
- `src/wq_alpha_os/research/`: sinh ung vien, chong trung, cham diem va tac tu Gemini.
- `src/wq_alpha_os/providers/`: lop goi mo hinh ngon ngu, hien co Gemini va may chu tuong thich OpenAI.
- `data/db/`: co so du lieu cuc bo, la nguon su that cua du an.
- `data/evidence/`: bang chung, goi cau nhac, phan hoi mo hinh, ket qua mo phong.
- `data/exports/`: tep xuat ra de xem, dua vao Google Sheets, hoac mo trinh mo phong.
- `scripts/run_research.ps1`: chay mot vong nghien cuu tu dong.
- `tests/`: kiem thu.

## Kien truc tac tu sinh alpha

Muc tieu khong phai sinh nhieu cong thuc na na alpha cu, ma sinh gia thuyet moi co co che kinh te ro rang.

Luong chinh:

1. Dong bo danh muc truong du lieu va toan tu tu WorldQuant BRAIN.
2. Tao goi nghien cuu cuc bo gom truong du lieu uu tien, bai hoc that bai tong hop, va quy tac ghep toan tu.
3. Goi Gemini de tao the gia thuyet, chua cho phep viet cong thuc.
4. Goi Gemini de thiet ke cong thuc nho tu tung the gia thuyet.
5. Goi Gemini lan nua de phan bien cong thuc.
6. Kiem tra cuc bo: cu phap, kieu du lieu, thu tu toan tu, chong trung chinh xac va gan dung.
7. Dua ung vien hop le vao hang cho mo phong.
8. Mo phong tren WorldQuant BRAIN, lay ket qua, cham diem, xuat tep.

## Nhom toan tu du kien

Y tuong chinh: khong boc toan tu lung tung. Moi cong thuc phai di qua mot duong hop ly.

- Lam min/lam on chuoi thoi gian: `ts_rank`, `ts_zscore`, `ts_mean`, `ts_delta`, `ts_decay_linear`.
- Xep hang mat cat ngang: `rank`, `group_rank`, `normalize`.
- Trung lap vai tro can han che: khong chong nhieu ham cung tac dung xep hang/chuan hoa neu khong co ly do.
- Dao chieu tin hieu: `reverse`, hoac he so am trong `multiply`.
- Ket hop nhanh hai nhanh: `add`, `subtract`, `multiply`, `signed_power`.
- Du lieu vec-to phai rut gon truoc khi dung nhu ma tran.
- Nhom trung hoa uu tien: nganh, phan nganh, quoc gia, thi truong, tuy tung universe.

## Huong toi uu chat luong

- Tang do moi bang cach uu tien truong du lieu chua thu, nhom du lieu chua khai thac va co che khac alpha cu.
- Luu ly do that bai theo nhom, khong chi theo tung cong thuc.
- Tao the gia thuyet truoc, cong thuc sau, de tranh Gemini clone alpha mau.
- Moi cong thuc moi can co ly do tai sao du lieu nay co the du bao loi nhuan.
- Sau khi co ket qua mo phong, uu tien hoc tu alpha gan dat: Sharpe, Fitness, turnover, coverage, self correlation, drawdown va so nam duong.
- Neu alpha gan dat nhung self correlation cao, tao bien the bang truong/nhom co che khac, khong chi doi tham so.

## Tien do hien tai

- Da co dong bo danh muc truong du lieu va toan tu.
- Da co co so du lieu cuc bo va bang chung trong `data/`.
- Da co luong mo phong, lam moi ket qua, cham diem, xuat tep.
- Da co bo chong trung de tranh gui lai alpha da co ho so mo phong.
- Da them nen tac tu Gemini: kham pha gia thuyet, thiet ke cong thuc, phan bien, kiem tra cuc bo.
- Viec goi Gemini that can duoc cho phep gui goi ngu canh nghien cuu ra ngoai.

## Viec lam tiep

- Chay that `alpha-os agent discover --count 2` khi nguoi dung cho phep gui goi ngu canh toi Gemini.
- Chay `alpha-os agent design --limit 2 --per-card 1` de tao ung vien dau tien.
- Mo phong so luong nho, xem ket qua, roi moi tang toc.
- Cai thien bo rut kinh nghiem sau mo phong de Gemini thay bai hoc tong hop thay vi clone cong thuc cu.
- Sau nay co the xuat `simulator_url` vao Google Sheets de bam mo trang WorldQuant BRAIN da dien alpha.
