from server.app.integrations.tokenizers.jieba_tokenizer import JiebaTokenizer


def test_tokenize_segments_chinese_words_and_ascii_runs():
    tokens = JiebaTokenizer().tokenize("退款需要主管审批，详见 SOP 2026。")

    assert "退款" in tokens
    assert "审批" in tokens
    assert "sop" in tokens
    assert "2026" in tokens
    # 标点和空白绝不能进入索引 lexeme
    assert all(token.strip() == token and token for token in tokens)


def test_tokenize_normalizes_fullwidth_via_nfkc():
    assert JiebaTokenizer().tokenize("ＳＯＰ２０２６") == ["sop2026"]


def test_tokenize_keeps_cjk_outside_basic_block():
    # 扩展 A 区（U+3400）：旧的 unigram 实现会将其当作分隔符丢弃
    assert JiebaTokenizer().tokenize("㐀") == ["㐀"]


def test_tokenize_drops_punctuation_and_blank_input():
    tokenizer = JiebaTokenizer()

    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("！？——…、。") == []


def test_tokenize_splits_punctuated_ascii_like_the_query_side():
    # PostgreSQL 的 'simple' 解析器与查询端 _TS_TOKEN_RE 对 "gpt-4" 这类
    # 复合词的切法不同，分词器必须先拆成纯字母数字段保证两端一致
    tokens = JiebaTokenizer().tokenize("GPT-4 和 v2.0")

    assert "gpt" in tokens
    assert "4" in tokens
    assert "v2" in tokens
    assert "0" in tokens


def test_query_tokens_hit_indexed_search_text_for_same_source():
    # 写读一致性契约：同一段文本，查询侧 token 必须是索引侧 lexeme 的子集
    tokenizer = JiebaTokenizer()
    question = "已开票订单退款前要做什么？"
    answer = "需要先红冲发票。"

    search_text = tokenizer.to_search_text(f"{question} {answer}")

    assert set(tokenizer.tokenize(question)) <= set(search_text.split())


def test_user_dict_keeps_domain_terms_whole(tmp_path):
    dict_file = tmp_path / "userdict.txt"
    dict_file.write_text("灵犀知识库 100 n\n", encoding="utf-8")

    tokens = JiebaTokenizer(user_dict_path=str(dict_file)).tokenize("灵犀知识库")

    assert "灵犀知识库" in tokens
