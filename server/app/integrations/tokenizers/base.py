class SearchTextTokenizer:
    def tokenize(self, text: str) -> list[str]:
        raise NotImplementedError

    def to_search_text(self, text: str) -> str:
        return " ".join(self.tokenize(text))
