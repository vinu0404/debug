"""
Celery worker for background financial-document analysis.
"""

import os
import datetime

from celery import Celery
from config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND, OUTPUTS_DIR
from logger import get_logger

logger = get_logger(__name__)

celery_app = Celery(
    "financial_analyzer",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1, 
)


@celery_app.task(name="analyze_document", bind=True, max_retries=2)
def analyze_document_task(self, analysis_id: str, query: str, file_path: str):
    """Background task: run the full CrewAI pipeline and persist results to DB."""
    from database import SessionLocal, AnalysisResult, AnalysisStatus
    from crewai import Crew, Process
    from agents import financial_analyst, verifier, investment_advisor, risk_assessor
    from task import (
        verification_task,
        financial_analysis_task,
        risk_assessment_task,
        investment_analysis_task,
    )

    logger.info("[%s] Celery task started – query=%r, file=%s", analysis_id, query, file_path)
    db = SessionLocal()
    record = None  

    try:
        record = db.query(AnalysisResult).filter(AnalysisResult.id == analysis_id).first()
        if not record:
            logger.error("[%s] DB record not found – aborting", analysis_id)
            return {"error": "Record not found"}

        record.status = AnalysisStatus.PROCESSING
        db.commit()
        crew = Crew(
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

        from tools import extract_pdf_text
        document_text = extract_pdf_text(file_path)

        result = crew.kickoff(inputs={
            "query": query,
            "file_path": file_path,
            "document_text": document_text,
        })

        record.status = AnalysisStatus.COMPLETED
        record.result = str(result)
        record.completed_at = datetime.datetime.utcnow()
        db.commit()
        os.makedirs(OUTPUTS_DIR, exist_ok=True)
        safe_name = os.path.splitext(record.filename)[0].replace(" ", "_")[:50]
        out_file = os.path.join(OUTPUTS_DIR, f"{safe_name}_{analysis_id[:8]}.txt")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"Financial Document Analysis Report\n")
            f.write(f"Analysis ID : {analysis_id}\n")
            f.write(f"Source File : {record.filename}\n")
            f.write(f"Query       : {query}\n")
            f.write(f"Generated   : {datetime.datetime.utcnow().isoformat()}\n")
            f.write(f"\n \n")
            f.write(str(result))
        logger.info("[%s] Celery task completed – saved to %s", analysis_id, out_file)

        return {"status": "completed", "analysis_id": analysis_id, "output_file": out_file}

    except Exception as exc:
        logger.error("[%s] Celery task failed (attempt %d): %s", analysis_id, self.request.retries + 1, exc, exc_info=True)
        if record:
            record.status = AnalysisStatus.FAILED
            record.error = str(exc)
            db.commit()
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))

    finally:
        db.close()
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
