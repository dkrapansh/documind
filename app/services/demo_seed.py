from sqlalchemy.orm import Session

from app.config import settings
from app.repositories.chunks import create_chunks, list_by_document
from app.repositories.documents import create_ready_document, list_by_tenant
from app.repositories.tenants import get_by_name

def clone_seed_corpus(db: Session, target_tenant_id: int) -> None:
    """Copies every ready document in the seed tenant (settings.seed_tenant_name)
    into target_tenant_id, chunks and embeddings included, with zero
    embedding-API calls - chunk embeddings are deterministic for a given
    model and text, so reusing the already-computed vectors is exact, not
    an approximation.

    Lets a brand-new ephemeral demo tenant answer questions about the
    sample handbook immediately, without either sharing the seed tenant's
    row (which would defeat the point of per-visitor isolation) or paying
    to re-embed it on every session mint.
    """
    seed_tenant = get_by_name(db, settings.seed_tenant_name)
    if seed_tenant is None:
        return

    for document in list_by_tenant(db, seed_tenant.id):
        if document.status != "ready":
            continue

        source_chunks = list_by_document(db, document.id, seed_tenant.id)
        if not source_chunks:
            continue

        clone = create_ready_document(
            db,
            tenant_id=target_tenant_id,
            filename=document.filename,
            content_hash=document.content_hash,
            chunk_count=len(source_chunks),
        )
        create_chunks(
            db,
            clone.id,
            target_tenant_id,
            [
                {
                    "index": chunk.chunk_index,
                    "text": chunk.text,
                    "embedding": chunk.embedding,
                    "token_count": chunk.token_count,
                }
                for chunk in source_chunks
            ],
        )
    db.commit()
