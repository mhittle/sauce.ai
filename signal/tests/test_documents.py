from app.api.documents import sniff_content_type


def test_pdf_served_inline_even_if_upstream_is_octet_stream():
    # CivicPlus DocumentCenter often serves PDFs as octet-stream -> would
    # download. We force application/pdf inline so it renders.
    ct, disp = sniff_content_type(b"%PDF-1.7\n...", "application/octet-stream")
    assert ct == "application/pdf" and disp == "inline"


def test_zip_is_attachment():
    ct, disp = sniff_content_type(b"PK\x03\x04...", "application/zip")
    assert ct == "application/zip" and disp == "attachment"


def test_unknown_falls_back_to_upstream_type():
    ct, disp = sniff_content_type(b"\xff\xd8\xff", "image/jpeg")
    assert ct == "image/jpeg" and disp == "inline"
    ct2, _ = sniff_content_type(b"\x00\x01", None)
    assert ct2 == "application/octet-stream"
