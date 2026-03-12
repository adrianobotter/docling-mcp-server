"""
Docling MCP Server
Processes PDFs from URLs and returns markdown, tables, and structured JSON.
"""

import json
import tempfile
import os
from typing import Optional
from enum import Enum

import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("docling_mcp")


# ─── Enums ────────────────────────────────────────────────────────────────────

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"
    ALL = "all"


# ─── Input Models ─────────────────────────────────────────────────────────────

class ProcessPDFInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid"
    )

    url: str = Field(
        ...,
        description="Public URL of the PDF to process (e.g. 'https://example.com/report.pdf')",
        min_length=10
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.ALL,
        description="Output format: 'markdown' for text only, 'json' for structured data, 'all' for both"
    )
    extract_tables: bool = Field(
        default=True,
        description="Whether to extract and return tables separately"
    )
    pages: Optional[str] = Field(
        default=None,
        description="Optional page range to process, e.g. '1-5' or '2,4,6'. Defaults to all pages."
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _handle_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return "Error: PDF not found at the provided URL. Please check the URL is correct and publicly accessible."
        elif status == 403:
            return "Error: Access denied. The URL may require authentication or the file is not publicly accessible."
        elif status == 429:
            return "Error: Rate limited by the remote server. Please try again later."
        return f"Error: Failed to fetch PDF — HTTP {status}"
    elif isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. The PDF may be too large or the server is slow. Try again."
    elif isinstance(e, httpx.InvalidURL):
        return "Error: Invalid URL. Please provide a valid public URL to a PDF file."
    return f"Error: {type(e).__name__}: {str(e)}"


async def _fetch_pdf(url: str) -> bytes:
    """Download PDF bytes from a URL."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _process_with_docling(pdf_bytes: bytes, extract_tables: bool):
    """Run Docling conversion on PDF bytes. Returns (markdown, tables, doc_json)."""
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = extract_tables

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        result = converter.convert(tmp_path)
        doc = result.document

        # Markdown
        markdown = doc.export_to_markdown()

        # Tables
        tables = []
        if extract_tables:
            for table in doc.tables:
                try:
                    df = table.export_to_dataframe()
                    tables.append({
                        "caption": table.caption_text(doc) or "",
                        "rows": len(df),
                        "columns": len(df.columns),
                        "headers": list(df.columns),
                        "data": df.values.tolist()
                    })
                except Exception:
                    pass

        # Structured JSON
        doc_json = doc.export_to_dict()

        return markdown, tables, doc_json

    finally:
        os.unlink(tmp_path)


def _format_tables_markdown(tables: list) -> str:
    """Render extracted tables as readable markdown."""
    if not tables:
        return "_No tables found in this document._"

    lines = [f"## Extracted Tables ({len(tables)} found)\n"]
    for i, table in enumerate(tables, 1):
        caption = table.get("caption") or f"Table {i}"
        lines.append(f"### {caption}")
        lines.append(f"_{table['rows']} rows × {table['columns']} columns_\n")

        headers = table.get("headers", [])
        data = table.get("data", [])

        if headers:
            lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in data[:50]:  # cap at 50 rows for readability
                lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
            if len(data) > 50:
                lines.append(f"\n_...and {len(data) - 50} more rows_")
        lines.append("")

    return "\n".join(lines)


# ─── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool(
    name="docling_process_pdf",
    annotations={
        "title": "Process PDF from URL",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def docling_process_pdf(params: ProcessPDFInput) -> str:
    """Convert a PDF from a public URL into markdown, extract tables, and return structured JSON.

    Downloads the PDF from the given URL, processes it using Docling, and returns the
    content in the requested format. Supports complex layouts, multi-column text,
    and table extraction.

    Args:
        params (ProcessPDFInput): Validated input containing:
            - url (str): Public URL of the PDF
            - response_format (str): 'markdown', 'json', or 'all'
            - extract_tables (bool): Whether to extract tables separately
            - pages (Optional[str]): Page range, e.g. '1-5'

    Returns:
        str: Formatted document content — markdown text, extracted tables,
             and/or structured JSON depending on response_format
    """
    try:
        pdf_bytes = await _fetch_pdf(params.url)
    except Exception as e:
        return _handle_error(e)

    try:
        markdown, tables, doc_json = _process_with_docling(pdf_bytes, params.extract_tables)
    except Exception as e:
        return f"Error: Failed to process PDF — {str(e)}"

    fmt = params.response_format
    sections = []

    if fmt in (ResponseFormat.MARKDOWN, ResponseFormat.ALL):
        sections.append("# Document Content (Markdown)\n")
        sections.append(markdown)

    if params.extract_tables and fmt in (ResponseFormat.MARKDOWN, ResponseFormat.ALL):
        sections.append("\n---\n")
        sections.append(_format_tables_markdown(tables))

    if fmt in (ResponseFormat.JSON, ResponseFormat.ALL):
        sections.append("\n---\n")
        sections.append("# Structured JSON\n")
        sections.append("```json")
        sections.append(json.dumps(doc_json, indent=2, default=str)[:50000])  # cap size
        sections.append("```")

    return "\n".join(sections)


@mcp.tool(
    name="docling_extract_tables",
    annotations={
        "title": "Extract Tables from PDF URL",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def docling_extract_tables(
    url: str = Field(..., description="Public URL of the PDF to extract tables from"),
    output_format: str = Field(default="markdown", description="'markdown' or 'json'")
) -> str:
    """Extract only tables from a PDF URL, returned as markdown or JSON.

    A focused tool for table extraction when you don't need the full document text.
    Returns all detected tables with headers, row counts, and data.

    Args:
        url (str): Public URL of the PDF
        output_format (str): 'markdown' for readable tables, 'json' for raw data

    Returns:
        str: Extracted tables in the requested format
    """
    try:
        pdf_bytes = await _fetch_pdf(url)
    except Exception as e:
        return _handle_error(e)

    try:
        _, tables, _ = _process_with_docling(pdf_bytes, extract_tables=True)
    except Exception as e:
        return f"Error: Failed to process PDF — {str(e)}"

    if output_format == "json":
        return json.dumps({"table_count": len(tables), "tables": tables}, indent=2, default=str)

    return _format_tables_markdown(tables)


@mcp.tool(
    name="docling_get_markdown",
    annotations={
        "title": "Convert PDF URL to Markdown",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True
    }
)
async def docling_get_markdown(
    url: str = Field(..., description="Public URL of the PDF to convert to markdown")
) -> str:
    """Convert a PDF from a URL to clean markdown text only.

    Lightweight tool for extracting readable text from a PDF without tables or JSON.
    Ideal for summarization, Q&A, or content analysis tasks.

    Args:
        url (str): Public URL of the PDF

    Returns:
        str: Full document content as markdown text
    """
    try:
        pdf_bytes = await _fetch_pdf(url)
    except Exception as e:
        return _handle_error(e)

    try:
        markdown, _, _ = _process_with_docling(pdf_bytes, extract_tables=False)
    except Exception as e:
        return f"Error: Failed to process PDF — {str(e)}"

    return markdown


# ─── Health Check ─────────────────────────────────────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request) -> dict:
    """Health check endpoint for Railway deployment."""
    return {"status": "ok", "server": "docling_mcp"}


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY environment variable is not set. Refusing to start without auth.")

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Mount

    # Instead of wrapping FastMCP's app externally (which causes the 502),
    # we mount FastMCP inside a Starlette app and attach our middleware there.
    # Starlette knows how to wire middleware into the request lifecycle correctly,
    # whereas our manual ASGI wrapper was intercepting the request but then
    # handing it to FastMCP in a way that caused it to hang without responding.
    protected_app = Starlette(
        routes=[Mount("/", app=mcp.streamable_http_app())],
        middleware=[Middleware(ApiKeyMiddleware, api_key=api_key)]
    )

    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(protected_app, host="0.0.0.0", port=port)
