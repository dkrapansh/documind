from fastapi import APIRouter, BackgroundTasks, Depends, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.repositories.documents import create_document, get_by_content_hash
from app.schemas.document import DocumentResponse
from app.services.file_storage import compute_content_hash, save_file
from app.services.ingestion import process_document
from app.services.text_extraction import validate_extension

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, dependencies=[Depends(api_key_header)])
async def upload_document(
    request: Request,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id

    validate_extension(file.filename)

    file_bytes = await file.read()
    content_hash = compute_content_hash(file_bytes)

    existing = get_by_content_hash(db, tenant_id, content_hash)
    if existing is not None:
        return existing

    save_file(content_hash, file.filename, file_bytes)
    document = create_document(db, tenant_id, file.filename, content_hash)

    background_tasks.add_task(process_document, document.id)

    return document