"""Seed the demo tenant's corpus, idempotently.

The public landing-page demo works by cloning a seed tenant's ready documents
into a fresh ephemeral tenant for each visitor (services/demo_seed.py). That
seed tenant's content used to exist only as rows in the production database,
uploaded by hand and never committed. Two consequences, both real:

  - A fresh deploy, or a restored-from-backup database, had an empty demo.
    Every question refused, including the landing page's own preset, because
    there was nothing to retrieve.
  - The corpus could not be reviewed, changed, or reasoned about, since it
    was not in the repository. A preset was once repointed at questions the
    real corpus could not answer precisely because the real corpus could not
    be read.

This script makes the corpus reproducible: the files in eval/demo_corpus/ are
the source of truth, and running this brings any database in line with them.

Usage:
    python -m scripts.seed_demo_corpus                    # uses DATABASE_URL
    python -m scripts.seed_demo_corpus --url "postgresql+psycopg://..."
    python -m scripts.seed_demo_corpus --dry-run          # report, change nothing

Safe to re-run. Documents are deduplicated by content hash, so an unchanged
file is skipped without paying to embed it again. Editing a file changes its
hash, so it is ingested as a new document; pass --replace to delete the
tenant's existing documents first rather than accumulating both versions.
"""
import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEMO_CORPUS_DIR = REPO_ROOT / "eval" / "demo_corpus"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("DATABASE_URL"),
        help="Database URL. Defaults to $DATABASE_URL.",
    )
    parser.add_argument(
        "--tenant",
        default=None,
        help="Seed tenant name. Defaults to settings.seed_tenant_name.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete the seed tenant's existing documents first, instead of adding to them.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    args = parser.parse_args()

    if not args.url:
        print("No database URL. Pass --url or set DATABASE_URL.", file=sys.stderr)
        return 2

    # Set before importing app.config, which reads it at import time.
    os.environ["DATABASE_URL"] = args.url

    from app.config import settings
    from app.db.session import SessionLocal
    from app.repositories.chunks import delete_by_tenant as delete_chunks_by_tenant
    from app.repositories.document_contents import (
        delete_by_tenant as delete_contents_by_tenant,
        upsert_content,
    )
    from app.repositories.documents import (
        claim_next_pending,
        create_document,
        delete_by_tenant as delete_documents_by_tenant,
        get_by_content_hash,
        list_by_tenant,
    )
    from app.repositories.tenants import create_tenant, get_by_name
    from app.services.file_storage import compute_content_hash
    from app.services.ingestion import process_document
    from app.services.text_extraction import extract_text

    tenant_name = args.tenant or settings.seed_tenant_name

    if not DEMO_CORPUS_DIR.is_dir():
        print("No corpus directory at %s" % DEMO_CORPUS_DIR, file=sys.stderr)
        return 1

    corpus_files = sorted(
        p for p in DEMO_CORPUS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in (".txt", ".pdf", ".docx")
    )
    if not corpus_files:
        print("No .txt/.pdf/.docx files in %s" % DEMO_CORPUS_DIR, file=sys.stderr)
        return 1

    print("corpus:  %s (%d file(s))" % (DEMO_CORPUS_DIR, len(corpus_files)))
    print("tenant:  %r" % tenant_name)
    if args.dry_run:
        print("mode:    DRY RUN, nothing will be written")

    db = SessionLocal()
    try:
        tenant = get_by_name(db, tenant_name)
        if tenant is None:
            print("tenant %r does not exist, will create" % tenant_name)
            if args.dry_run:
                return 0
            # is_ephemeral=False: the seed tenant is the source every demo
            # visitor's tenant is cloned from, so the expiry sweep must never
            # collect it.
            tenant = create_tenant(db, tenant_name, is_ephemeral=False)
            db.commit()
        else:
            existing = list_by_tenant(db, tenant.id)
            print("tenant exists (id=%d) with %d document(s)" % (tenant.id, len(existing)))

        if args.replace:
            print("--replace: deleting existing documents for this tenant")
            if not args.dry_run:
                delete_chunks_by_tenant(db, tenant.id)
                delete_contents_by_tenant(db, tenant.id)
                delete_documents_by_tenant(db, tenant.id)
                db.commit()

        seeded = skipped = failed = 0
        for path in corpus_files:
            file_bytes = path.read_bytes()
            content_hash = compute_content_hash(file_bytes)

            if get_by_content_hash(db, tenant.id, content_hash) is not None:
                print("  skip    %s (already present, unchanged)" % path.name)
                skipped += 1
                continue

            # Same filename, different content hash. Deduplication is by
            # content, so this would sail past the check above and leave the
            # tenant holding two copies of the same document under one name.
            # The demo clones every ready document into each visitor's
            # tenant, so a duplicate is not cosmetic: it distorts BM25 term
            # statistics, lets RRF fuse a chunk with itself, and lets the
            # same text occupy several slots in the final reranked context.
            #
            # This is a live risk for exactly this corpus. The committed file
            # was recovered from a stored chunk rather than the original
            # upload, so a trailing newline or CRLF difference is enough to
            # change its hash while the text a reader sees is identical.
            same_name = [d for d in list_by_tenant(db, tenant.id) if d.filename == path.name]
            if same_name and not args.replace:
                print("  SKIP    %s: a document with this name already exists (ids %s)"
                      % (path.name, ", ".join(str(d.id) for d in same_name)))
                print("          Its content differs from the committed file, so seeding")
                print("          would add a second copy rather than update it.")
                print("          Re-run with --replace to rebuild this tenant's corpus.")
                skipped += 1
                continue

            if args.dry_run:
                print("  would seed %s" % path.name)
                seeded += 1
                continue

            # Mirrors the real upload route: extract, store the text, create
            # the document, then run the job. Deliberately not a shortcut that
            # writes chunks directly, so the demo corpus is produced by the
            # same pipeline real uploads go through.
            try:
                extracted_text = extract_text(file_bytes, path.name)
            except Exception as exc:
                print("  FAILED  %s: could not extract (%s)" % (path.name, type(exc).__name__))
                failed += 1
                continue

            if not extracted_text.strip():
                print("  FAILED  %s: no readable text" % path.name)
                failed += 1
                continue

            document = create_document(db, tenant.id, path.name, content_hash)
            upsert_content(db, document.id, extracted_text)
            db.commit()

            # Claim it the way the worker would, so attempt_count and the
            # lease are set consistently rather than left in a state no real
            # ingestion would produce.
            claimed_id = claim_next_pending(
                db,
                lease_seconds=settings.ingestion_lease_seconds,
                max_attempts=settings.ingestion_max_attempts,
            )
            if claimed_id is None:
                print("  FAILED  %s: could not claim its ingestion job" % path.name)
                failed += 1
                continue

            process_document(claimed_id)
            db.expire_all()
            final = get_by_content_hash(db, tenant.id, content_hash)
            status = final.status if final is not None else "missing"
            if status == "ready":
                print("  seeded  %s (%d chunk(s))" % (path.name, final.chunk_count))
                seeded += 1
            else:
                print("  FAILED  %s: status=%s reason=%s"
                      % (path.name, status, getattr(final, "error_reason", None)))
                failed += 1

        print("\nseeded=%d skipped=%d failed=%d" % (seeded, skipped, failed))

        ready = [d for d in list_by_tenant(db, tenant.id) if d.status == "ready"]
        print("tenant %r now has %d ready document(s)" % (tenant_name, len(ready)))
        if not ready and not args.dry_run:
            print("WARNING: no ready documents, the demo will refuse every question",
                  file=sys.stderr)
            return 1
        return 1 if failed else 0

    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
