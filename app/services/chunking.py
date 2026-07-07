import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

_encoding = tiktoken.encoding_for_model("text-embedding-3-small")

def _count_tokens(text: str) -> int:
    return len(_encoding.encode(text))

_splitter = RecursiveCharacterTextSplitter(
    chunk_size = 500,
    chunk_overlap = 60,
    length_function = _count_tokens,
    separators=["\n\n", "\n", ". ", " ", ""]
)

def chunk_text(text: str) -> list[str]:
    """Split raw document text into ~500-token chunks with ~60-token overlap.
    Splits on the most natural boundary available (paragraph, then line,
    then sentence, then word, then character) so chunks stay aligned with
    real units of meaning rather than cutting mid-sentence wherever
    possible.
    """

    if not text.strip():
        return []

    return _splitter.split_text(text)