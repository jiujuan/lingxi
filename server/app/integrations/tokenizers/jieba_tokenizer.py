"""jieba search-mode tokenizer shared by the FTS index and query sides.

Contract: ``qa_pairs.search_text`` is space-joined tokens re-parsed by the
``to_tsvector('simple', ...)`` generated column, while queries go through
``RetrievalRepository._build_tsquery``. Both ends only stay consistent if
every token is a plain run of letters/digits/CJK ideographs — punctuation or
underscores would be re-split differently by PostgreSQL's parser than by the
query-side regex. Changing segmentation behavior (jieba version, user dict)
requires re-running ``server.scripts.backfill_search_text``.
"""

import re
import threading
import unicodedata

import jieba

from server.app.core.config import settings
from server.app.integrations.tokenizers.base import SearchTextTokenizer

# Word-character runs minus underscore: PostgreSQL's default parser treats
# "_" as a separator, so "foo_bar" as one token would create index lexemes
# the query side can never produce.
_WORD_RUN_RE = re.compile(r"[^\W_]+")

# jieba.load_userdict mutates the process-global default tokenizer and
# re-reads the file on every call; services construct this class per request,
# so each dict file must be loaded exactly once per process.
_user_dict_lock = threading.Lock()
_loaded_user_dicts: set[str] = set()


class JiebaTokenizer(SearchTextTokenizer):
    def __init__(self, user_dict_path: str | None = None) -> None:
        # Eager dictionary load (~1s, once per process, lock-guarded by jieba)
        # so the first request does not pay the latency.
        jieba.initialize()
        path = user_dict_path or settings.jieba_user_dict_path
        if path:
            self._load_user_dict_once(path)

    @staticmethod
    def _load_user_dict_once(path: str) -> None:
        if path in _loaded_user_dicts:
            return
        with _user_dict_lock:
            if path not in _loaded_user_dicts:
                jieba.load_userdict(path)
                _loaded_user_dicts.add(path)

    def tokenize(self, text: str) -> list[str]:
        # NFKC folds fullwidth forms (ＳＯＰ２０２６ -> SOP2026) and must run
        # before segmentation so both sides see identical surface text.
        normalized = unicodedata.normalize("NFKC", text).lower()
        tokens: list[str] = []
        for word in jieba.cut_for_search(normalized):
            tokens.extend(_WORD_RUN_RE.findall(word))
        return tokens
