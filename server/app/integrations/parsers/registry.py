"""Parser registry: the single place that knows which parsers exist, in what
precedence order, and which upload extensions are therefore acceptable.

The upload gate must never accept a file the parse stage cannot handle, so
``allowed_upload_extensions`` is derived from parser availability: an
unconfigured MinerU keeps PDF/Office/image formats out of the allowlist. The
``UPLOAD_ALLOWED_EXTENSIONS`` env var can only restrict this set, never widen
it beyond what the parsers support.
"""

from server.app.core.config import settings
from server.app.integrations.parsers.base import ParserAdapter
from server.app.integrations.parsers.csv_parser import CsvParser
from server.app.integrations.parsers.lightweight import LightweightParser
from server.app.integrations.parsers.mineru import MinerUParser


def get_parser_chain() -> list[ParserAdapter]:
    # Ordered by selection precedence; extensions are currently disjoint so
    # the order only matters if a future parser overlaps an earlier one.
    return [LightweightParser(), CsvParser(), MinerUParser()]


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
