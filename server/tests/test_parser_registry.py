import types

from server.app.integrations.parsers import mineru as mineru_module
from server.app.integrations.parsers import registry as registry_module
from server.app.integrations.parsers.base import ParseSource


def _stub_settings(monkeypatch, *, allowed=(), mineru_base_url=None):
    stub = types.SimpleNamespace(
        upload_allowed_extensions=allowed,
        mineru_base_url=mineru_base_url,
        mineru_api_key=None,
        mineru_timeout_ms=1000,
        mineru_max_wait_seconds=5,
        mineru_poll_interval_seconds=0.1,
        mineru_backend=None,
        mineru_lang=None,
    )
    monkeypatch.setattr(registry_module, "settings", stub)
    monkeypatch.setattr(mineru_module, "settings", stub)


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
