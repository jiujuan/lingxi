from server.app.models.document import Document
from server.app.models.qa_pair import DocumentChunk


def build_qa_split_prompt(document: Document, chunks: list[DocumentChunk]) -> str:
    lines = [
        "你是企业知识库 QA 拆分助手。",
        "请基于原文片段生成可检索的问题、答案、引用原文和页码。",
        "只返回 JSON，格式为 {\"items\":[{\"question\":\"...\",\"answer\":\"...\",\"quote\":\"...\",\"pageNo\":1,\"chunkIndex\":0}]}。",
        f"文档标题：{document.title}",
        "原文片段：",
    ]
    for chunk in chunks:
        title_path = " / ".join(chunk.title_path or [])
        lines.append(
            f"[chunkIndex={chunk.chunk_index}, pageNo={chunk.page_no or 1}, title={title_path}]"
        )
        lines.append(chunk.content)
    return "\n".join(lines)
