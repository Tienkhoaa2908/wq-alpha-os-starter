# Quy tắc làm việc của dự án

## Nguồn sự thật và cách đọc

- Đọc `00_TONG_QUAN_DU_AN.md` trước.
- Sau đó đọc `docs/TRANG_THAI_HIEN_TAI.md` và `docs/generated/research_state.json` nếu đã được tạo từ máy cục bộ.
- Với luồng alpha v2 ưu tiên deterministic, đọc thêm:
  - `docs/generated/autonomous_v2_run_status.json`
  - `docs/generated/autonomous_v2_dry_run.json` nếu runner thành công
  - `docs/generated/field_semantic_audit.json`
- Nhánh LLM chỉ là tùy chọn; khi dùng thì mới đọc thêm:
  - `docs/generated/agent_packet_preview.json`
  - `docs/generated/first_v2_run_status.json`
  - `docs/generated/candidate_semantic_review.json`
  - `docs/generated/first_v2_hypothesis_dry_run.json`
- SQLite trong `data/db/` và bằng chứng trong `data/evidence/` là nguồn sự thật thực nghiệm cục bộ; các tệp trạng thái/audit trong `docs/` là bản rút gọn an toàn để đồng bộ qua GitHub.
- Chỉ mở thêm file liên quan trực tiếp đến nhiệm vụ hiện tại; không audit toàn repo nếu không cần.

## Quy tắc nghiên cứu

- Ưu tiên viết mã để máy tự chạy các bước lặp lại: sinh candidate, kiểm tra, mô phỏng, lấy bằng chứng, chấm điểm và xuất tệp.
- LLM không phải dependency bắt buộc. Luồng mặc định là Field Profiler -> Path Template -> AlphaPlan -> compiler -> gates -> simulation.
- Giữ trao đổi ngắn: không dán toàn bộ nhật ký, danh sách alpha hoặc dữ liệu lãi/lỗ; chỉ báo cáo tổng hợp, lỗi và đường dẫn tệp.
- Không tự động nộp alpha lên WorldQuant; chỉ tạo, mô phỏng, lưu bằng chứng và xuất đường dẫn.
- Không in tài khoản, mật khẩu, mã phiên hay khóa truy cập. Tệp `.env` chỉ nằm trên máy và không được đưa vào Git.
- `legacy_unverified` là dữ liệu lịch sử từ bộ sinh Gemini cũ. `screened_out` là candidate local đã bị loại trước simulation. Cả hai trạng thái chỉ giữ provenance và không được ảnh hưởng novelty, duplicate gate, subtree frequency hay empirical memory.
- Breadth batch 6 candidate chỉ được coi là đạt khi đồng thời đủ đa dạng theme, dataset và path template; không dùng 6 field khác theme nhưng cùng một cơ chế để giả tạo diversity.
- `information_staleness` chỉ được dùng khi cadence/sparsity thật sự phản ánh một quá trình cập nhật chậm hoặc theo sự kiện.
- Nếu semantic tên/mô tả có marker rõ ràng trái với profile (ví dụ ATM put/call implied-volatility nhưng theme lại là liquidity) thì phải loại trước compile/simulation.
- Không tiêu simulation mới nếu `autonomous_v2_dry_run.json` chưa qua review ở cổng hiện tại.

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
6. Với autonomous breadth, luôn stage `autonomous_v2_run_status.json`; nếu thành công phải stage cả `autonomous_v2_dry_run.json`.
7. Với nhánh LLM, stage các status/audit tương ứng nếu đã chạy.
8. Commit và push branch hiện tại lên GitHub.

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
