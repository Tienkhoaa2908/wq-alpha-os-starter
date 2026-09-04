# Đánh giá hiện trạng và hướng tối ưu

## Vì sao bản cũ sinh alpha yếu

Bản cũ có 2.131 trường nhưng chỉ hai thí nghiệm, không có liên kết chắc chắn từ ứng viên đến kết quả. Trong 1.267 ứng viên cũ không có biểu thức dùng `hump`, không có khung 504 ngày và chỉ bốn biểu thức dùng `normalize`. Câu nhắc lại ép phối hợp nhiều trường, trong khi alpha mẫu tốt chỉ cần một trường và một cơ chế rõ ràng. Vì không có vòng phản hồi thật, Gemini chủ yếu ghép chuỗi nhìn có vẻ hợp lệ, không học được phép biến đổi nào cải thiện Sharpe (lợi nhuận điều chỉnh theo rủi ro), Fitness (độ phù hợp tổng hợp), vòng quay hay tương quan.

Một số danh mục cũ cũng thiếu: nhóm Mô hình nhà phân tích chỉ có 300 trên 3.256 trường được báo cáo, nhóm Cơ bản doanh nghiệp có 836 trên 886, còn nhóm Vũ trụ chưa có trường. Vì vậy danh mục cũ chỉ là điểm khởi đầu và phải được đồng bộ lại từ chính tài khoản.

## Trạng thái sau khi tổ chức lại

- Mã giao diện trang mạng và các bộ sinh chuỗi cũ đã bỏ khỏi nhánh hiện tại.
- Cơ sở dữ liệu cũ còn nguyên để truy hồi; 1.267 biểu thức cũ đã vào bộ nhớ chống trùng dưới trạng thái chưa kiểm chứng.
- Bộ phân tích biểu thức hiểu toán tử lồng nhau, tham số có tên, kiểu `MATRIX`, `VECTOR`, trường nhóm và giới hạn độ phức tạp.
- Tám thí nghiệm nền tạo thành một họ có cha–con: mẫu gốc, hai phép loại bỏ nhánh và năm phép thử độ nhạy.
- Mô phỏng lưu yêu cầu, phản hồi, thống kê theo năm, PnL (lãi và lỗ theo thời gian) và tương quan tự thân. Chỉ lớp đánh giá độc lập mới được nâng hạng.
- Có đầu nối Qwen qua Ollama và gói câu nhắc để Codex sinh đề xuất; mọi đầu ra đều phải đi qua cùng cổng cú pháp và chống trùng.

## Thứ tự tối ưu đúng

1. Thêm thông tin BRAIN vào `.env`, đồng bộ lại toàn bộ danh mục USA/TOP3000/D1.
2. Mô phỏng tám alpha nền với cùng một bộ thiết lập; không đổi đồng thời cả công thức lẫn thiết lập.
3. So mẫu gốc với hai phép loại bỏ để biết phối hợp 504/252 có tạo giá trị thật hay chỉ tăng độ phức tạp.
4. So các phép thử trọng số, `hump` và khung dài bằng chỉ số, thống kê theo năm và tương quan.
5. Cho tác tử sinh phép biến đổi từ nguyên nhân đã quan sát. Kết quả âm mới kiểm tra đảo dấu; vòng quay cao mới thêm hãm; Fitness thấp mới kéo dài khung.
6. Mở rộng sang trường cùng chủ đề có độ phủ cao, rồi mới sang họ kinh tế khác. Mỗi họ giữ tổng số lần thử để thấy rủi ro chọn lọc quá mức.

Không có mô hình ngôn ngữ nào tự bảo đảm alpha có thể nộp. Chất lượng đến từ giả thuyết, thí nghiệm có đối chứng, dữ liệu BRAIN thật, chống trùng theo cấu trúc và kỷ luật không học từ kết quả lỗi.
