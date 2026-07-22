"""Run the golden dataset through the real retrieval + answering pipeline
and score it with RAGAS, printing a summary.

Usage:
    python -m eval.run_eval
    python -m eval.run_eval --confidence-threshold -3.0
"""
import argparse
import logging
import statistics

from app.db.session import SessionLocal
from app.repositories.eval_runs import list_eval_results
from app.repositories.tenants import create_tenant, get_by_name
from app.services.evaluation import EVAL_TENANT_NAME, load_golden_dataset, run_evaluation


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description="Run eval/golden_dataset.json through the RAG pipeline and score it with RAGAS."
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=None,
        help="Override settings.confidence_threshold for this run only.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        requester = get_by_name(db, EVAL_TENANT_NAME) or create_tenant(db, name=EVAL_TENANT_NAME)
        eval_run = run_evaluation(
            db,
            requesting_tenant_id=requester.id,
            confidence_threshold_override=args.confidence_threshold,
        )
        results = list_eval_results(db, eval_run.id)
        dataset = load_golden_dataset()
    finally:
        db.close()

    refusal_questions = {
        item["question"] for item in dataset["items"] if item["category"] == "expected_refusal"
    }
    scored_results = [r for r in results if r.question not in refusal_questions]

    faithfulness_scores = [r.faithfulness for r in scored_results if r.faithfulness is not None]
    relevancy_scores = [r.answer_relevancy for r in scored_results if r.answer_relevancy is not None]
    precision_scores = [r.context_precision for r in scored_results if r.context_precision is not None]

    print(f"\nEval run {eval_run.id} (dataset {eval_run.dataset_version}), config: {eval_run.config}")
    print(f"Scored items:      {len(faithfulness_scores)}/{len(scored_results)} (rest timed out - see None scores)")
    print(f"Mean faithfulness:      {_mean(faithfulness_scores)}")
    print(f"Mean answer_relevancy:  {_mean(relevancy_scores)}")
    print(f"Mean context_precision: {_mean(precision_scores)}")


if __name__ == "__main__":
    main()
