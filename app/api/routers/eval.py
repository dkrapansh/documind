from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.core.exceptions import EvalRunNotFoundException
from app.repositories.eval_runs import get_eval_run_for_tenant, list_eval_results
from app.schemas.eval import EvalRunRequest, EvalRunResponse
from app.services.evaluation import run_eval_in_background, start_eval_run

router = APIRouter(prefix="/eval", tags=["eval"])

@router.post("/runs", response_model=EvalRunResponse, dependencies=[Depends(api_key_header)])
def create_eval_run_endpoint(
    body: EvalRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id

    eval_run = start_eval_run(db, tenant_id, body.confidence_threshold_override)
    background_tasks.add_task(
        run_eval_in_background, eval_run.id, body.confidence_threshold_override
    )

    return EvalRunResponse(
        id=eval_run.id,
        dataset_version=eval_run.dataset_version,
        config=eval_run.config,
        created_at=eval_run.created_at,
        results=[],
    )

@router.get("/runs/{eval_run_id}", response_model=EvalRunResponse, dependencies=[Depends(api_key_header)])
def get_eval_run_endpoint(
    eval_run_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    eval_run = get_eval_run_for_tenant(db, eval_run_id, request.state.tenant_id)
    if eval_run is None:
        raise EvalRunNotFoundException()

    results = list_eval_results(db, eval_run_id)

    return EvalRunResponse(
        id=eval_run.id,
        dataset_version=eval_run.dataset_version,
        config=eval_run.config,
        created_at=eval_run.created_at,
        results=results,
    )
