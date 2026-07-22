from sqlalchemy.orm import Session

from app.models.eval import EvalResult, EvalRun

def create_eval_run(db: Session, tenant_id: int, dataset_version: str, config: dict) -> EvalRun:
    run = EvalRun(tenant_id=tenant_id, dataset_version=dataset_version, config=config)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run

def create_eval_result(
    db: Session,
    eval_run_id: int,
    question: str,
    faithfulness: float | None,
    answer_relevancy: float | None,
    context_precision: float | None,
) -> EvalResult:
    result = EvalResult(
        eval_run_id=eval_run_id,
        question=question,
        faithfulness=faithfulness,
        answer_relevancy=answer_relevancy,
        context_precision=context_precision,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result

def get_eval_run(db: Session, eval_run_id: int) -> EvalRun | None:
    """Untenant-scoped lookup for internal, trusted use only (the
    BackgroundTask started right after start_eval_run already knows the
    exact id it created). API-facing lookups must use
    get_eval_run_for_tenant instead - see routers/eval.py."""
    return db.query(EvalRun).filter(EvalRun.id == eval_run_id).first()

def get_eval_run_for_tenant(db: Session, eval_run_id: int, tenant_id: int) -> EvalRun | None:
    return (
        db.query(EvalRun)
        .filter(EvalRun.id == eval_run_id, EvalRun.tenant_id == tenant_id)
        .first()
    )

def list_eval_results(db: Session, eval_run_id: int) -> list[EvalResult]:
    return (
        db.query(EvalResult)
        .filter(EvalResult.eval_run_id == eval_run_id)
        .order_by(EvalResult.id)
        .all()
    )
