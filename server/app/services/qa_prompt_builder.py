from server.app.models.document import Document
from server.app.models.qa_pair import DocumentChunk


def build_qa_split_prompt(document: Document, chunks: list[DocumentChunk]) -> str:
    lines = [
        "你是企业知识库 QA 拆分助手。",
        "请基于原文片段生成可检索的问题、答案、引用原文和页码。",
        (
            "只返回一个严格 JSON object，不要 Markdown 或解释。格式为 "
            '{"items":[{"question":"...","answer":"...","quote":"...",'
            '"pageNo":1,"chunkIndex":0}],"coveredChunkIndexes":[0],'
            '"skippedChunks":[{"chunkIndex":1,"reason":"..."}]}'
        ),
        (
            "items 中每项必须有当前片段的 chunkIndex；quote 必须是该 chunk 的原文子串，"
            "pageNo 必须位于该 chunk 的页码范围内。"
        ),
        (
            "coveredChunkIndexes 表示至少生成了一条 items 的 chunkIndex；skippedChunks "
            "记录未生成 QA 的 chunkIndex 和非空 reason。coveredChunkIndexes 与 "
            "skippedChunks 的 chunkIndex 必须对本批次所有 chunkIndex 构成完备分区："
            "每个 index 恰好出现一次，不能同时出现在两处，也不能缺失。"
        ),
        f"文档标题：{document.title}",
        "原文片段：",
    ]
    for chunk in chunks:
        title_path = " / ".join(chunk.title_path or [])
        page_start = chunk.page_start or chunk.page_no or 1
        page_end = chunk.page_end or page_start
        lines.append(
            f"[chunkIndex={chunk.chunk_index}, pageRange={page_start}-{page_end}, "
            f"title={title_path}]"
        )
        lines.append(chunk.content)
    return "\n".join(lines)
