import datetime
import logging
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Text,
    DateTime,
    Enum as SAEnum,
    Integer,
)
from sqlalchemy.orm import declarative_base, sessionmaker
import enum

from config import DATABASE_URL
from logger import get_logger

logger = get_logger(__name__)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class AnalysisStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class AnalysisResult(Base):
    """Stores each financial-document analysis request and its result."""

    __tablename__ = "analysis_results"

    id = Column(String(36), primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    query = Column(Text, nullable=False)
    status = Column(
        SAEnum(AnalysisStatus),
        default=AnalysisStatus.PENDING,
        nullable=False,
    )
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<AnalysisResult(id={self.id}, status={self.status})>"


class UserRecord(Base):
    """Basic user tracking (API consumers)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<UserRecord(id={self.id}, name={self.name})>"


def init_db():
    """Create all tables if they don't exist."""
    logger.info("Creating database tables (if not exist)")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready")


def get_db():
    """FastAPI dependency – yields a DB session and auto-closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
