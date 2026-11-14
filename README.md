# Bài nộp Day 06 — Nguyễn Thiên Bảo (2A202603861)

Pipeline ingestion và benchmark truy xuất trên **Luật An toàn thông tin mạng 2015** và **Luật An ninh mạng 2018** (47 trang nội dung). Ba cấu hình được so sánh: A chunk cố định, B chunk theo Điều/khoản, C là B kèm filter `year`. Embedding dùng `intfloat/multilingual-e5-base` (local, 768 chiều), lưu và truy xuất bằng PostgreSQL + pgvector. Báo cáo: [report/individual/2A202603861_NguyenThienBao.md](report/individual/2A202603861_NguyenThienBao.md).

| | Hit@1 dev | Hit@3 dev | Hit@1 test | Hit@3 test | Coherence /2 | Grounding /2 |
|---|---|---|---|---|---|---|
| A | 10/16 | 11/16 | 0/6 | 3/6 | 1,00 | 1,67 |
| B | 11/16 | 14/16 | 6/6 | 6/6 | 2,00 | 2,00 |
| **C (chọn trên dev)** | 12/16 | 15/16 | 6/6 | 6/6 | 2,00 | 2,00 |

### Cài đặt

Yêu cầu: Docker Desktop, Python 3.11–3.14. GPU là tùy chọn; nếu không có, model tự chạy trên CPU. Chạy các lệnh từ thư mục `starter/` (Windows PowerShell):

```powershell
cd starter
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
# GPU CUDA 12.8 (máy tác giả): python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
Copy-Item .env.example .env          # đặt EMBEDDING_MODEL=intfloat/multilingual-e5-base (để trống cũng dùng model này)
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py        # kỳ vọng: Setup OK
```

Lần chạy đầu sẽ tải model e5 (~1,1 GB) từ Hugging Face, không cần API key, chi phí 0.

### Chạy lại toàn bộ (từ `starter/`)

```powershell
python scripts/build_manifest.py     # data/manifest.json: trang, ký tự, SHA-256, giấy phép
python -m src.ingestion              # results/pages.jsonl, results/ingest_log.json
python -m src.chunking               # results/chunks_A|B.jsonl, results/chunk_stats.json
python scripts/verify_benchmark.py   # benchmark/verification.json (kiểm chứng evidence, khóa SHA-256)
python -m src.index                  # nạp 3 index A/B/C vào pgvector, results/index_log.json (chạy lại không nhân đôi)
python scripts/test_store.py         # kiểm thử nạp lại, tài liệu thay đổi, filter -> results/store_test.json
python -m src.run --phase dev        # trace + chỉ số dev, chọn cấu hình -> results/selection.json
python -m src.run --phase test       # trace + chỉ số test với lựa chọn đã khóa -> results/metrics.json
python scripts/build_audit.py        # bảng nhãn thủ công + tổng hợp từ results/manual_labels.json
python scripts/rescore_traces.py     # (chỉ khi sửa gold) chấm lại trace đã lưu, không truy xuất lại -> results/rescore_log.json
```

Bộ câu hỏi đã được sửa gold một lần **sau khi đánh giá**: mở rộng evidence của q09 và q13, chỉ số không đổi. Xem [benchmark/CHANGELOG.md](benchmark/CHANGELOG.md).

Lưu ý: `--phase dev` từ chối ghi đè `selection.json` sau khi test đã được đánh giá. Muốn chạy lại từ đầu thì xóa `results/selection.json` trước.

### Cấu trúc bài nộp

```text
STUDENT.md                          thông tin học viên
data/manifest.json, data/raw/       2 PDF nguồn + manifest (nguồn, giấy phép, trang tính, SHA-256)
benchmark/                          22 câu (16 dev/6 test), README thiết kế + tiêu chí chọn, verification.json
artifacts/experiment_log.csv        cấu hình, giả thuyết và kết quả A/B/C
starter/src/                        pipeline: ingestion, chunking, embeddings, store, index, evaluation, run
starter/scripts/                    manifest, kiểm chứng benchmark, kiểm thử store, build audit
results/                            log ingest/index, chunk stats, trace top-3, metrics, selection, nhãn audit
report/individual/2A202603861_NguyenThienBao.md
```

Đường dẫn dữ liệu: PDF nằm ở `data/raw/`; manifest ghi URL gốc để tải lại. Không commit `.env` hay `.venv`.

---

# Đề bài gốc — Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
