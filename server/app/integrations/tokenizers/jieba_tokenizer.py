import re

from server.app.integrations.tokenizers.base import SearchTextTokenizer


class JiebaTokenizer(SearchTextTokenizer):
    def tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        buffer: list[str] = []

        def flush_buffer() -> None:
            if buffer:
                tokens.append("".join(buffer).lower())
                buffer.clear()

        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                flush_buffer()
                tokens.append(char)
            elif re.match(r"[A-Za-z0-9]", char):
                buffer.append(char)
            else:
                flush_buffer()
        flush_buffer()
        return tokens
