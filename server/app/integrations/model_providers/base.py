from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    status: str
    latency_ms: int
    error_code: str | None = None
    error_message: str | None = None


class ChatProvider:
    def test_connection(self) -> ConnectionTestResult:
        raise NotImplementedError

    def generate_qa_pairs(self, prompt: str) -> str:
        raise NotImplementedError

    def complete_chat(self, prompt: str) -> str:
        raise NotImplementedError

    def stream_chat(self, prompt: str):
        raise NotImplementedError


class EmbeddingProvider:
    dimension: int | None = None

    def test_connection(self) -> ConnectionTestResult:
        raise NotImplementedError

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class ConfiguredProvider(ChatProvider, EmbeddingProvider):
    provider_name = "configured"

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        config: dict | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.config = config or {}

    def test_connection(self) -> ConnectionTestResult:
        if self.base_url == "mock://success":
            return ConnectionTestResult(success=True, status="SUCCESS", latency_ms=1)
        if self.base_url == "mock://failure":
            return ConnectionTestResult(
                success=False,
                status="FAILED",
                latency_ms=1,
                error_code="PROVIDER_UNAVAILABLE",
                error_message="模型供应商连接失败",
            )
        if self.config.get("testMode") == "failure":
            return ConnectionTestResult(
                success=False,
                status="FAILED",
                latency_ms=1,
                error_code="PROVIDER_UNAVAILABLE",
                error_message="模型供应商连接失败",
            )
        if self.base_url or self.api_key:
            return ConnectionTestResult(success=True, status="SUCCESS", latency_ms=1)
        return ConnectionTestResult(
            success=False,
            status="FAILED",
            latency_ms=1,
            error_code="MISSING_PROVIDER_CONFIG",
            error_message="模型供应商配置不完整",
        )

    def generate_qa_pairs(self, prompt: str) -> str:
        configured = self.config.get("qaSplitResponse")
        if configured is not None:
            return configured if isinstance(configured, str) else json.dumps(configured)

        return json.dumps(
            {
                "items": [
                    {
                        "question": "这段内容的核心问题是什么？",
                        "answer": prompt[:200],
                        "quote": prompt[:120],
                        "pageNo": 1,
                        "chunkIndex": 0,
                    }
                ]
            },
            ensure_ascii=False,
        )

    def complete_chat(self, prompt: str) -> str:
        if self.config.get("chatError"):
            raise RuntimeError(str(self.config["chatError"]))
        configured = self.config.get("chatResponse")
        if configured is not None:
            return str(configured)
        if "知识库中没有找到足够可靠的信息" in prompt:
            return "知识库中没有找到足够可靠的信息，无法根据现有资料回答。"
        return "根据知识库资料，" + prompt.split("用户问题：", 1)[-1].split("\n", 1)[0]

    def stream_chat(self, prompt: str):
        answer = self.complete_chat(prompt)
        chunk_size = int(self.config.get("chatChunkSize") or 8)
        for index in range(0, len(answer), chunk_size):
            yield answer[index : index + chunk_size]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        dimension = int(self.config.get("embeddingDimension") or self.dimension or 1536)
        vectors: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(text.encode("utf-8")).digest()
            vector = []
            for index in range(dimension):
                value = seed[index % len(seed)] / 255
                vector.append(round(value, 6))
            vectors.append(vector)
        return vectors
