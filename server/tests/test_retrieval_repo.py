import server.app.db.base  # noqa: F401  (ensure mappers load before repo import)
from server.app.repositories.retrieval_repo import RetrievalRepository


def test_build_tsquery_sanitizes_and_dedupes_tokens():
    build = RetrievalRepository._build_tsquery
    # operators/punctuation stripped, CJK + alnum kept, duplicates removed, OR-joined
    assert build(["退款", "退款", "&", "SOP", "!!!"]) == "退款 | sop"
    assert build([":", "|", "()"]) == ""
    assert build([]) == ""


def test_build_tsquery_splits_mixed_tokens():
    # a raw token containing separators is split into safe lexemes
    assert RetrievalRepository._build_tsquery(["a-b.c"]) == "a | b | c"
