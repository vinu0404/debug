"""
FastAPI application for the Financial Document Analyzer.
"""

import os
import uuid
import datetime
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends
from sqlalchemy.orm import Session
import uvicorn
from crewai import Crew, Process

from agents import financial_analyst, verifier, investment_advisor, risk_assessor
from task import (
    verification_task,
    financial_analysis_task,
    risk_assessment_task,
    investment_analysis_task,
)
from config import DATA_DIR, OUTPUTS_DIR, MAX_UPLOAD_SIZE_MB
from database import init_db, get_db, AnalysisResult, AnalysisStatus
from logger import get_logger

logger = get_logger(__name__)


def save_analysis_output(analysis_id: str, filename: str, query: str, result: str) -> str:
    """Save the analysis result to a text file in outputs/.

    Returns the path of the saved file.
    """
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    safe_name = os.path.splitext(filename)[0].replace(" ", "_")[:50]
    out_file = os.path.join(OUTPUTS_DIR, f"{safe_name}_{analysis_id[:8]}.txt")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"Financial Document Analysis Report\n")
        f.write(f"Analysis ID : {analysis_id}\n")
        f.write(f"Source File : {filename}\n")
        f.write(f"Query       : {query}\n")
        f.write(f"Generated   : {datetime.datetime.utcnow().isoformat()}\n")
        f.write(f"\n\n")
        f.write(result)

    logger.info("[%s] Analysis saved to %s", analysis_id, out_file)
    return out_file


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables and ensure directories exist."""
    logger.info("Application startup – initialising directories and database")
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs("outputs", exist_ok=True)
    try:
        init_db()
        logger.info("Database tables initialised successfully")
    except Exception as e:
        logger.warning("Could not initialise database (continuing without DB): %s", e)
    yield
    logger.info("Application shutdown")


app = FastAPI(
    title="Financial Document Analyzer",
    description="AI-powered financial document analysis with CrewAI agents.",
    version="1.0.0",
    lifespan=lifespan,
)


def run_crew(query: str, file_path: str = "data/sample.pdf") -> str:
    """Build and kick off the full analysis crew.

    The PDF is read ONCE here and passed as {document_text} to all agents,
    avoiding 4 redundant reads of the same file.
    """
    from tools import extract_pdf_text
    logger.info("Starting crew analysis – query=%r, file=%s", query, file_path)
    document_text = extract_pdf_text(file_path)
    logger.info("PDF extracted – %d characters", len(document_text))

    financial_crew = Crew(
        agents=[verifier, financial_analyst, risk_assessor, investment_advisor],
        tasks=[
            verification_task,
            financial_analysis_task,
            risk_assessment_task,
            investment_analysis_task,
        ],
        process=Process.sequential,
        verbose=True,
    )

    result = financial_crew.kickoff(inputs={
        "query": query,
        "file_path": file_path,
        "document_text": document_text,
    })
    logger.info("Crew analysis complete – result length=%d chars", len(str(result)))
    return str(result)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "Financial Document Analyzer API is running"}


@app.post("/analyze")
async def analyze_document(
    file: UploadFile = File(...),
    query: str = Form(
        default="Analyze this financial document for investment insights"
    ),
    db: Session = Depends(get_db),
):
    """Upload a financial PDF and receive a comprehensive AI analysis.

    The system runs four specialist agents sequentially:
    1. **Verification** – confirms the document is a valid financial report
    2. **Financial Analysis** – extracts metrics and answers your query
    3. **Risk Assessment** – evaluates risk factors
    4. **Investment Advice** – provides actionable recommendations
    """

    file_id = str(uuid.uuid4())
    file_path = os.path.join(DATA_DIR, f"financial_document_{file_id}.pdf")
    logger.info("[%s] Sync analysis request – file=%s, query=%r", file_id, file.filename, query)
    record = AnalysisResult(
        id=file_id,
        filename=file.filename or "unknown.pdf",
        query=query,
        status=AnalysisStatus.PENDING,
    )
    db.add(record)
    db.commit()

    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {MAX_UPLOAD_SIZE_MB} MB limit.",
            )
        with open(file_path, "wb") as f:
            f.write(content)

        if not query or query.strip() == "":
            query = "Analyze this financial document for investment insights"
        record.status = AnalysisStatus.PROCESSING
        db.commit()
        response = await asyncio.to_thread(run_crew, query=query.strip(), file_path=file_path)
        record.status = AnalysisStatus.COMPLETED
        record.result = response
        record.completed_at = datetime.datetime.utcnow()
        db.commit()

        out_path = save_analysis_output(file_id, file.filename or "unknown.pdf", query, response)
        logger.info("[%s] Analysis completed successfully", file_id)

        return {
            "status": "success",
            "analysis_id": file_id,
            "query": query,
            "analysis": response,
            "file_processed": file.filename,
            "output_file": out_path,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[%s] Analysis failed: %s", file_id, e, exc_info=True)
        record.status = AnalysisStatus.FAILED
        record.error = str(e)
        db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Error processing financial document: {str(e)}",
        )
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


# ─── Async endpoint (Celery) ────────────────────────────────────────
@app.post("/analyze-async")
async def analyze_document_async(
    file: UploadFile = File(...),
    query: str = Form(
        default="Analyze this financial document for investment insights"
    ),
    db: Session = Depends(get_db),
):
    """Submit a financial document for **background** analysis via Celery.

    Returns with an `analysis_id` , can poll via
    `GET /analysis/{analysis_id}`.
    """
    from celery_worker import analyze_document_task

    file_id = str(uuid.uuid4())
    file_path = os.path.join(DATA_DIR, f"financial_document_{file_id}.pdf")
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {MAX_UPLOAD_SIZE_MB} MB limit.",
        )
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(content)

    if not query or query.strip() == "":
        query = "Analyze this financial document for investment insights"
    record = AnalysisResult(
        id=file_id,
        filename=file.filename or "unknown.pdf",
        query=query.strip(),
        status=AnalysisStatus.PENDING,
    )
    db.add(record)
    db.commit()
    analyze_document_task.delay(file_id, query.strip(), file_path)
    logger.info("[%s] Async analysis queued – file=%s", file_id, file.filename)

    return {
        "status": "accepted",
        "analysis_id": file_id,
        "message": "Analysis queued. Poll GET /analysis/{analysis_id} for results.",
    }


# ─── Poll / list results ────────────────────────────────────────────
@app.get("/analysis/{analysis_id}")
async def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    """Retrieve the status and result of an analysis by ID."""
    record = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return {
        "analysis_id": record.id,
        "status": record.status.value,
        "filename": record.filename,
        "query": record.query,
        "result": record.result,
        "error": record.error,
        "created_at": str(record.created_at),
        "completed_at": str(record.completed_at) if record.completed_at else None,
    }


@app.get("/analyses")
async def list_analyses(
    skip: int = 0, limit: int = 20, db: Session = Depends(get_db)
):
    """List recent analyses (paginated)."""
    records = (
        db.query(AnalysisResult)
        .order_by(AnalysisResult.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "analysis_id": r.id,
            "status": r.status.value,
            "filename": r.filename,
            "query": r.query,
            "created_at": str(r.created_at),
            "completed_at": str(r.completed_at) if r.completed_at else None,
        }
        for r in records
    ]


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
