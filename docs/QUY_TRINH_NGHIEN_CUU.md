# Quy trình nghiên cứu

Mỗi họ alpha bắt đầu bằng một giả thuyết kinh tế có thể bác bỏ. Lứa đầu gồm mẫu gốc, phép loại bỏ từng nhánh và phép thử độ nhạy một biến. Thiết lập mô phỏng được cố định trong một đợt; không vừa dò biểu thức vừa dò mọi thiết lập.

Một kết quả chỉ đi vào bộ nhớ học khi:

- mô phỏng hoàn tất và phản hồi thô đã được lưu;
- biểu thức cùng thiết lập khớp với yêu cầu đã lưu;
- các chỉ số và kiểm tra được đọc từ phản hồi, không do mô hình dự đoán;
- phép đánh giá độc lập đã ghi rõ dữ liệu còn thiếu;
- số lần thử của cả họ được tính, để tránh chọn may mắn sau quá nhiều lần thử.

Với thất bại, thay đúng một nguyên nhân có thể kiểm tra: vòng quay cao thì thử `hump` hoặc khung dài hơn; hướng âm thì kiểm tra `reverse`; hiệu quả chỉ đến từ một nhánh thì bỏ nhánh còn lại. Alpha gần trùng không phải là khám phá mới và không được tính thành họ độc lập.

Trước khi nộp, người dùng vẫn phải kiểm tra tương quan, điều kiện cuộc thi, tính ổn định theo năm và cổng kiểm tra trên BRAIN. Hệ thống cố ý không tự nộp.
