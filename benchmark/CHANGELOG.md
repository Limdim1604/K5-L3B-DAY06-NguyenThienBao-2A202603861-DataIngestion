# Lịch sử thay đổi bộ câu hỏi

## v2 — 2026-11-14, sửa gold **sau khi đã đánh giá**

Khi rà soát cuối, tôi phát hiện hai câu dev có evidence chưa bao phủ hết điều kiện/ngoại lệ đã nêu trong `expected_answer`. Như vậy chưa đạt yêu cầu "evidence đủ hỗ trợ đáp án, kể cả điều kiện/ngoại lệ" của BENCHMARK.md.

| Câu | Thiếu ở v1 | Sửa ở v2 |
|---|---|---|
| q09 (dev) | Điều kiện "Doanh nghiệp không vi phạm quy định của pháp luật về kinh doanh sản phẩm, dịch vụ an toàn thông tin mạng" | Evidence bắt đầu từ đầu khoản 3 Điều 45 (trang 19) |
| q13 (dev) | Điểm c) "Các trường hợp khác theo quy định của pháp luật." | Evidence kéo dài tới hết điểm c) khoản 4 Điều 33 (trang 13) |

Câu hỏi, đáp án, nguồn, trang, split và filter của cả hai câu **không đổi**. Không có câu test nào bị sửa.

**Cách cập nhật:**

1. Sửa `questions.jsonl`, đánh dấu trường `gold_revision` ở hai câu.
2. Chạy lại `scripts/verify_benchmark.py`: 0 lỗi. Evidence mới vẫn nằm trên trang gold và không trùng trang nào khác. Hash v1 là `78d322ff077a1dde95d1b3e815277e5589f4837242d1290bd8e6fe43021ab117`; hash v2 nằm trong `verification.json`.
3. **Không chạy lại truy xuất**: câu hỏi và vector truy vấn không đổi, tìm kiếm là exact. `scripts/rescore_traces.py` chấm lại top-3 đã lưu bằng gold v2.
4. Kết quả (`results/rescore_log.json`):
   - **0 nhãn thay đổi**; Hit@1, Hit@3, tuân thủ filter trên dev và test giống hệt v1.
   - Áp dụng lại luật chọn trên dev: vẫn chọn **C**.
   - Chỉ số chẩn đoán "evidence dev nằm trọn trong một chunk" vẫn là A 13/16 (thiếu q06, q07, q13), B 16/16.
5. Nhãn thủ công không bị ảnh hưởng, vì grounding và metadata chỉ chấm trên câu test, còn coherence không phụ thuộc vào câu hỏi.

Vì đây là sửa gold sau khi đã xem kết quả, việc sửa được ghi rõ trong báo cáo. Hai câu được sửa đều thuộc dev và kết quả không đổi, nên lựa chọn cấu hình và đánh giá test không bị ảnh hưởng.
