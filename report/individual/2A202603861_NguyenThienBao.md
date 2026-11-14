# Báo cáo cá nhân — Day 6

**Họ tên:** Nguyễn Thiên Bảo · **MSSV:** 2A202603861 · **Lớp:** L3B
**Chủ đề:** Truy xuất điều luật trong Luật An toàn thông tin mạng 2015 và Luật An ninh mạng 2018 (văn bản gốc khi ban hành).

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Corpus gồm 2 văn bản luật PDF có lớp text:
    - `attt-2015`: Luật An toàn thông tin mạng 86/2015/QH13, 24 trang vật lý.
    - `anm-2018`: Luật An ninh mạng 24/2018/QH14, 24 trang vật lý.
  - Văn bản quy phạm pháp luật không thuộc phạm vi bảo hộ quyền tác giả (Điều 15 khoản 2 Luật Sở hữu trí tuệ), nên được phép xử lý và đưa vào repo. Hai bản PDF là bản dàn trang lại của bên thứ ba (WTO và một trường đại học), không phải bản Công báo. Tôi đã kiểm tra đủ 54/54 và 43/43 Điều nhưng chưa đối chiếu từng chữ với bản Công báo.
  - **Quy tắc tính trang:** một trang được tính khi text trích xuất (NFC, strip) có ≥ 300 ký tự; trang dưới ngưỡng được kiểm tra thủ công và ghi lý do loại. Kết quả là **47 trang nội dung**: 24 + 23. Trang 24 của `anm-2018` bị loại vì chỉ có chữ ký.
  - Văn bản không có trang bìa, mục lục hay tài liệu tham khảo riêng. Trang 1 chứa Điều 1–2 nên được tính.
  - Chi tiết nằm trong `data/manifest.json` (URL, SHA-256, ngày truy cập 2026-11-14, số ký tự từng trang), tạo bằng `starter/scripts/build_manifest.py`.
  - **Lưu ý hiệu lực:** cả hai luật đã hết hiệu lực từ 01/07/2026, do Luật An ninh mạng 116/2025/QH15 thay thế. Benchmark chỉ hỏi về nội dung văn bản, không hỏi luật nào đang có hiệu lực.

- **Chuẩn hóa, lỗi và giới hạn** (`starter/src/ingestion.py`):
  - **Các bước chuẩn hóa:** Unicode NFC; đổi các loại khoảng trắng lạ thành dấu cách; bỏ ký tự vô hình và soft hyphen; bỏ dòng gạch `-----`; nối các dòng bị PDF ngắt thành đoạn logic.
  - **Nhận diện cấu trúc:** đoạn mới chỉ bắt đầu ở `Chương`, `Mục`, `Điều N.`, khoản `N.`, điểm `a)` hoặc tên chương viết hoa. Heading Điều dài nhiều dòng được nhận diện bằng **font in đậm** lấy từ PDF. Tôi đã kiểm chứng rằng các đoạn text kèm thông tin font ghép lại khớp từng ký tự với `extract_text()` trên cả 48 trang.
  - **Log** (`results/ingest_log.json`): 0 trang rỗng, 0 lỗi, 1 trang bị loại; nhận diện đủ 54 + 43 Điều và 8 + 7 Chương.
  - **Hai lỗi phát hiện khi làm và đã sửa trước khi chạy benchmark:**
    1. Regex `^` không bật chế độ MULTILINE nên đếm thiếu Chương.
    2. Heading Điều dính câu nội dung đầu tiên. Tôi thử dùng độ dài dòng nhưng không tách được, nên chuyển sang nhận diện font in đậm.
  - **Giới hạn:** chunk không vượt qua ranh giới trang (để truy được đúng một trang nguồn), nên câu bị ngắt giữa hai trang sẽ nằm ở hai chunk. Không cần OCR vì PDF có lớp text.

- **Embedding, vector store, lệnh chạy và chi phí:**
  - **Embedding:** `intfloat/multilingual-e5-base`, revision `d128750597153bb5987e10b1c3493a34e5a4502a`, 768 chiều, chạy local bằng sentence-transformers 6.3.0, torch 2.11.0+cu128 trên RTX 3050 Ti. Thêm tiền tố `query: `/`passage: ` theo tài liệu của model, chuẩn hóa L2. Không có fallback sang vector giả.
  - **Vector store:** PostgreSQL 16.16 + pgvector 0.8.7 chạy bằng Docker (`starter/docker-compose.yml`). Một bảng `chunks`, khóa chính `(strategy, chunk_id)`. Metric cosine `<=>`, tìm kiếm **chính xác** (không dùng chỉ mục ANN, nên filter không làm số kết quả ít hơn 3).
  - **Lệnh chạy:** `python -m src.ingestion`, `python -m src.chunking`, `python scripts/verify_benchmark.py`, `python -m src.index`, `python -m src.run --phase dev`, `python -m src.run --phase test`, `python scripts/build_audit.py`. Thứ tự đầy đủ xem `README.md`.
  - **Phiên bản:** Python 3.12.2, torch 2.11.0+cu128, transformers 5.23.0, sentence-transformers 6.3.0, psycopg 3.3.8, pypdf 6.21.4, Docker image `pgvector/pgvector:0.8.7-pg16`.
  - **Thời điểm chạy (UTC):** truy xuất dev 2026-11-14 03:35:18, test 03:35:50.
  - **Tái lập và tính tất định:** không cần seed vì embedding và tìm kiếm exact đều tất định. Khi truy xuất lại toàn bộ 22 câu × 3 cấu hình lúc rà soát cuối, cả 66/66 trace cho top-3 giống hệt. Chạy lại ingestion và chunking cho file đầu ra giống từng byte.
  - **Chi phí:** 0 USD (không gọi API trả phí).
  - **Thời gian:** ingest 1,24 s; lần nạp đầu tổng 21,2 s, gồm cả tải model.

- **Metadata:**
  - **Bắt buộc:** `document_id`, `source` (đường dẫn PDF), `page` (trang PDF vật lý, bắt đầu từ 1).
  - **Trường lọc:** `year` (int, 2015/2018), lấy từ dòng "Luật số …" trên trang 1. Lý do chọn: hai luật trùng chủ đề và nhiều khái niệm xuất hiện ở cả hai (hiệu lực, "sự cố", "hệ thống thông tin quan trọng", hành vi bị cấm, hợp tác quốc tế), nên người dùng cần giới hạn phạm vi văn bản.
  - **Trường bổ trợ truy vết:** `law_number`, `chapter`, `article`, `article_title`, `articles` (các Điều chunk phủ), `char_start`/`char_end`. Chương/Điều lấy từ chính text, kể cả Điều kéo sang trang sau.

## Cấu hình và benchmark

- **A / B / C:**
  - **A:** cửa sổ cố định 500 ký tự, overlap 50, cắt tại khoảng trắng gần nhất, không lọc. Kết quả 293 chunk.
  - **B:** chunk theo cấu trúc, mỗi Điều một nhóm, khoản giữ chung với các điểm của nó, gom tối đa 1000 ký tự. Chunk nối tiếp được gắn dòng "Điều N. <tên> (tiếp)". Bỏ 9 chunk chỉ có heading nằm ở cuối trang (nội dung ở trang sau và đã được gắn tiền tố). Không lọc. Kết quả 204 chunk.
  - **C:** cùng chunk và cùng vector với B, **khác biệt duy nhất** là `WHERE year = …` cho 5 câu có filter. 17 câu còn lại chạy không lọc và được ghi `filter_applied = null` trong trace.
  - **Lưu ý:** A–B khác cả cách cắt lẫn kích thước (500 so với 1000 ký tự), nên chênh lệch kết quả không quy riêng cho một yếu tố. B–C là so sánh có kiểm soát.
  - Cả ba dùng cùng corpus, model, store, metric và bộ câu hỏi.

- **Benchmark ≥ 20 câu** (`benchmark/questions.jsonl`):
  - 22 câu, **16 dev / 6 test**, chia trước khi chạy.
  - Loại câu: trực tiếp 5, diễn đạt lại 4, điều kiện/ngoại lệ 8, metadata filter 5.
  - Câu filter: 3 ở dev (q14–q16), 2 ở test (q21, q22). Nội dung câu filter không nêu năm hay tên luật; phạm vi là **đầu vào giả định do người dùng chọn trước khi truy xuất**.
  - Mỗi câu có đáp án, nguồn, trang và evidence. `scripts/verify_benchmark.py` kiểm tra:
    - Evidence có nguyên văn trên trang gold sau chuẩn hóa, và không xuất hiện ở trang khác chưa khai báo.
    - Giá trị filter tồn tại và trang gold thỏa filter.
    - Câu hỏi không lộ năm hay tên luật.
  - Kết quả kiểm tra: 0 lỗi; bộ câu v1 có SHA-256 `78d322ff…` lúc chạy truy xuất. `run.py` từ chối chạy nếu bộ câu đã đổi sau khi kiểm chứng.
  - **Sửa gold sau đánh giá (v2):** khi rà soát cuối, tôi thấy evidence của q09 thiếu điều kiện "doanh nghiệp không vi phạm…" và evidence của q13 thiếu điểm c) "các trường hợp khác theo quy định của pháp luật", trong khi đáp án có nêu. Tôi mở rộng hai evidence (câu hỏi, đáp án, trang không đổi), kiểm chứng lại, và chấm lại các trace đã lưu bằng `scripts/rescore_traces.py`, không chạy lại truy xuất. Kết quả: 0 nhãn thay đổi, mọi chỉ số giữ nguyên, áp lại luật chọn trên dev vẫn ra C. Hai câu đều thuộc dev nên không ảnh hưởng đến đánh giá test. Chi tiết trong `benchmark/CHANGELOG.md` và `results/rescore_log.json`.
  - Nguy cơ rò rỉ dev/test (cùng trang khác Điều) được ghi trong `benchmark/README.md`.

- **Tiêu chí chọn chiến lược** (chốt trước khi xem test, áp dụng tự động trong `run.py`):
  - Thứ tự ưu tiên: dev Hit@3 → dev Hit@1 → Hit@3 trên câu filter dev → tỷ lệ tuân thủ filter → số chunk.
  - Chênh lệch ≤ 1 câu được coi là hòa.
  - Nếu vẫn hòa: so lại theo giá trị thô, rồi chọn cấu hình đơn giản hơn (A → B → C). Luật phá hòa này được bổ sung trước lần chạy truy xuất đầu tiên.
  - **Kết quả:** dev chọn **C**. B và C hòa ở 3 tiêu chí đầu (14 so với 15, 11 so với 12, 2 so với 3); C thắng ở tiêu chí tuân thủ filter (3/3 so với 0/3). Từng bước lưu trong `results/selection.json`. Lựa chọn được khóa trước khi chạy test.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 10/16 | 11/16 | 293 | embed 2,41 s + upsert 0,34 s; truy vấn TB 27,4 ms | 0 |
| A | test | 0/6 | 3/6 | 293 | truy vấn TB 34,9 ms | 0 |
| B | dev | 11/16 | 14/16 | 204 | embed 1,94 s + upsert 0,21 s; truy vấn TB 25,0 ms | 0 |
| B | test | 6/6 | 6/6 | 204 | truy vấn TB 24,1 ms | 0 |
| C | dev | **12/16** | **15/16** | 204 | embed 0 s (dùng lại vector B) + upsert 0,24 s; truy vấn TB 19,2 ms | 0 |
| C | test | **6/6** | **6/6** | 204 | truy vấn TB 27,3 ms | 0 |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,00 (n=10; 0:2, 1:6, 2:2) | 18/18 | dev 0/3, test 0/2 | 1 / 0 / 5 — 1,67 |
| B | 2,00 (n=10) | 18/18 | dev 0/3, test 0/2 | 0 / 0 / 6 — 2,00 |
| C | 2,00 (n=10, cùng chunk với B) | 18/18 | dev 3/3, test 2/2 | 0 / 0 / 6 — 2,00 |

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- **Trace top-3:** `results/traces_dev.jsonl`, `results/traces_test.jsonl`. Mỗi bản ghi có câu hỏi, filter đã áp dụng, chunk ID, text, score, metadata, cờ trúng trang gold, cờ chứa evidence và thời gian truy vấn.
- **Chỉ số:** `results/metrics.json`.
- **Nhãn thủ công:** `results/manual_labels.json`, kèm 3 bảng `results/manual_audit_*.csv` và tổng hợp `results/manual_audit_summary.json`.
- **Coherence:** sắp 47 trang theo `(document_id, page)`, lấy trang ở chỉ số 0, 5, …, 45, chọn ký tự giữa trang, rồi chấm chunk chứa vị trí đó. Quy tắc chốt trước khi đọc chunk.
- **Metadata:** 6 câu test × top-3 × 3 cấu hình = 54 bản ghi. Mỗi bản ghi được đối chiếu tự động với text PDF thô (text có đúng trang, `year`/`law_number` khớp) và đọc tay để kiểm tra `article`.
- **Grounding:** 6 câu test × 3 cấu hình, xét top-3 chung.
- Người chấm là chính tôi. Nhãn được chấm sau khi đã biết cấu hình của từng chunk, nên có nguy cơ thiên lệch.

## Phân tích và kết luận

- **So sánh A–B (đổi cách chunk):**
  - B hơn A ở Hit@3 dev (14/16 so với 11/16) và test (6/6 so với 3/6), coherence (2,00 so với 1,00) và grounding (2,00 so với 1,67), đồng thời ít chunk hơn (204 so với 293).
  - Nguyên nhân chính: cửa sổ 500 ký tự cắt ngang khoản/điểm. Ngay trước khi embed, chỉ 13/16 evidence dev nằm trọn trong một chunk A, so với 16/16 ở B.
  - Hit@1 test của A là 0/6, thấp bất thường. Lý do: trang gold thường có nhiều chunk A gần giống nhau, chunk hạng 1 đúng trang nhưng thiếu một phần evidence (gold page@3 của A trên test là 5/6).
  - **A không thua mọi mặt.** Ở q04 (dev), chunk A ngắn tìm được evidence ở hạng 2, còn B và C trượt top-3 vì chunk Điều 26 dài làm loãng nội dung.

- **So sánh B–C (chỉ đổi filter):**
  - Trên 17 câu không filter, B và C trả về giống hệt nhau.
  - Trên 5 câu filter: Hit@3 tăng từ 2/3 lên 3/3 ở dev (giữ 2/2 ở test). Tuân thủ filter tăng từ 0/3 lên 3/3 ở dev và từ 0/2 lên 2/2 ở test.
  - Chunk của văn bản ngoài phạm vi trong top-3 (test) giảm từ 2 câu xuống 0.
  - Đánh đổi: không tốn thêm tài nguyên, nhưng C phụ thuộc vào việc người dùng chọn đúng phạm vi. Nếu chọn sai năm, C chắc chắn trượt.

- **Hai ví dụ sai:**
  1. **q18 (test), cấu hình A.** Câu hỏi: "Khi nào phải hủy thông tin cá nhân đã lưu trữ?". Gold là `attt-2015` trang 7, Điều 18 khoản 3. Cả 3 chunk top-3 đều đúng trang 7 nhưng evidence bị tách đôi: `attt-2015-p07-003` dừng ở "…hết thời hạn lưu trữ", còn mệnh đề "và thông báo cho chủ thể… trừ trường hợp pháp luật có quy định khác" nằm ở `attt-2015-p07-004`. Hit@3 tự động bằng 0. Chấm grounding thủ công vẫn được 2, vì hai chunk nối liền nhau nhờ overlap. Đây là chỗ thước đo tự động khắt khe hơn người chấm. B trả về trọn khoản 3 ở hạng 1 (`attt-2015-p07-002`).
  2. **q16 (dev), cấu hình A và B.** Câu hỏi: "Sự cố được hiểu là gì?", phạm vi người dùng chọn là văn bản 2015. Không có filter, B đưa định nghĩa "Sự cố an ninh mạng" của `anm-2018` (trang 2, `anm-2018-p02-002`) lên hạng 1 và không có chunk gold nào trong top-3. C lọc `year=2015` thì lấy được `attt-2015-p01-004` (Điều 3 khoản 7) ở hạng 3. Ví dụ tương tự là q14: B xếp ngày hiệu lực của luật 2015 (`attt-2015-p24-001`) trên ngày hiệu lực của luật 2018.
  - Ví dụ thứ ba nằm trong trace: q19 (test) với cấu hình A được grounding 0. Top-3 không có điểm c) khoản 1 Điều 41 về nghĩa vụ khi lộ dữ liệu, vì điểm này nằm ở đầu trang 23 còn câu dẫn ở cuối trang 22.

- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - Chọn **C**: chunk theo Điều/khoản cộng filter `year` khi người dùng đã xác định văn bản.
  - Phù hợp với corpus văn bản pháp luật có cấu trúc Chương/Điều/khoản rõ ràng và nhiều văn bản trùng chủ đề.
  - Đánh đổi:
    - Chunk dài hơn (trung bình 647 ký tự, tối đa 1216) nên có thể pha loãng khoản ngắn trong Điều dài (q04).
    - Filter chỉ giúp khi người dùng cung cấp phạm vi trước.
    - Dòng tiền tố "(tiếp)" là text tổng hợp, không có nguyên văn trên trang.
  - Kết quả chỉ đúng với corpus này. Tôi không coi đây là chiến lược tốt nhất nói chung.

- **Hạn chế:**
  - **Dữ liệu:** chỉ 2 văn bản nên `year` thực chất trùng với `document_id`; bản PDF của bên thứ ba chưa đối chiếu từng chữ; luật đã hết hiệu lực.
  - **Nhãn:** một người chấm (tác giả), biết cấu hình khi chấm, không có người chấm thứ hai để đo độ đồng thuận. B và C được 2,00 ở mọi vị trí coherence có thể phản ánh thiên lệch đó.
  - **Mẫu nhỏ:** test chỉ có 6 câu (2 câu filter) nên 6/6 của B và C không phân biệt được hai cấu hình và không đủ cơ sở để khái quát. Chênh lệch 1 câu trên dev là 6,25 điểm phần trăm.
  - **Rò rỉ dev/test:** một số câu test nằm cùng trang với câu dev (q18/q06, q20/q12, q19/q14). Tôi có xem lỗi dev trước khi chạy test nhưng không sửa pipeline.
  - **Đo thời gian:** trên một máy, chỉ đo một lần, có tính thời gian tải model. Thời gian truy vấn (19–35 ms) gồm cả mở kết nối PostgreSQL mỗi lần, nên chênh lệch giữa các cấu hình chủ yếu là nhiễu. Chi phí 0 vì chạy local; chưa tính điện và phần cứng.

- **Nếu làm lại hoặc mở rộng:**
  1. Tách riêng hai yếu tố kích thước và cấu trúc ở A–B, ví dụ thêm cấu hình B' theo cấu trúc nhưng tối đa 500 ký tự.
  2. Cho phép chunk B vượt ranh giới trang nhưng lưu danh sách trang, để không cắt Điều ở chân trang (lỗi q19 của A).
  3. Thêm hybrid BM25 cho các câu có con số, thời hạn (như "24 giờ" ở q04), chọn tham số trên dev.
  4. Mở rộng test lên ≥ 15 câu, thêm luật 2025 để `year` có 3 giá trị độc lập với `document_id`, và nhờ người chấm thứ hai để đo độ đồng thuận.

## Công cụ AI và cách kiểm tra

Tôi dùng Claude (Anthropic) để hỗ trợ viết code, soạn nháp benchmark, nhãn thủ công và báo cáo. Tôi chịu trách nhiệm đọc hiểu, kiểm tra và duyệt từng bước (chọn corpus, chọn model, bộ câu hỏi, cách chunk, nhãn audit), một vài lần có đưa ra lỗi và yêu cầu AI chỉnh lại khi phát hiện lỗi hoặc chưa ưng ý. Cách kiểm tra:

- Mọi số liệu trong báo cáo đều lấy từ file kết quả do chính pipeline sinh ra (`results/`), không tự điền.
- Evidence được kiểm chứng bằng script trên text đã chuẩn hóa.
- Metadata được đối chiếu với text PDF thô.
- Tôi đã đọc lại bộ câu hỏi và các bảng nhãn trước khi chạy hoặc chốt.
