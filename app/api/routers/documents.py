from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.config import settings
from app.core.exceptions import DocumentNotFoundException, PayloadTooLargeException
from app.repositories.documents import (
    create_document,
    get_by_content_hash,
    get_by_id_for_tenant,
    list_by_tenant,
)
from app.schemas.document import DocumentResponse
from app.services.document_service import delete_document as delete_document_for_tenant
from app.services.file_storage import compute_content_hash, save_file
from app.services.ingestion import process_document
from app.services.text_extraction import validate_extension

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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id

    validate_extension(file.filename)

    file_bytes = await _read_bounded(file, settings.max_upload_size_bytes)
    content_hash = compute_content_hash(file_bytes)

    existing = get_by_content_hash(db, tenant_id, content_hash)
    if existing is not None:
        return existing

    save_file(content_hash, file.filename, file_bytes)
    document = create_document(db, tenant_id, file.filename, content_hash)

    background_tasks.add_task(process_document, document.id)

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