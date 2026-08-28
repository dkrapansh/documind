from fastapi import APIRouter, Depends, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.config import settings
from app.core.exceptions import (
    DocumentNotFoundException,
    MissingFilenameException,
    PayloadTooLargeException,
    UnreadableDocumentException,
)
from app.repositories.document_contents import upsert_content
from app.repositories.documents import (
    create_document,
    get_by_content_hash,
    get_by_id_for_tenant,
    list_by_tenant,
)
from app.schemas.document import DocumentResponse
from app.services.document_service import delete_document as delete_document_for_tenant
from app.services.file_storage import compute_content_hash
from app.services.ingestion_worker import notify_new_job
from app.services.text_extraction import extract_text, validate_extension

router = APIRouter(prefix="/documents", tags=["documents"])


async def _read_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Reads in chunks instead of one `await file.read()`, so an
    oversized file gets rejected mid-stream instead of fully buffered
    into memory first. The backend is directly reachable (the Vercel
    proxy's body cap only covers the frontend path), so this is the
    only guard against a large-upload memory DoS."""
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeException(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=DocumentResponse, dependencies=[Depends(api_key_header)])
async def upload_document(
    request: Request,
    file: UploadFile,
    db: Session = Depends(get_db),
):
    """Accept a document and enqueue it for ingestion.

    Text extraction happens here, synchronously, and the extracted text is
    stored in Postgres. Previously the raw file was written to local disk and
    the background job read it back, which on an ephemeral filesystem meant
    any restart between upload and ingestion destroyed the input: the job
    could never succeed and no retry could fix it.

    Extracting up front also turns a whole class of silent failure into an
    immediate, actionable error. A corrupt file, or a scanned PDF with no
    text layer, used to return 200 with status "pending" and then land in
    "failed" minutes later with no reason recorded. It now returns 422 with
    an explanation while the caller is still listening.

    The slow, paid, network-bound part (embedding every chunk) stays in the
    background where it belongs. This returns as soon as the job is durably
    enqueued.
    """
    tenant_id = request.state.tenant_id

    # UploadFile.filename is None for a malformed multipart part, and
    # Path(None) raises TypeError, which used to escape as an unhandled 500.
    if not file.filename:
        raise MissingFilenameException()

    validate_extension(file.filename)

    file_bytes = await _read_bounded(file, settings.max_upload_size_bytes)
    content_hash = compute_content_hash(file_bytes)

    # Excludes failed documents, so re-uploading a file that failed is the
    # retry mechanism rather than a no-op that returns the failed row.
    existing = get_by_content_hash(db, tenant_id, content_hash)
    if existing is not None:
        return existing

    try:
        extracted_text = extract_text(file_bytes, file.filename)
    except Exception as exc:
        raise UnreadableDocumentException(
            f"Could not read this file ({type(exc).__name__}). It may be corrupt or "
            "not a valid file of its type."
        )

    if not extracted_text.strip():
        raise UnreadableDocumentException(
            "No readable text could be extracted from this document. If it is a scanned "
            "PDF, it has no text layer and needs OCR, which is not supported."
        )

    document = create_document(db, tenant_id, file.filename, content_hash)
    upsert_content(db, document.id, extracted_text)
    db.commit()
    db.refresh(document)

    # Wakes the worker so ingestion starts now rather than at the next poll.
    # Only an optimisation: the job is already durably queued, so losing this
    # signal costs latency, never the job.
    notify_new_job()

    return document

@router.get("", response_model=list[DocumentResponse], dependencies=[Depends(api_key_header)])
async def list_documents(
    request:Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id
    return list_by_tenant(db, tenant_id)

@router.get("/{document_id}", response_model=DocumentResponse, dependencies=[Depends(api_key_header)])
async def get_document_status(
    document_id: int,
    request: Request, 
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id
    document = get_by_id_for_tenant(db, document_id, tenant_id)
    if document is None:
        raise DocumentNotFoundException()
    return document

@router.delete("/{document_id}", status_code=204, dependencies=[Depends(api_key_header)])
async def delete_document(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id
    deleted = delete_document_for_tenant(db, document_id, tenant_id)
    if not deleted:
        raise DocumentNotFoundException()
    return Response(status_code=204)