# Quy tắc làm việc của dự án

- Ưu tiên viết mã để máy tự chạy các bước lặp lại: sinh đề xuất, kiểm tra, mô phỏng, lấy bằng chứng, chấm điểm và xuất tệp.
- Giữ trao đổi ngắn: không dán toàn bộ nhật ký, danh sách alpha hoặc dữ liệu lãi/lỗ; chỉ báo cáo tổng hợp, lỗi và đường dẫn tệp.
- `data/db/` và `data/evidence/` là nguồn sự thật cục bộ để tiếp tục công việc sau này.
- Không tự động nộp alpha lên WorldQuant; chỉ tạo đường dẫn và để người dùng bấm mô phỏng hoặc nộp thủ công.
- Không in tài khoản, mật khẩu, mã phiên hay khóa truy cập. Tệp `.env` chỉ nằm trên máy và không được đưa vào Git.
- Mọi thay đổi phải có kiểm thử tối thiểu bằng `python -m unittest discover -s tests -v`.
