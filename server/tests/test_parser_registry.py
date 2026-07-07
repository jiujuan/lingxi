import types

from server.app.integrations.parsers import docling as docling_module
from server.app.integrations.parsers import mineru as mineru_module
from server.app.integrations.parsers import registry as registry_module
from server.app.integrations.parsers.base import ParseSource


def _stub_settings(
    monkeypatch,
    *,
    allowed=(),
    mineru_base_url=None,
    docling_base_url=None,
    doc_parser_engine="auto",
):
    stub = types.SimpleNamespace(
        upload_allowed_extensions=allowed,
        doc_parser_engine=doc_parser_engine,
        mineru_base_url=mineru_base_url,
        mineru_api_key=None,
        mineru_timeout_ms=1000,
        mineru_max_wait_seconds=5,
        mineru_poll_interval_seconds=0.1,
        mineru_backend=None,
        mineru_lang=None,
        docling_base_url=docling_base_url,
        docling_api_key=None,
        docling_timeout_ms=1000,
        docling_max_wait_seconds=5,
        docling_poll_interval_seconds=0.1,
        docling_do_ocr=None,
        docling_ocr_lang=None,
        docling_pdf_backend=None,
    )
    monkeypatch.setattr(registry_module, "settings", stub)
    monkeypatch.setattr(mineru_module, "settings", stub)
    monkeypatch.setattr(docling_module, "settings", stub)


def _source(file_name: str) -> ParseSource:
    return ParseSource(
        file_name=file_name, mime_type="application/octet-stream", content=b"x"
    )


def _select(file_name: str) -> str | None:
    for parser in registry_module.get_parser_chain():
        if parser.supports(_source(file_name)):
            return parser.name
    return None


def test_extension_routing_with_mineru_configured(monkeypatch):
    _stub_settings(monkeypatch, mineru_base_url="http://mineru.test")

    assert _select("guide.md") == "LIGHTWEIGHT"
    assert _select("notes.TXT") == "LIGHTWEIGHT"
    assert _select("staff.csv") == "CSV"
    assert _select("report.pdf") == "MINERU"
    assert _select("slides.pptx") == "MINERU"
    assert _select("archive.zip") is None


def test_mineru_formats_hidden_when_unconfigured(monkeypatch):
    _stub_settings(monkeypatch, mineru_base_url=None)

    assert _select("report.pdf") is None
    supported = registry_module.supported_extensions()
    assert ".md" in supported and ".csv" in supported
    assert ".pdf" not in supported and ".docx" not in supported

    _stub_settings(monkeypatch, mineru_base_url="http://mineru.test")
    assert ".pdf" in registry_module.supported_extensions()


def test_allowed_upload_extensions_env_semantics(monkeypatch):
    # env 未设置：白名单 = 全部可用解析器扩展名
    _stub_settings(monkeypatch, allowed=(), mineru_base_url="http://mineru.test")
    assert registry_module.allowed_upload_extensions() == (
        registry_module.supported_extensions()
    )

    # env 设置：只能收紧——与解析器支持集求交
    _stub_settings(
        monkeypatch, allowed=(".md", ".PDF"), mineru_base_url="http://mineru.test"
    )
    assert registry_module.allowed_upload_extensions() == frozenset({".md", ".pdf"})

    # env 里写了 .pdf 但 MinerU 未配置：交集把它剔除，杜绝"上传成功解析必败"
    _stub_settings(monkeypatch, allowed=(".md", ".pdf"), mineru_base_url=None)
    assert registry_module.allowed_upload_extensions() == frozenset({".md"})


def test_engine_auto_registers_both_heavy_parsers_mineru_first(monkeypatch):
    _stub_settings(
        monkeypatch,
        mineru_base_url="http://mineru.test",
        docling_base_url="http://docling.test",
    )

    names = [parser.name for parser in registry_module.get_parser_chain()]
    assert names == ["LIGHTWEIGHT", "CSV", "MINERU", "DOCLING"]
    # 链序即优先级：共有格式归 MinerU
    assert _select("report.pdf") == "MINERU"
    # Docling 独占格式仍然可达
    assert _select("page.html") == "DOCLING"


def test_engine_docling_registers_only_docling(monkeypatch):
    _stub_settings(
        monkeypatch,
        doc_parser_engine="docling",
        mineru_base_url="http://mineru.test",
        docling_base_url="http://docling.test",
    )

    names = [parser.name for parser in registry_module.get_parser_chain()]
    assert "MINERU" not in names and "DOCLING" in names
    assert _select("report.pdf") == "DOCLING"


def test_engine_mineru_hides_docling_formats(monkeypatch):
    _stub_settings(
        monkeypatch,
        doc_parser_engine="mineru",
        mineru_base_url="http://mineru.test",
        docling_base_url="http://docling.test",
    )

    assert _select("page.html") is None
    assert ".html" not in registry_module.supported_extensions()


def test_html_allowlist_follows_docling_availability(monkeypatch):
    _stub_settings(monkeypatch, mineru_base_url="http://mineru.test")
    assert ".html" not in registry_module.allowed_upload_extensions()

    _stub_settings(monkeypatch, docling_base_url="http://docling.test")
    allowed = registry_module.allowed_upload_extensions()
    assert ".html" in allowed and ".htm" in allowed
    assert _select("page.html") == "DOCLING"


def test_unknown_engine_falls_back_to_auto(monkeypatch):
    _stub_settings(
        monkeypatch,
        doc_parser_engine="dockling-typo",
        docling_base_url="http://docling.test",
    )

    names = [parser.name for parser in registry_module.get_parser_chain()]
    assert names == ["LIGHTWEIGHT", "CSV", "MINERU", "DOCLING"]
    assert _select("report.pdf") == "DOCLING"  # MinerU 未配置，Docling 兜住
