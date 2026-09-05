# Quy tắc làm việc của dự án

## Nguồn sự thật và cách đọc

- Đọc `00_TONG_QUAN_DU_AN.md` trước.
- Sau đó đọc `docs/TRANG_THAI_HIEN_TAI.md` và `docs/generated/research_state.json` nếu đã được tạo từ máy cục bộ.
- Khi làm việc với bộ sinh alpha v2, đọc thêm:
  - `docs/generated/field_semantic_audit.json`
  - `docs/generated/agent_packet_preview.json`
  - `docs/generated/first_v2_run_status.json` nếu đang chạy vòng discovery đầu tiên; file này là trạng thái runtime đã làm sạch và phải được ưu tiên để chẩn đoán lần chạy gần nhất.
  - `docs/generated/candidate_semantic_review.json` và `docs/generated/first_v2_hypothesis_dry_run.json` khi chúng đã tồn tại.
- SQLite trong `data/db/` và bằng chứng trong `data/evidence/` là nguồn sự thật thực nghiệm cục bộ; các tệp trạng thái/audit trong `docs/` là bản rút gọn an toàn để đồng bộ qua GitHub.
- Chỉ mở thêm file liên quan trực tiếp đến nhiệm vụ hiện tại; không audit toàn repo nếu không cần.

## Quy tắc nghiên cứu

- Ưu tiên viết mã để máy tự chạy các bước lặp lại: sinh đề xuất, kiểm tra, mô phỏng, lấy bằng chứng, chấm điểm và xuất tệp.
- Giữ trao đổi ngắn: không dán toàn bộ nhật ký, danh sách alpha hoặc dữ liệu lãi/lỗ; chỉ báo cáo tổng hợp, lỗi và đường dẫn tệp.
- Không tự động nộp alpha lên WorldQuant; chỉ tạo, mô phỏng, lưu bằng chứng và xuất đường dẫn.
- Không in tài khoản, mật khẩu, mã phiên hay khóa truy cập. Tệp `.env` chỉ nằm trên máy và không được đưa vào Git.
- `legacy_unverified` là dữ liệu lịch sử từ bộ sinh Gemini cũ. Giữ record để truy vết nhưng tuyệt đối không cho chúng ảnh hưởng novelty, subtree frequency, empirical motif stats, scheduler hay trial memory của research v2.
- Không tiêu lượt simulation mới trước khi `field_semantic_audit.json` và `agent_packet_preview.json` đã được kiểm tra ở cổng hiện tại.
- Gemini runtime không được phụ thuộc cứng vào một model ID dễ hết hạn. Runner phải resolve model hỗ trợ `generateContent` bằng chính API key; model thực tế được chọn phải xuất hiện trong `first_v2_run_status.json` và provenance của lần chạy.

## Quy tắc hoàn tất mọi tác vụ

Một tác vụ chưa được coi là hoàn tất nếu thay đổi chỉ nằm trên máy hoặc chưa cập nhật file điều phối.

Sau mọi thay đổi có ý nghĩa:

1. Chạy `python -m unittest discover -s tests -v`.
2. Nếu thay đổi ảnh hưởng tri thức/nghiên cứu, chạy `alpha-os knowledge build`.
3. Cập nhật `00_TONG_QUAN_DU_AN.md` nếu kiến trúc, quy tắc hoặc kế hoạch chung thay đổi.
4. Xuất audit cục bộ an toàn bằng `python .\scripts\export_research_audit.py` để cập nhật:
   - `docs/generated/field_semantic_audit.json`
   - `docs/generated/agent_packet_preview.json`
5. Xuất snapshot cục bộ an toàn bằng `python .\scripts\export_research_state.py` để cập nhật:
   - `docs/TRANG_THAI_HIEN_TAI.md`
   - `docs/generated/research_state.json`
6. Với workflow discovery đầu tiên, luôn stage cả `docs/generated/first_v2_run_status.json`; nếu run thành công còn phải có `candidate_semantic_review.json` và `first_v2_hypothesis_dry_run.json`.
7. Commit và push branch hiện tại lên GitHub.

Ưu tiên dùng một lệnh:

```powershell
.\scripts\finalize_task.ps1 -Message "<commit message>"
```

Script này chạy test, rebuild knowledge, xuất audit + snapshot, stage các file source-controlled, commit và push branch hiện tại. Không stage `.env`, SQLite, evidence hoặc exports runtime.

Nếu chỉ sửa tài liệu hoặc thay đổi không cần rebuild knowledge:

```powershell
.\scripts\finalize_task.ps1 -Message "<commit message>" -NoKnowledgeBuild
```

Không dùng `-NoPush` trong workflow bình thường. Chỉ dùng khi đang debug và chưa muốn công khai checkpoint.
