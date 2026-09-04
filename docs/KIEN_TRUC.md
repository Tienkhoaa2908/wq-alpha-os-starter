# Kiến trúc

Luồng chính là `danh mục → giả thuyết → biểu thức → xác thực → chống trùng → mô phỏng → bằng chứng → đánh giá → bộ nhớ`.

- `catalog.py` nhập danh mục cũ hoặc đồng bộ đúng những gì tài khoản BRAIN nhìn thấy.
- `dsl/` phân tích biểu thức thành cây, kiểm tra số tham số, kiểu trường và tạo dấu vân tay.
- `research/artifacts.py` là cổng duy nhất ghi alpha. Trùng chính xác bị loại; gần trùng chỉ được giữ khi là thử độ nhạy có cha rõ ràng.
- `brain/` đăng nhập, gửi từng mô phỏng, tôn trọng thời gian chờ và lưu phản hồi nguyên văn.
- `research/scorer.py` chỉ chấm kết quả đã có; không dùng nhận xét của mô hình thay cho số liệu BRAIN.
- `research/reviewer.py` là lớp kiểm tra độc lập, không tham gia sinh đề xuất.
- `exporter.py` tạo CSV và đường dẫn chứa biểu thức; đoạn mã người dùng trên trình duyệt chỉ điền, không tự bấm.

SQLite giữ chỉ mục và trạng thái. `data/evidence/` giữ yêu cầu/phản hồi bất biến để có thể kiểm toán. Mô hình ngôn ngữ không được nhận mật khẩu, phiên đăng nhập hoặc dữ liệu lợi nhuận cấp mã chứng khoán.

Hệ thống chưa gọi một alpha là “chất lượng” chỉ vì cú pháp hợp lệ. Trạng thái `validated` chỉ có nghĩa là đủ điều kiện thử; `tested` là đã có mô phỏng; `promoted` là vượt ngưỡng và lớp đánh giá không tìm thấy thiếu bằng chứng trọng yếu.
