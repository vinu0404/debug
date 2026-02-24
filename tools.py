"""
Tools for the Financial Document Analyzer.
"""

import os
import re

import fitz
from crewai.tools import tool
from crewai_tools import SerperDevTool
from logger import get_logger

logger = get_logger(__name__)

search_tool = SerperDevTool()


# ─── PDF Extraction Utility ────────────
def extract_pdf_text(file_path: str) -> str:
    """Read a PDF and return its full text. Called once per request
    in run_crew() so the text can be shared across all agents via
    the {document_text} input variable.

    This is NOT a CrewAI @tool — it's a plain function used by the
    orchestrator to avoid 4 redundant PDF reads.
    """
    if not os.path.exists(file_path):
        logger.error("PDF not found: %s", file_path)
        return f"Error: File not found at '{file_path}'."

    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logger.error("Failed to open PDF %s: %s", file_path, e)
        return f"Error opening PDF: {e}"

    full_report = ""
    page_count = doc.page_count
    for page in doc:
        text = page.get_text()
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        full_report += text + "\n"

    doc.close()
    logger.info("PDF extracted: %s (%d pages, %d chars)", file_path, page_count, len(full_report))
    return full_report.strip() if full_report.strip() else "The PDF contained no extractable text."


# ─── PDF Tool (fallback for agents that need to re-read) ────────────
@tool("read_financial_document")
def read_financial_document(file_path: str = "data/sample.pdf") -> str:
    """Read and extract text from a financial PDF document.

    Args:
        file_path: Path to the PDF file. Defaults to 'data/sample.pdf'.

    Returns:
        The full extracted text of the financial document.
    """
    
    if not os.path.exists(file_path):
        return f"Error: File not found at '{file_path}'."

    try:
        doc = fitz.open(file_path)
    except Exception as e:
        return f"Error opening PDF: {e}"

    full_report = ""
    for page in doc:
        text = page.get_text()
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        full_report += text + "\n"

    doc.close()
    return full_report.strip() if full_report.strip() else "The PDF contained no extractable text."


# ─── Investment Analysis Helper Tool ────────────────────────────────
@tool("analyze_investment_data")
def analyze_investment_data(financial_text: str) -> str:
    """Extract and highlight key financial figures (revenue, net income,
    margins, EPS, debt, cash) from financial text so the agent can build
    an investment thesis from real data.

    Args:
        financial_text: The raw text extracted from a financial document.

    Returns:
        Extracted financial metrics and data-rich sections for the agent
        to analyze.
    """
    if not financial_text or financial_text.strip() == "":
        logger.warning("analyze_investment_data called with empty text")
        return "No financial data provided for analysis."

    logger.info("Analyzing investment data – input length=%d chars", len(financial_text))
    money_pattern = r'\$[\d,]+\.?\d*\s*(?:million|billion|M|B|K)?'
    pct_pattern = r'[\d]+\.?\d*\s*%'

    metric_keywords = [
        "revenue", "net income", "gross profit", "operating income",
        "ebitda", "eps", "earnings per share", "free cash flow",
        "operating cash flow", "total assets", "total liabilities",
        "shareholders equity", "debt", "margin", "growth",
        "year-over-year", "quarter", "guidance", "outlook",
        "dividend", "buyback", "repurchase",
    ]

    paragraphs = [p.strip() for p in financial_text.split("\n\n") if p.strip()]
    if len(paragraphs) < 5:
        paragraphs = [p.strip() for p in financial_text.split("\n") if len(p.strip()) > 30]

    output = ["=== Financial Metrics Extraction ===", ""]
    money_matches = re.findall(money_pattern, financial_text, re.IGNORECASE)
    if money_matches:
        unique_amounts = list(dict.fromkeys(money_matches))[:20] 
        output.append(f"Monetary figures found ({len(money_matches)} total):")
        for amt in unique_amounts:
            output.append(f"  • {amt.strip()}")
        output.append("")

    pct_matches = re.findall(pct_pattern, financial_text)
    if pct_matches:
        unique_pcts = list(dict.fromkeys(pct_matches))[:15]
        output.append(f"Percentage figures found ({len(pct_matches)} total):")
        for p in unique_pcts:
            output.append(f"  • {p.strip()}")
        output.append("")

    metric_sections = []
    for para in paragraphs:
        para_lower = para.lower()
        matched = [kw for kw in metric_keywords if kw in para_lower]
        if matched and (re.search(money_pattern, para, re.IGNORECASE) or re.search(pct_pattern, para)):
            metric_sections.append((para[:600], matched))

    if metric_sections:
        output.append(f"Key financial sections ({len(metric_sections)} found):")
        for text, keywords in metric_sections[:10]:
            output.append(f"  Keywords: {', '.join(keywords)}")
            output.append(f"  Text: \"{text}\"")
            output.append("")

    if len(output) <= 2:
        output.append("No structured financial figures detected.")
        output.append("The agent should review the full document text directly.")
    else:
        output.append("The agent should now use these extracted figures for investment analysis.")

    return "\n".join(output)


# ─── Risk Assessment Helper Tool ────────────────────────────────────
@tool("assess_risk_factors")
def assess_risk_factors(financial_text: str) -> str:
    """Extract risk-relevant sections from financial text so the agent
    can perform a thorough LLM-based risk analysis.

    Args:
        financial_text: The raw text extracted from a financial document.

    Returns:
        Extracted risk-relevant paragraphs grouped by risk category,
        ready for the agent to analyze with LLM reasoning.
    """
    if not financial_text or financial_text.strip() == "":
        logger.warning("assess_risk_factors called with empty text")
        return "No financial data provided for risk assessment."

    logger.info("Assessing risk factors – input length=%d chars", len(financial_text))

    risk_categories = {
        "Credit & Debt Risk": [
            "debt", "default", "credit", "leverage", "borrowing",
            "interest expense", "covenant", "downgrade",
        ],
        "Market & Volatility Risk": [
            "volatility", "market risk", "currency", "exchange rate",
            "interest rate", "commodity", "inflation",
        ],
        "Legal & Regulatory Risk": [
            "litigation", "regulatory", "compliance", "lawsuit",
            "investigation", "penalty", "sanction", "SEC",
        ],
        "Operational Risk": [
            "restructuring", "impairment", "write-off", "supply chain",
            "cybersecurity", "disruption", "workforce",
        ],
        "Financial Health Concerns": [
            "decline", "loss", "adverse", "uncertainty", "contingent",
            "liability", "going concern", "liquidity risk",
        ],
    }

    paragraphs = [p.strip() for p in financial_text.split("\n\n") if p.strip()]
    if len(paragraphs) < 5:
        paragraphs = [p.strip() for p in financial_text.split("\n") if len(p.strip()) > 50]

    output = ["=== Risk-Relevant Sections Extracted for Analysis ===\n"]
    total_extracts = 0

    for category, keywords in risk_categories.items():
        relevant = []
        for para in paragraphs:
            para_lower = para.lower()
            matched_terms = [kw for kw in keywords if kw in para_lower]
            if matched_terms:
                relevant.append((para[:500], matched_terms))

        if relevant:
            output.append(f"\n── {category} ({len(relevant)} section(s)) ──")
            for text, terms in relevant[:5]:
                output.append(f"  Indicators: {', '.join(terms)}")
                output.append(f"  Text: \"{text}\"")
                output.append("")
            total_extracts += len(relevant)

    if total_extracts == 0:
        output.append("No explicit risk-related sections detected in the document.")
        output.append("The agent should review the full document for implicit risks.")
    else:
        output.append(f"\nTotal: {total_extracts} risk-relevant sections found across {len(risk_categories)} categories.")
        output.append("The agent should now perform qualitative analysis on these extracts.")

    return "\n".join(output)
