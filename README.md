# WQ Alpha OS

Hệ thống nghiên cứu alpha (tín hiệu dự báo) chạy bằng dòng lệnh cho WorldQuant BRAIN. Mục tiêu của dự án là tạo một vòng nghiên cứu có bằng chứng:

1. đồng bộ trường dữ liệu và toán tử từ BRAIN;
2. tạo giả thuyết và biểu thức có kiểu;
3. chặn biểu thức sai hoặc trùng trước khi mô phỏng;
4. gửi mô phỏng, lưu nguyên văn kết quả và các kiểm tra;
5. chấm điểm, kiểm tra độc lập và chỉ đột biến từ bằng chứng thật;
6. xuất tệp CSV (bảng dữ liệu phân cách bằng dấu phẩy) có đường dẫn mở BRAIN và tự điền biểu thức.

Không có giao diện trang mạng. SQLite (cơ sở dữ liệu gọn trong một tệp) được dùng cho trạng thái; mọi phản hồi quan trọng từ BRAIN được lưu bất biến trong `data/evidence/`.

Các trạng thái có nghĩa rõ ràng:

- `legacy_unverified`: alpha cũ chỉ dùng để chống trùng, chưa được tin là tốt;
- `validated`: đúng cú pháp và danh mục, sẵn sàng mô phỏng;
- `tested`: đã có kết quả BRAIN nhưng chưa qua hết cổng độc lập;
- `promoted`: đạt ngưỡng chỉ số, kiểm tra tương quan và đủ bằng chứng theo năm.

## 1. Cài đặt

Yêu cầu Python (ngôn ngữ lập trình) 3.11 trở lên.

```powershell
cd C:\Users\welcome\OneDrive\Desktop\C++\wq-alpha-os-starter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Khởi tạo cơ sở dữ liệu mới và nhập dữ liệu cũ:

```powershell
alpha-os init
alpha-os catalog import-legacy --source data/db/legacy_wq_alpha_os.sqlite
alpha-os status
```

## 2. Tạo lứa alpha nền

Lứa đầu tiên dùng cấu trúc đa khung thời gian, kiểm soát nhóm và `hump` (giới hạn thay đổi vị thế), được rút ra từ alpha mẫu đã xác nhận:

```powershell
alpha-os seed --field mdl177_2_deepvaluefactor_ttmcfp
alpha-os candidates --status validated --limit 30
```

Mọi alpha phải qua bộ phân tích cú pháp, kiểm tra trường/toán tử và cổng chống trùng. Không biểu thức nào được coi là tốt trước khi có kết quả BRAIN.

## 3. Dùng Qwen miễn phí tại máy

Đầu nối mặc định hỗ trợ Ollama (trình chạy mô hình tại máy) và Qwen (mô hình ngôn ngữ mã nguồn mở):

```powershell
ollama pull qwen3:1.7b
ollama serve
```

Riêng máy hiện tại chỉ có khoảng 4 GB bộ nhớ và đồ họa tích hợp, vì vậy bản 8B (tám tỷ tham số) không phù hợp. Bản `qwen3:1.7b` ở trên chỉ nên dùng để thử đầu nối, không nên kỳ vọng nó tạo giả thuyết tốt hơn Codex. Với lứa nghiên cứu quan trọng, dùng lệnh `prompt` bên dưới và đưa gói câu nhắc cho Codex; bộ xác thực và chống trùng vẫn chạy tại máy.

Trong `.env`:

```dotenv
ALPHA_LLM_BASE_URL=http://localhost:11434/v1
ALPHA_LLM_MODEL=qwen3:1.7b
ALPHA_LLM_API_KEY=ollama
```

Tạo đề xuất:

```powershell
alpha-os propose --count 8
```

Nếu không muốn chạy mô hình tại máy, tạo gói câu nhắc rồi đưa tệp đó cho Codex hoặc một mô hình khác:

```powershell
alpha-os prompt --count 8
alpha-os ingest-proposals data/outbox/proposals.json
```

Định dạng JSON (dữ liệu có cấu trúc) bắt buộc được ghi ngay trong gói câu nhắc.

## 4. Kết nối BRAIN

Thông tin đăng nhập chỉ nằm trong `.env` tại máy và đã bị Git bỏ qua:

```dotenv
BRAIN_EMAIL=dia_chi_cua_ban
BRAIN_PASSWORD=mat_khau_cua_ban
```

Không gửi `.env`, mật khẩu, mã phiên hoặc dữ liệu PnL (lãi và lỗ theo thời gian) cho mô hình.

Đồng bộ danh mục mà tài khoản được phép truy cập:

```powershell
alpha-os catalog sync --region USA --universe TOP3000 --delay 1
```

Kiểm tra hàng đợi mà không gửi mô phỏng:

```powershell
alpha-os simulate --limit 5 --dry-run
```

Gửi thật và thu kết quả:

```powershell
alpha-os simulate --limit 5
alpha-os review --limit 20
alpha-os status
```

Đầu nối tuân theo `Retry-After` (thời gian máy chủ yêu cầu chờ), giới hạn song song mặc định là một và không tự nộp alpha. Tài khoản có xác minh bổ sung hoặc không có quyền dùng API (giao diện lập trình) sẽ dừng với hướng dẫn rõ ràng.

## 5. Xuất đường dẫn mở trình mô phỏng

Cài một lần tệp người dùng [scripts/brain_prefill.user.js](scripts/brain_prefill.user.js) bằng Tampermonkey (tiện ích chạy đoạn mã người dùng). Sau đó:

```powershell
alpha-os export --output data/exports/alpha_candidates.csv --status promoted
```

Cột `simulator_url` trong CSV có thể đưa vào Google Sheets (bảng tính Google). Khi bấm đường dẫn, BRAIN mở bằng phiên đăng nhập hiện có và đoạn mã người dùng cố gắng điền biểu thức. Nó không tự bấm nút mô phỏng.

## 6. Vòng nghiên cứu tự động

```powershell
alpha-os run --budget 12 --provider ollama
```

Một vòng gồm: chọn họ nghiên cứu, tạo đề xuất, xác thực, chặn trùng, mô phỏng, thu bằng chứng, chấm điểm và kiểm tra độc lập. Chỉ các kết quả đã được BRAIN xác nhận mới cập nhật điểm của họ nghiên cứu.

## 7. Quy tắc an toàn nghiên cứu

- Không tự nộp alpha; quyết định nộp là của người dùng.
- Không tối ưu đồng thời biểu thức và mọi thiết lập.
- Không dùng kết quả chưa xác minh làm ký ức.
- Mọi thử nghiệm có cha, phép đột biến, phiên bản câu nhắc và dấu vân tay.
- Alpha trùng chính xác luôn bị chặn. Alpha gần trùng chỉ được giữ khi là phép loại bỏ thành phần hoặc thử độ nhạy có cha rõ ràng, và không được thăng hạng nếu chưa qua kiểm tra tương quan.
- Giữ số lần thử theo từng họ để thấy rủi ro chọn lọc quá mức.

Đọc thêm: [docs/DANH_GIA_HIEN_TRANG.md](docs/DANH_GIA_HIEN_TRANG.md), [docs/KIEN_TRUC.md](docs/KIEN_TRUC.md), [docs/THU_THAP_DU_LIEU.md](docs/THU_THAP_DU_LIEU.md), [docs/QUY_TRINH_NGHIEN_CUU.md](docs/QUY_TRINH_NGHIEN_CUU.md).

## 8. Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

## Nguồn tham khảo

- WorldQuant BRAIN, ví dụ alpha theo nhóm dữ liệu: https://worldquantbrain.com/alpha-examples
- Hướng dẫn IQC 2026: https://platform.worldquantbrain.com/competition/IQC2026S1/agreement
- AgonAlpha, tìm kiếm theo hiện vật nghiên cứu có kiểm chứng: https://arxiv.org/abs/2608.11250
- Qwen3, cách chạy tại máy và giấy phép Apache 2.0: https://github.com/QwenLM/Qwen3

Các đường dẫn API BRAIN không được coi là hợp đồng công khai ổn định. Đầu nối lưu phản hồi thô và báo lỗi khi giao diện máy chủ thay đổi.
