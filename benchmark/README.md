# Benchmark — Luật An toàn thông tin mạng 2015 & Luật An ninh mạng 2018

Tác giả bộ câu hỏi và gold: Nguyễn Thiên Bảo (2A202603861). Bộ câu hỏi được viết và kiểm chứng **trước khi chạy bất kỳ cấu hình truy xuất nào**; tiêu chí chọn cấu hình bên dưới cũng được chốt tại thời điểm này.

## File

| File | Nội dung |
|---|---|
| `questions.jsonl` | 22 câu hỏi, mỗi dòng một JSON |
| `verification.json` | Kết quả kiểm chứng tự động + `questions_sha256` để chứng minh bộ câu hỏi không đổi sau khi chạy |

Trường của mỗi câu: `id`, `split` (`dev`/`test`), `type`, `question`, `expected_answer`, `gold_source_id`, `gold_page` (số trang PDF vật lý, 1-based), `evidence_quote`, `filter` (`null` hoặc `{"year": ...}`), `filter_context`, `alternatives` (nguồn/trang hợp lệ khác, hiện không có câu nào cần), `notes` (nguồn gây nhiễu đã biết).

## Thành phần

| | Tổng | dev | test |
|---|---:|---:|---:|
| Câu hỏi | 22 | 16 | 6 |
| Có metadata filter | 5 | 3 (q14–q16) | 2 (q21, q22) |
| Gold thuộc `attt-2015` / `anm-2018` | 11 / 11 | 8 / 8 | 3 / 3 |

Loại câu (nhãn phục vụ phân tích lỗi, không phải tỷ lệ bắt buộc): `truc_tiep` 5, `dien_dat_lai` 4 (dùng từ đời thường như "email quảng cáo", "gỡ nội dung", "rò rỉ dữ liệu" thay cho thuật ngữ trong luật), `dieu_kien` 8 (điều kiện, ngoại lệ, thời hạn, thẩm quyền), `metadata_filter` 5.

## Thiết kế câu metadata filter

Hai luật trùng chủ đề nên có nhiều khái niệm xuất hiện ở cả hai: hiệu lực thi hành, định nghĩa "sự cố", "hệ thống thông tin quan trọng", hành vi bị nghiêm cấm, hợp tác quốc tế. Câu filter được viết **không nêu năm hay tên luật** trong nội dung câu hỏi; phạm vi văn bản là **input giả định do người dùng chọn trước khi truy xuất** (`filter_context`), ví dụ chọn "văn bản năm 2018" trong giao diện. Giá trị `year` lấy từ dòng "Luật số …" trên trang 1 của từng văn bản (xem `data/manifest.json`). Mỗi câu filter có một đoạn tương tự ở văn bản còn lại (ghi trong `notes`), nên không lọc thì dễ truy xuất nhầm văn bản.

Cấu hình A và B chạy mọi câu **không filter**; cấu hình C áp filter **chỉ cho 5 câu có `filter`**, 17 câu còn lại chạy giống B và được ghi rõ trong trace.

## Kiểm chứng evidence

`python scripts/verify_benchmark.py` (từ `starter/`, sau `python -m src.ingestion`) kiểm tra:

1. Mỗi `evidence_quote` nằm nguyên văn trên trang gold **sau chuẩn hóa** (NFC + gộp khoảng trắng, cùng hàm `normalize_text` của pipeline).
2. Evidence không xuất hiện nguyên văn ở trang nào khác chưa khai báo (nếu có phải thêm vào `alternatives`).
3. Giá trị filter tồn tại trong corpus và trang gold thỏa filter.
4. Câu hỏi không chứa `source_id`, số hiệu luật, năm hay tên luật của corpus.
5. Đủ ≥20 câu, ≥15 dev, ≥5 test, ≥3 câu filter trong đó ≥1 câu test.

Ngoài kiểm tra tự động, tác giả đã đọc lại từng evidence trong ngữ cảnh điều luật để xác nhận evidence **đủ** hỗ trợ đáp án, kể cả điều kiện/ngoại lệ (ví dụ q06, q07, q18 giữ nguyên mệnh đề "trừ trường hợp…"). Không có câu nào thiếu đáp án trong nguồn.

**Sửa sau đánh giá:** lần rà soát cuối phát hiện evidence của q09 (thiếu điều kiện "không vi phạm") và q13 (thiếu điểm c) chưa đủ. Hai evidence đã được mở rộng (v2) và các trace đã lưu được chấm lại. Kết quả: 0 nhãn đổi, lựa chọn trên dev không đổi. Chi tiết xem [CHANGELOG.md](CHANGELOG.md).

## Phân chia dev/test và nguy cơ rò rỉ

Tập test được chọn theo chủ đề ít trùng với dev: quyền trẻ em, hủy thông tin cá nhân, rò rỉ dữ liệu, đánh giá rủi ro hệ thống quan trọng quốc gia, nguyên tắc hợp tác quốc tế, định nghĩa hệ thống thông tin quan trọng. Nguy cơ rò rỉ còn lại:

- q18 (test) và q06 (dev) cùng ở trang 7 văn bản 2015 (khác Điều: 18 và 17).
- q20 (test) và q12 (dev) cùng ở trang 9 văn bản 2015 (khác Điều: 27 và 24).
- q19 (test) và q14 (dev) cùng ở trang 23 văn bản 2018 (khác Điều: 41 và 43).
- Câu filter test (q21, q22) cùng dạng "định nghĩa/nguyên tắc có ở cả hai luật" như câu filter dev.

Tham số chunking được chọn trước, không tinh chỉnh trên test. Nếu sau này phải xem test để sửa pipeline, việc đó sẽ được ghi vào báo cáo và kết quả test không còn được coi là kiểm tra độc lập.

## Tiêu chí chọn cấu hình (chốt trước khi chạy)

Chọn trên **dev** theo thứ tự ưu tiên:

1. Evidence Hit@3 trên 16 câu dev.
2. Hit@1 trên 16 câu dev.
3. Hit@3 và tỷ lệ tuân thủ filter trên 3 câu filter dev.
4. Tài nguyên: số chunk và thời gian ingest/embedding (ít hơn tốt hơn).

Vì mẫu nhỏ, chênh lệch **≤ 1 câu (1/16)** ở một tiêu chí được coi là hòa và chuyển sang tiêu chí kế tiếp.

*Bổ sung trước lần chạy truy xuất đầu tiên (Bước 7, chưa có kết quả benchmark nào):* nếu vẫn hòa sau cả bốn tiêu chí, so lại các tiêu chí theo cùng thứ tự bằng **giá trị thô** (không ngưỡng hòa); nếu vẫn hòa, chọn cấu hình đơn giản hơn theo thứ tự A → B → C. Luật này được hiện thực trong `select_strategy` của `starter/src/run.py`, áp dụng tự động trên dev và ghi từng bước vào `results/selection.json`. Sau khi chọn, cấu hình được cố định rồi mới chạy đánh giá test; cả ba cấu hình vẫn được báo cáo trên test để so sánh, nhưng kết quả test không được dùng để đổi lựa chọn.
