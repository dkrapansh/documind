import hashlib


def compute_content_hash(file_bytes: bytes) -> str:
    """SHA-256 of the uploaded bytes, used as the per-tenant deduplication
    key so re-uploading the same file never pays to embed it twice."""
    return hashlib.sha256(file_bytes).hexdigest()


# save_file/load_file used to write the raw upload to a local `storage/`
# directory and read it back in the background job. They are gone, along with
# that directory, because the disk they wrote to is ephemeral on the
# deployment target: any restart between upload and ingestion destroyed the
# bytes, so the job could never succeed and no retry could fix it. Extracted
# text now lives in Postgres (models/document_content.py) alongside the
# document row, which is also what makes ingestion restartable.
#
# The tradeoff: the original bytes are not kept, so re-extracting with a
# better parser (or adding OCR later) needs a re-upload. Recorded here rather
# than only in a commit message, because "where did the raw file go" is the
# obvious question when reading this module.
