# WQ Alpha OS

Hệ thống nghiên cứu alpha (tín hiệu dự báo) chạy bằng dòng lệnh cho WorldQuant BRAIN. Mục tiêu là tạo alpha có cơ chế kinh tế rõ ràng, kiểm tra được và không phải bản sao tham số của alpha cũ.

## Nguyên tắc vận hành

- Máy tự thực hiện các bước lặp lại: tạo giả thuyết, kiểm tra cấu trúc, chống trùng, mô phỏng, lấy bằng chứng, chấm điểm và xuất tệp.
- `data/db/` và `data/evidence/` là nguồn sự thật cục bộ. Không cần đưa nhật ký dài, danh sách alpha hay dữ liệu PnL (lãi/lỗ theo thời gian) vào trao đổi.
- Gemini chỉ dùng để suy luận giả thuyết, thiết kế thí nghiệm và phản biện. Chương trình cục bộ quyết định cú pháp, kiểu dữ liệu, độ trùng và việc đưa alpha vào hàng đợi mô phỏng.
- Không tự động nộp alpha. Hệ thống chỉ mô phỏng, lưu kết quả và xuất đường dẫn; người dùng tự quyết định mô phỏng hoặc nộp trên BRAIN.
- Không in hoặc đưa vào Git tài khoản, mật khẩu, mã phiên và khóa truy cập.

## 1. Cài đặt một lần

Yêu cầu Python (ngôn ngữ lập trình) 3.11 trở lên.

```powershell
Set-Location 'C:\Users\welcome\OneDrive\Desktop\wq-alpha-os-starter'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Nếu môi trường `.venv` đã có, chỉ cần mở PowerShell (trình dòng lệnh) tại đúng thư mục dự án và chạy các lệnh `alpha-os` bên dưới. Không dùng đường dẫn `..venv`; đường dẫn đúng là `.\.venv\...`.

Khởi tạo cơ sở dữ liệu SQLite (cơ sở dữ liệu gọn trong một tệp) và, nếu có, nhập dữ liệu cũ:

```powershell
alpha-os init
alpha-os catalog import-legacy --source data/db/legacy_wq_alpha_os.sqlite
alpha-os status
```

## 2. Thiết lập Gemini

Mở `.env`, chỉ trên máy của bạn, rồi điền tối thiểu:

```dotenv
Đặt khóa Gemini cục bộ trong tệp `.env` bằng biến `GEMINI_API_KEY` (không đưa khóa vào Git).
GEMINI_MODEL=gemini-2.5-pro
```

`GEMINI_BASE_URL` đã có giá trị mặc định trong `.env.example`, thường không cần sửa. Luồng `alpha-os agent ...` luôn gọi Gemini; có thể thêm dòng dưới đây nếu cũng muốn lệnh tạo đề xuất cũ dùng Gemini:

```dotenv
ALPHA_LLM_PROVIDER=gemini
```

Không đặt khóa vào `.env.example`, không chụp màn hình khóa và không gửi tệp `.env`. Khóa được gửi trong tiêu đề của lời gọi API (giao diện lập trình), không được ghi vào tệp bằng chứng hay thông báo lỗi.

## 3. Luồng tác tử Gemini

Luồng mới tách ba việc để tránh Gemini sao chép alpha cũ:

1. Khám phá chỉ tạo **thẻ giả thuyết**: cơ chế kinh tế, dấu kỳ vọng, chân trời, trường dữ liệu và điều kiện bác bỏ; chưa được phép tạo công thức.
2. Thiết kế tạo tối đa vài biểu thức thí nghiệm nhỏ từ từng thẻ.
3. Phản biện độc lập, bộ kiểm tra cục bộ, đồ thị tương thích toán tử và cổng chống trùng quyết định biểu thức nào trở thành `validated` (đã xác thực cục bộ).

Đồ thị toán tử chỉ cho phép ghép đúng loại dữ liệu và thứ tự hợp lý, chẳng hạn xử lý chuỗi thời gian trước khi xếp hạng theo mặt cắt, hoặc rút gọn dữ liệu véc-tơ trước khi dùng như ma trận. Các toán tử cùng vai trò thay thế không được chồng tùy tiện.

Trong lời gọi Gemini, chương trình chỉ gửi siêu dữ liệu trường đã được chọn, các ràng buộc toán tử và bài học tổng hợp từ các lần thất bại. Không gửi công thức alpha cũ hoặc dữ liệu PnL riêng. Công thức mới do Gemini vừa tạo chỉ được đưa sang lượt phản biện trong chính vòng đó.

### Các lệnh

Xem gói nghiên cứu trước, không gọi Gemini và không mô phỏng:

```powershell
alpha-os agent packet --count 4
```

Gọi Gemini để tạo thẻ giả thuyết, chưa tạo alpha:

```powershell
alpha-os agent discover --count 4
```

Thiết kế và phản biện alpha từ các thẻ đã lưu; chưa mô phỏng:

```powershell
alpha-os agent design --limit 4 --per-card 2
```

Chạy cả khám phá, thiết kế, phản biện và kiểm tra cục bộ; vẫn chưa mô phỏng:

```powershell
alpha-os agent run --count 4 --per-card 2
```

Sau mỗi lệnh, bằng chứng câu nhắc và phản hồi được lưu trong `data/evidence/agent/`. Có thể kiểm tra số lượng thẻ, alpha hợp lệ và hàng đợi bằng:

```powershell
alpha-os status
alpha-os candidates --status validated --limit 30
```

## 4. Đồng bộ danh mục và mô phỏng

Lần đầu, hoặc khi cần làm mới trường dữ liệu và toán tử mà tài khoản được phép dùng:

```powershell
alpha-os catalog sync --region USA --universe TOP3000 --delay 1
```

Kiểm tra hàng đợi trước khi gửi thật:

```powershell
alpha-os simulate --limit 8 --dry-run
```

Gửi mô phỏng, lấy kết quả và chấm lại:

```powershell
alpha-os simulate --limit 8
alpha-os refresh --limit 8
alpha-os review --limit 20
alpha-os status
```

Một alpha đã có hồ sơ mô phỏng, kể cả hồ sơ lỗi hoặc hết thời gian chờ, sẽ không tự gửi lại để tránh tạo bản trùng. Muốn thử lại, phải tạo biến thể mới và để cổng chống trùng kiểm tra.

## 5. Chạy một vòng bằng tập lệnh PowerShell

Tập lệnh tự tìm đúng tệp thực thi trong `.venv`, vì vậy nên gọi từ thư mục dự án:

```powershell
Set-Location 'C:\Users\welcome\OneDrive\Desktop\wq-alpha-os-starter'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\run_research.ps1 -Limit 8
```

Thêm `-Generate` để chạy tác tử Gemini trước, sau đó kiểm tra hàng đợi, mô phỏng các alpha hợp lệ, tải kết quả, chấm điểm và xuất hai tệp:

- `data/exports/alpha_tested.csv`: alpha đã có kết quả mô phỏng.
- `data/exports/alpha_promoted.csv`: alpha đã vượt các cổng thăng hạng.

```powershell
.\scripts\run_research.ps1 -Limit 8 -Generate
```

`-Generate` không tự nộp alpha. Nếu thêm `-DryRun`, tập lệnh chỉ kiểm tra hàng đợi, không gọi Gemini, không mô phỏng thật, không tải kết quả và không xuất tệp mới.

Lần đầu muốn đồng bộ danh mục ngay trong cùng vòng:

```powershell
.\scripts\run_research.ps1 -Limit 8 -SyncCatalog -Generate
```

## 6. Xuất đường dẫn mở trình mô phỏng

Cài một lần tệp người dùng [scripts/brain_prefill.user.js](scripts/brain_prefill.user.js) bằng Tampermonkey (tiện ích chạy mã người dùng). Sau đó xuất:

```powershell
alpha-os export --output data/exports/alpha_promoted.csv --status promoted
```

Cột `simulator_url` có thể đưa vào Google Sheets (bảng tính Google). Khi bấm đường dẫn, BRAIN mở bằng phiên đăng nhập hiện có và tệp người dùng cố điền biểu thức vào trình mô phỏng. Nó không tự bấm nút mô phỏng hoặc nút nộp.

## 7. Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

## Tài liệu tham khảo

- [Ví dụ alpha của WorldQuant BRAIN](https://worldquantbrain.com/alpha-examples)
- [Trang giới thiệu WorldQuant BRAIN](https://www.worldquant.com/brain/?next=/dashboard)
- [Hướng dẫn Gemini API (giao diện lập trình)](https://ai.google.dev/gemini-api/docs/get-started)
