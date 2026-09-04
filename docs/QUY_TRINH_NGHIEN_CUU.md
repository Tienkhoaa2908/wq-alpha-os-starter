# Quy trình nghiên cứu

## Nguyên tắc tiết kiệm dung lượng trao đổi

Mọi phép thử có thể tự động hóa trên máy người dùng thì ưu tiên viết thành mã hoặc dùng lệnh có sẵn. Máy tự chạy đồng bộ danh mục, kiểm tra, mô phỏng, thu bằng chứng, đánh giá và xuất tệp; không cần đưa toàn bộ nhật ký hoặc kết quả dài vào cuộc trao đổi.

Cuộc trao đổi chỉ nên giữ lại những thứ cần cho quyết định: mục tiêu, thay đổi cần làm, kết quả tóm tắt, lỗi và quyết định tiếp theo. Bằng chứng đầy đủ phải được lưu trong `data/evidence/` và cơ sở dữ liệu; khi cần kiểm tra lại, hệ thống đọc từ các tệp đó thay vì yêu cầu gửi lại nội dung qua hộp thoại.

Không lặp lại ngữ cảnh đã ghi trong tài liệu. Khi yêu cầu hỗ trợ, chỉ gửi tên lỗi, một đoạn lỗi ngắn và đường dẫn tệp liên quan. Cuối mỗi đợt chạy, dùng một báo cáo gọn để ghi số alpha đã thử, số alpha qua cổng, alpha tốt nhất, lý do loại và việc cần làm tiếp theo.

Mỗi họ alpha bắt đầu bằng một giả thuyết kinh tế có thể bác bỏ. Lứa đầu gồm mẫu gốc, phép loại bỏ từng nhánh và phép thử độ nhạy một biến. Thiết lập mô phỏng được cố định trong một đợt; không vừa dò biểu thức vừa dò mọi thiết lập.

Một kết quả chỉ đi vào bộ nhớ học khi:

- mô phỏng hoàn tất và phản hồi thô đã được lưu;
- biểu thức cùng thiết lập khớp với yêu cầu đã lưu;
- các chỉ số và kiểm tra được đọc từ phản hồi, không do mô hình dự đoán;
- phép đánh giá độc lập đã ghi rõ dữ liệu còn thiếu;
- số lần thử của cả họ được tính, để tránh chọn may mắn sau quá nhiều lần thử.

Với thất bại, thay đúng một nguyên nhân có thể kiểm tra: vòng quay cao thì thử `hump` hoặc khung dài hơn; hướng âm thì kiểm tra `reverse`; hiệu quả chỉ đến từ một nhánh thì bỏ nhánh còn lại. Alpha gần trùng không phải là khám phá mới và không được tính thành họ độc lập.

Trước khi nộp, người dùng vẫn phải kiểm tra tương quan, điều kiện cuộc thi, tính ổn định theo năm và cổng kiểm tra trên BRAIN. Hệ thống cố ý không tự nộp.
