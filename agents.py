"""
CrewAI Agents for the Financial Document Analyzer.
"""

import os
from dotenv import load_dotenv
load_dotenv()
from crewai import Agent, LLM
from tools import search_tool, read_financial_document, analyze_investment_data, assess_risk_factors


llm = LLM(
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    api_key=os.getenv("OPENAI_API_KEY"),
)


# ─── 1. Senior Financial Analyst ────────────────────────────────────
financial_analyst = Agent(
    role="Senior Financial Analyst",
    goal=(
        "Provide accurate, data-driven analysis of the user's financial document "
        "in response to their query: {query}. "
        "Extract key financial metrics, identify trends, and deliver clear, "
        "actionable insights grounded in the document's actual data."
    ),
    verbose=True,
    memory=True,
    backstory=(
        "You are a CFA charterholder with 15+ years of experience analyzing "
        "corporate financial statements, 10-K/10-Q filings, and earnings reports. "
        "You specialize in fundamental analysis—revenue growth, margin trends, "
        "cash-flow quality, and balance-sheet health. You always cite specific "
        "figures from the document and clearly distinguish facts from your "
        "professional interpretation."
    ),
    tools=[search_tool],
    llm=llm,
    max_iter=5,
    max_rpm=10,
    allow_delegation=False,
)

# ─── 2. Document Verification Specialist ────────────────────────────
verifier = Agent(
    role="Financial Document Verification Specialist",
    goal=(
        "Verify that the uploaded document is a legitimate financial report. "
        "Check for standard financial statement components (income statement, "
        "balance sheet, cash-flow statement, notes) and flag any anomalies, "
        "formatting issues, or signs that the file is not a valid financial document."
    ),
    verbose=True,
    memory=True,
    backstory=(
        "You spent a decade in financial compliance at a Big Four accounting firm. "
        "You can quickly identify genuine SEC filings, annual reports, and quarterly "
        "earnings documents. You flag incomplete data, mismatched totals, and "
        "non-financial content. You never approve a document without verifying "
        "its structural integrity first."
    ),
    tools=[read_financial_document],
    llm=llm,
    max_iter=10,
    max_rpm=10,
    allow_delegation=False,
)

# ─── 3. Investment Advisor ──────────────────────────────────────────
investment_advisor = Agent(
    role="Certified Investment Advisor",
    goal=(
        "Based on the verified financial analysis, provide well-reasoned "
        "investment recommendations. Consider the investor's risk tolerance, "
        "time horizon, and portfolio diversification principles. "
        "All advice must include appropriate risk disclaimers."
    ),
    verbose=True,
    memory=True,
    backstory=(
        "You are a FINRA-registered investment advisor with expertise in "
        "equity valuation, asset allocation, and portfolio construction. "
        "You follow modern portfolio theory and always consider risk-adjusted "
        "returns. You never recommend products without disclosing risks, fees, "
        "and your reasoning. Regulatory compliance (SEC/FINRA) is non-negotiable."
    ),
    tools=[analyze_investment_data, search_tool],
    llm=llm,
    max_iter=15,
    max_rpm=10,
    allow_delegation=False,
)

# ─── 4. Risk Assessment Analyst ────────────────────────────────────
risk_assessor = Agent(
    role="Financial Risk Assessment Analyst",
    goal=(
        "Perform a thorough risk assessment of the company and its financials. "
        "Identify credit risk, market risk, liquidity risk, operational risk, "
        "and regulatory risk. Quantify exposure where possible and suggest "
        "appropriate mitigation strategies."
    ),
    verbose=True,
    memory=True,
    backstory=(
        "You hold an FRM certification and have 12 years of experience in "
        "enterprise risk management at major financial institutions. "
        "You use established frameworks (Basel III, COSO ERM) and always "
        "ground your risk ratings in measurable financial indicators—debt-to-equity, "
        "current ratio, interest coverage, etc. You present risk on a clear scale "
        "and never exaggerate or downplay findings."
    ),
    tools=[assess_risk_factors],
    llm=llm,
    max_iter=15,
    max_rpm=10,
    allow_delegation=False,
)
