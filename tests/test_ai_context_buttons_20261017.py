"""Keep the project context UI simple without retiring the ad-hoc compressor."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_only_one_copy_and_one_download_action():
    detail = (ROOT / 'templates/detail.html').read_text(encoding='utf-8')
    assert 'data-prompt="/api/context/{{ p.name | urlencode }}">copy AI context</button>' in detail
    assert 'href="/api/context/{{ p.name | urlencode }}?download=1">download AI context</a>' in detail
    assert 'download compact chat copy' not in detail
    assert '?download=1&amp;compact=1' not in detail
    assert 'Copy and download export the same complete AI context' in detail


def test_separate_document_compressor_and_old_api_remain_available():
    base = (ROOT / 'templates/base.html').read_text(encoding='utf-8')
    code = (ROOT / 'app.py').read_text(encoding='utf-8')
    checkpoints = (ROOT / 'checkpoints.py').read_text(encoding='utf-8')
    assert "url_for('compress_page')" in base
    assert '@app.route("/compress")' in code
    assert '@app.route("/api/compress", methods=["POST"])' in code
    assert 'compact=request.args.get("compact") == "1"' in code
    assert 'def export_context(name, compact=False):' in checkpoints
