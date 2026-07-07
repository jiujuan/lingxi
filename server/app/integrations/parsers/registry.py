"""Parser registry: the single place that knows which parsers exist, in what
precedence order, and which upload extensions are therefore acceptable.

The upload gate must never accept a file the parse stage cannot handle, so
``allowed_upload_extensions`` is derived from parser availability: an
unconfigured MinerU/Docling keeps PDF/Office/image formats out of the
allowlist. The ``UPLOAD_ALLOWED_EXTENSIONS`` env var can only restrict this
set, never widen it beyond what the parsers support.

Heavy-engine selection: ``DOC_PARSER_ENGINE`` picks MinerU, Docling, or (the
default) ``auto`` which registers both with MinerU first — chain order is the
tiebreak for their overlapping extensions, so under ``auto`` with both engines
configured MinerU owns the shared formats and Docling only receives its
exclusive ones (.html/.htm).
"""

from functools import lru_cache
import logging

from server.app.core.config import settings
from server.app.integrations.parsers.base import ParserAdapter
from server.app.integrations.parsers.csv_parser import CsvParser
from server.app.integrations.parsers.docling import DoclingParser
from server.app.integrations.parsers.lightweight import LightweightParser
from server.app.integrations.parsers.mineru import MinerUParser

logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def _warn_unknown_engine(engine: str) -> None:
    # Registry functions run per upload request and inside the worker — a
    # config typo must degrade to "auto" visibly, not become blanket 500s.
    logger.warning("未知的 DOC_PARSER_ENGINE=%s，按 auto 处理", engine)


def _heavy_parsers() -> list[ParserAdapter]:
    engine = (settings.doc_parser_engine or "auto").strip().lower()
    if engine == "mineru":
        return [MinerUParser()]
    if engine == "docling":
        return [DoclingParser()]
    if engine != "auto":
        _warn_unknown_engine(engine)
    return [MinerUParser(), DoclingParser()]


def get_parser_chain() -> list[ParserAdapter]:
    return [LightweightParser(), CsvParser(), *_heavy_parsers()]


def supported_extensions() -> frozenset[str]:
    extensions: set[str] = set()
    for parser in get_parser_chain():
        if parser.is_available():
            extensions.update(parser.extensions)
    return frozenset(extensions)


def allowed_upload_extensions() -> frozenset[str]:
    supported = supported_extensions()
    configured = {item.lower() for item in settings.upload_allowed_extensions}
    if not configured:
        return supported
    return frozenset(configured & supported)
