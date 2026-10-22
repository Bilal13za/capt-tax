"""Tests for core/pageshot.py. No streamlit, no network.

Renders from assets/book.pdf when present, otherwise the render tests skip.
"""

import os

import pytest

from core import pageshot

BOOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "book.pdf")


def _make_pdf(path, text="hello page"):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def test_missing_pdf_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pageshot.render_page(str(tmp_path / "nope.pdf"), 1,
                             cache_dir=str(tmp_path / "cache"))


def test_page_exists_missing_file(tmp_path):
    assert pageshot.page_exists(str(tmp_path / "nope.pdf"), 1) is False


def test_render_and_cache_hit(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, "render me")
    cache = tmp_path / "cache"
    b1 = pageshot.render_page(str(pdf), 1, cache_dir=str(cache))
    assert b1[:8] == b"\x89PNG\r\n\x1a\n"
    b2 = pageshot.render_page(str(pdf), 1, cache_dir=str(cache))
    assert b1 == b2  # cache hit → identical bytes
    assert len(os.listdir(str(cache))) == 1


def test_render_out_of_range(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf)
    with pytest.raises(ValueError):
        pageshot.render_page(str(pdf), 99, cache_dir=str(tmp_path / "c"))


def test_page_exists_true_false(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf)
    assert pageshot.page_exists(str(pdf), 1) is True
    assert pageshot.page_exists(str(pdf), 5) is False


@pytest.mark.skipif(not os.path.isfile(BOOK), reason="assets/book.pdf not present")
def test_render_real_book_page(tmp_path):
    assert pageshot.page_exists(BOOK, 1) is True
    png = pageshot.render_page(BOOK, 1, dpi=110,
                               cache_dir=str(tmp_path / "cache"))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000
