"""Build data/manifest.json from the PDFs in data/raw.

Bibliographic fields (title, law number, dates, URL, licence) are entered by hand
from the documents themselves; page counts, character counts and hashes are
computed here so the manifest can be regenerated and checked.

Page counting rule: a physical page is counted as a content page when its
extracted text (Unicode NFC, whitespace-trimmed) has at least
MIN_CONTENT_CHARS characters. Pages below the threshold are listed as excluded
together with the reason found on manual inspection.

Run from starter/:  python scripts/build_manifest.py
"""
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "manifest.json"
ACCESSED_AT = "2026-11-14"
MIN_CONTENT_CHARS = 300

LICENSE = (
    "Văn bản quy phạm pháp luật không thuộc phạm vi bảo hộ quyền tác giả "
    "(Điều 15 khoản 2 Luật Sở hữu trí tuệ số 50/2005/QH11, sửa đổi, bổ sung). "
    "Được phép xử lý và tái phân phối; bản PDF là bản dàn trang lại của bên thứ ba, "
    "không phải bản Công báo."
)

SOURCES = [
    {
        "source_id": "attt-2015",
        "file": "luat-attt-86-2015-qh13.pdf",
        "title": "Luật An toàn thông tin mạng",
        "law_number": "86/2015/QH13",
        "issuer": "Quốc hội khóa XIII, kỳ họp thứ 10",
        "issued_date": "2015-11-19",
        "effective_date_stated_in_text": "2016-07-01",
        "year": 2015,
        "source_path_or_url": (
            "https://www.importlicensing.wto.org/sites/default/files/members/134/"
            "Law%20No.86_2015%20-%20Cyber-information%20security%20%28VIE%29_19.11.2015.pdf"
        ),
        "version_note": (
            "Văn bản gốc khi ban hành (8 chương, 54 điều). Không bao gồm sửa đổi theo "
            "Luật 35/2018/QH14. Đã hết hiệu lực từ 2026-07-01 theo Điều 44 Luật An ninh mạng "
            "116/2025/QH15 (nguồn: tra cứu web ngày truy cập). Benchmark hỏi theo nội dung văn bản này, "
            "không hỏi hiệu lực pháp lý hiện hành."
        ),
        "excluded_pages": {},
    },
    {
        "source_id": "anm-2018",
        "file": "luat-anm-24-2018-qh14.pdf",
        "title": "Luật An ninh mạng",
        "law_number": "24/2018/QH14",
        "issuer": "Quốc hội khóa XIV, kỳ họp thứ 5",
        "issued_date": "2018-06-12",
        "effective_date_stated_in_text": "2019-01-01",
        "year": 2018,
        "source_path_or_url": "https://cntt.pnt.edu.vn/api/upload/2025051537j24_2018_QH14_351416.pdf",
        "version_note": (
            "Văn bản gốc khi ban hành (7 chương, 43 điều). Đã hết hiệu lực từ 2026-07-01 theo "
            "Điều 44 Luật An ninh mạng 116/2025/QH15 (nguồn: tra cứu web ngày truy cập). "
            "Benchmark hỏi theo nội dung văn bản này, không hỏi hiệu lực pháp lý hiện hành."
        ),
        "excluded_pages": {24: "Chỉ có chức danh và chữ ký Chủ tịch Quốc hội, không có nội dung điều luật."},
    },
]


def main() -> None:
    documents = []
    total_counted = 0
    for spec in SOURCES:
        path = RAW / spec["file"]
        if not path.exists():
            sys.exit(f"Missing source file: {path}")
        reader = PdfReader(str(path))
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            text = unicodedata.normalize("NFC", page.extract_text() or "").strip()
            counted = len(text) >= MIN_CONTENT_CHARS
            reason = spec["excluded_pages"].get(number)
            if counted and reason:
                sys.exit(f"{spec['source_id']} p{number}: marked excluded but passes threshold; review rule")
            if not counted and not reason:
                sys.exit(f"{spec['source_id']} p{number}: below threshold without a recorded reason")
            pages.append({"page": number, "chars": len(text), "counted": counted,
                          **({"exclusion_reason": reason} if reason else {})})
        counted_pages = [p["page"] for p in pages if p["counted"]]
        total_counted += len(counted_pages)
        documents.append({
            **{k: v for k, v in spec.items() if k not in ("file", "excluded_pages")},
            "source_path_local": f"data/raw/{spec['file']}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "license_or_permission": LICENSE,
            "accessed_at": ACCESSED_AT,
            "physical_pages": len(reader.pages),
            "counted_pages": counted_pages,
            "counted_page_total": len(counted_pages),
            "counted_chars": sum(p["chars"] for p in pages if p["counted"]),
            "pages": pages,
        })

    manifest = {
        "corpus": "Luật Việt Nam về an toàn thông tin mạng và an ninh mạng (bản gốc 2015, 2018)",
        "language": "vi",
        "page_counting_rule": (
            f"Trang vật lý được tính khi text trích xuất (NFC, bỏ khoảng trắng đầu/cuối) có >= "
            f"{MIN_CONTENT_CHARS} ký tự; trang dưới ngưỡng được kiểm tra thủ công và ghi lý do loại. "
            "Không có trang bìa, mục lục hay tài liệu tham khảo riêng; trang 1 chứa Điều 1-2 nên được tính."
        ),
        "char_count_note": "Số ký tự đo trên text pypdf sau NFC + strip, trước bước chuẩn hóa khoảng trắng của pipeline.",
        "filter_fields": {
            "year": "int, năm ban hành lấy từ dòng 'Luật số ...' trên trang 1 (2015 hoặc 2018)",
            "document_id": "str, ID tài liệu do tác giả đặt theo số hiệu luật",
        },
        "total_counted_pages": total_counted,
        "documents": documents,
    }
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}: {total_counted} counted pages")
    for d in documents:
        print(f"  {d['source_id']}: {d['counted_page_total']}/{d['physical_pages']} pages, "
              f"{d['counted_chars']} chars, sha256={d['sha256'][:12]}")
    if total_counted < 30:
        sys.exit("Corpus has fewer than 30 counted content pages")


if __name__ == "__main__":
    main()
