# Thu thập dữ liệu

Ưu tiên đầu nối tài khoản chính chủ qua lệnh `alpha-os catalog sync`. Nó lấy danh sách bộ dữ liệu, trường và toán tử mà tài khoản hiện tại có quyền xem, phân trang đầy đủ và lưu bản thô theo thời điểm.

Nếu đăng nhập cần xác minh bổ sung hoặc đầu nối thay đổi, làm theo thứ tự:

1. đăng nhập BRAIN bằng trình duyệt và xuất danh mục được nền tảng cho phép;
2. đặt tệp xuất trong `data/raw/manual/`;
3. bổ sung bộ nhập riêng cho đúng định dạng, không cào trang bằng cách vượt kiểm soát truy cập;
4. tuyệt đối không đưa mật khẩu, bánh quy phiên hoặc khóa bí mật vào kho mã.

Dữ liệu cũ được giữ tại `data/db/legacy_wq_alpha_os.sqlite` và `data/raw/legacy_exports/`. Chúng là nguồn chuyển tiếp, không phải sự thật mới nhất. Mỗi lần đồng bộ thật tạo một bản chụp có thời gian và đường dẫn bằng chứng.

Các đường dẫn máy chủ trong mã được xem là đầu nối có thể thay đổi, không phải hợp đồng công khai ổn định. Khi cấu trúc phản hồi đổi, chương trình dừng và giữ lỗi thay vì âm thầm huấn luyện từ dữ liệu sai.
