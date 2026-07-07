from app.services.chunking import chunk_text

def test_chunk_text_splits_long_document_into_multiple_chunks():
    long_text = "This is a test sentence. " * 300  # well over 500 tokens

    chunks = chunk_text(long_text)

    assert len(chunks) > 1
    assert all(isinstance(chunk, str) for chunk in chunks)


def test_chunk_text_returns_single_chunk_for_short_text():
    short_text = "Just one short sentence."

    chunks = chunk_text(short_text)

    assert len(chunks) == 1
    assert chunks[0] == short_text


def test_chunk_text_returns_empty_list_for_empty_input():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_consecutive_chunks_share_overlapping_content():
    long_text = "Paragraph one sentence. " * 100 + "\n\n" + "Paragraph two sentence. " * 100

    chunks = chunk_text(long_text)

    assert len(chunks) >= 2
    # Overlap means the tail of one chunk should reappear at the start of the next
    tail_of_first = chunks[0][-30:]
    assert tail_of_first[:15] in chunks[1] or tail_of_first[-15:] in chunks[1]