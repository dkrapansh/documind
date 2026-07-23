import logging

from app.clients.embeddings import embed_text
from app.db.session import SessionLocal
from app.repositories.chunks import create_chunks
from app.repositories.documents import get_by_id, update_status
from app.services.chunking import chunk_text, count_tokens
from app.services.file_storage import load_file
from app.services.query_cache import bump_scope
from app.services.text_extraction import extract_text

logger = logging.getLogger(__name__)

def process_document(document_id: int) -> None:
    """Background job: load the saved file, extract text, chunk it,
    embed every chunk, and store the results.

    Runs in its OWN database session, because BackgroundTasks executes
    after the HTTP response has already been sent, the request's
    session (from Depends(get_db)) is already closed by then.

    All chunk inserts + the final status update commit together as one
    transaction: a document ends up fully ready or cleanly failed,
    never half-written.
    """

    db = SessionLocal()
    document = None
    try:
        document = get_by_id(db, document_id)
        if document is None:
            logger.error("process_codument: document %s not found", document_id)
            return

        update_status(db, document_id, "processing")
        db.commit()

        file_bytes = load_file(document.content_hash, document.filename)
        text = extract_text(file_bytes, document.filename)
        raw_chunks = chunk_text(text)

        if not raw_chunks:
            update_status(db, document_id, "failed")
            db.commit()
            bump_scope(document.tenant_id)
            logger.warning(
                "proess_document: no extractable text for document %s", document_id
            )
            return

        chunk_rows = []
        for index, piece in enumerate(raw_chunks):
            embedding = embed_text(piece)
            chunk_rows.append(
                {
                    "index": index,
                    "text": piece,
                    "embedding": embedding,
                    "token_count": count_tokens(piece),
                }
            )
        create_chunks(db, document_id, document.tenant_id, chunk_rows)
        update_status(db, document_id, "ready", chunk_count=len(chunk_rows))
        db.commit()
        bump_scope(document.tenant_id)

    except Exception:
        db.rollback()
        logger.exception("process_document failed for document %s", document_id)
        update_status(db, document_id, "failed")
        db.commit()
        if document is not None:
            bump_scope(document.tenant_id)
    finally:
        db.close()