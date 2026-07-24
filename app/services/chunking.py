import re

import tiktoken

_encoding = tiktoken.encoding_for_model("text-embedding-3-small")

def _count_tokens(text: str) -> int:
    return len(_encoding.encode(text))

def count_tokens(text: str) -> int:
    """Public wrapper around _count_tokens so other modules (ingestion)
    can get a chunk's token count without duplicating the tiktoken
    encoding setup."""
    return _count_tokens(text)

_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 60
_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# Hand-rolled port of langchain_text_splitters' RecursiveCharacterTextSplitter
# (keep_separator=True, is_separator_regex=False - the only combination this
# project ever used), not a call into that library. langchain_text_splitters
# .base unconditionally does `try: from transformers.tokenization_utils_base
# import ...` at import time to probe for an optional HuggingFace-tokenizer
# feature this project never uses - and since `transformers`/`torch` ARE
# installed here (for the cross-encoder reranker), that probe succeeds and
# eagerly loads the entire torch/transformers stack into every process, just
# from importing this module. That's what pushed the deployed image's boot
# memory to the edge of Render free tier's 512MB ceiling, on a request path
# (document upload/ingestion) that has nothing to do with reranking. Porting
# the ~40 lines this project actually exercises keeps the exact chunking
# behavior while removing that dependency entirely.

def _split_with_separator(text: str, separator: str) -> list[str]:
    """Split on `separator`, keeping it attached to the start of whatever
    follows it (langchain's keep_separator=True / "start" behavior)."""
    if not separator:
        return list(text)
    parts = re.split(f"({re.escape(separator)})", text)
    merged = [parts[i] + parts[i + 1] for i in range(1, len(parts), 2)]
    if len(parts) % 2 == 0:
        merged += parts[-1:]
    pieces = [parts[0], *merged]
    return [p for p in pieces if p]

def _join_pieces(pieces: list[str], separator: str) -> str | None:
    text = separator.join(pieces).strip()
    return text or None

def _merge_pieces(pieces: list[str], separator: str) -> list[str]:
    """Greedily pack pieces into chunks up to _CHUNK_SIZE tokens, backing
    off by whole pieces until the running total is back under
    _CHUNK_OVERLAP before starting the next chunk - this is what produces
    the overlapping tail/head between consecutive chunks."""
    separator_len = _count_tokens(separator)
    chunks = []
    current: list[str] = []
    total = 0
    for piece in pieces:
        piece_len = _count_tokens(piece)
        if total + piece_len + (separator_len if current else 0) > _CHUNK_SIZE:
            if current:
                joined = _join_pieces(current, separator)
                if joined is not None:
                    chunks.append(joined)
                while total > _CHUNK_OVERLAP or (
                    total + piece_len + (separator_len if current else 0) > _CHUNK_SIZE
                    and total > 0
                ):
                    total -= _count_tokens(current[0]) + (separator_len if len(current) > 1 else 0)
                    current = current[1:]
        current.append(piece)
        total += piece_len + (separator_len if len(current) > 1 else 0)
    joined = _join_pieces(current, separator)
    if joined is not None:
        chunks.append(joined)
    return chunks

def _recursive_split(text: str, separators: list[str]) -> list[str]:
    separator = separators[-1]
    remaining_separators: list[str] = []
    for i, candidate in enumerate(separators):
        if not candidate:
            separator = candidate
            break
        if candidate in text:
            separator = candidate
            remaining_separators = separators[i + 1:]
            break

    pieces = _split_with_separator(text, separator)

    final_chunks = []
    good_pieces: list[str] = []
    for piece in pieces:
        if _count_tokens(piece) < _CHUNK_SIZE:
            good_pieces.append(piece)
            continue
        if good_pieces:
            final_chunks.extend(_merge_pieces(good_pieces, ""))
            good_pieces = []
        if not remaining_separators:
            final_chunks.append(piece)
        else:
            final_chunks.extend(_recursive_split(piece, remaining_separators))
    if good_pieces:
        final_chunks.extend(_merge_pieces(good_pieces, ""))
    return final_chunks

def chunk_text(text: str) -> list[str]:
    """Split raw document text into ~500-token chunks with ~60-token overlap.
    Splits on the most natural boundary available (paragraph, then line,
    then sentence, then word, then character) so chunks stay aligned with
    real units of meaning rather than cutting mid-sentence wherever
    possible.
    """
    if not text.strip():
        return []

    return _recursive_split(text, _SEPARATORS)
