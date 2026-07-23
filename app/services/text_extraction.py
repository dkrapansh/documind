import io 
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

from app.core.exceptions import UnsupportedFileTypeException

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}

def validate_extension(filename: str) -> None:
    """
    Reject unsupported file types immediately at upload time, before
    saving to disk or scheduling a background job that would only fail
    later with no direct feedback to the client.
    """
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeException(extension)
    

def extract_text(file_bytes: bytes, fileame: str) -> str:
    """ Turn a saved file's raw bytes into plain text, based on its extension.
    .txt  -> decode as UTF-8 directly.
    .pdf  -> read the embedded text layer via pypdf. Scanned/image-only
             PDFs have no text layer and extract as empty string — a
             known, deliberate limitation (OCR is out of scope).
    .docx -> read paragraph text plus any table cell text via
             python-docx. Table content is appended after paragraphs,
             not interleaved at its true position: acceptable since
             chunking cares about content, not exact reading order.
    """
    extension = Path(fileame).suffix.lower()

    if extension == ".txt":
        return file_bytes.decode("utf-8")
    
    if extension == ".pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    
    if extension == ".docx":
        doc = DocxDocument(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        table_cells = [ 
            cell.text
            for table in doc.tables
            for row in table.rows
            for cell in row.cells
            if cell.text.strip()
        ]
        return "\n\n".join(paragraphs + table_cells)
    
    raise UnsupportedFileTypeException(extension)