"""
CrewAI Tasks for the Financial Document Analyzer.
"""

from crewai import Task

from agents import financial_analyst, verifier, investment_advisor, risk_assessor
from tools import (
    read_financial_document,
    search_tool,
    analyze_investment_data,
    assess_risk_factors,
)


# ─── Task 1: Document Verification ──────────────────────────────────
verification_task = Task(
    description=(
        "Verify the uploaded financial document.\n\n"
        "The full document text has been pre-extracted and is provided below:\n"
        "--- START OF DOCUMENT ---\n"
        "{document_text}\n"
        "--- END OF DOCUMENT ---\n\n"
        "1. Check whether it contains standard financial statement components "
        "(income statement, balance sheet, cash-flow statement, notes/disclosures).\n"
        "2. Flag any structural issues, missing sections, or indications that "
        "the file is NOT a legitimate financial document.\n"
        "3. Provide a clear PASS / FAIL verification verdict with reasoning.\n"
        "4. If needed, use the read_financial_document tool to re-read the original file."
    ),
    expected_output=(
        "A structured verification report containing:\n"
        "- Document type identified (e.g., 10-K, 10-Q, Annual Report, Earnings Release)\n"
        "- Sections found vs. expected\n"
        "- Data quality observations\n"
        "- Verdict: PASS or FAIL with justification"
    ),
    agent=verifier,
    tools=[read_financial_document],
    async_execution=False,
)


# ─── Task 2: Financial Analysis ─────────────────────────────────────
financial_analysis_task = Task(
    description=(
        "Perform a comprehensive financial analysis in response to the "
        "user's query: {query}\n\n"
        "The full document text has been pre-extracted and is provided below:\n"
        "--- START OF DOCUMENT ---\n"
        "{document_text}\n"
        "--- END OF DOCUMENT ---\n\n"
        "1. Extract and analyze key financial metrics: revenue, net income, "
        "operating margins, EPS, debt levels, and cash-flow figures.\n"
        "2. Identify year-over-year or quarter-over-quarter trends.\n"
        "3. Supplement with current market context using the search tool where relevant.\n"
        "4. Provide clear, data-backed answers to the user's specific query."
    ),
    expected_output=(
        "A detailed financial analysis report including:\n"
        "- Executive summary addressing the user's query\n"
        "- Key financial metrics with actual figures from the document\n"
        "- Trend analysis (growth rates, margin changes)\n"
        "- Comparison to industry benchmarks where available\n"
        "- Clearly labeled sources (document page references, search results)"
    ),
    agent=financial_analyst,
    tools=[search_tool],
    async_execution=False,
)


# ─── Task 3: Risk Assessment ────────────────────────────────────────
risk_assessment_task = Task(
    description=(
        "Conduct a thorough risk assessment based on the financial document.\n"
        "User context: {query}\n\n"
        "The full document text has been pre-extracted and is provided below:\n"
        "--- START OF DOCUMENT ---\n"
        "{document_text}\n"
        "--- END OF DOCUMENT ---\n\n"
        "1. Use the assess_risk_factors tool with the document text above to "
        "scan for risk indicators.\n"
        "2. Evaluate credit risk, market risk, liquidity risk, and operational risk.\n"
        "3. Analyze debt ratios, interest coverage, current ratio, and cash reserves.\n"
        "4. Identify specific risk factors mentioned in management discussion sections.\n"
        "5. Rate each risk category (Low / Medium / High) with supporting data."
    ),
    expected_output=(
        "A structured risk assessment report:\n"
        "- Risk summary matrix (category, rating, key indicator)\n"
        "- Detailed analysis per risk category with supporting financial data\n"
        "- Comparison to industry risk benchmarks\n"
        "- Recommended risk mitigation strategies\n"
        "- Overall risk rating with confidence level"
    ),
    agent=risk_assessor,
    tools=[assess_risk_factors],
    async_execution=False,
)


# ─── Task 4: Investment Recommendation ──────────────────────────────
investment_analysis_task = Task(
    description=(
        "Provide investment recommendations based on the financial analysis "
        "and risk assessment.\n"
        "User query: {query}\n\n"
        "The full document text has been pre-extracted and is provided below:\n"
        "--- START OF DOCUMENT ---\n"
        "{document_text}\n"
        "--- END OF DOCUMENT ---\n\n"
        "1. Review the financial analysis findings and risk assessment results.\n"
        "2. Use the analyze_investment_data tool with the document text to extract "
        "key financial figures.\n"
        "3. Evaluate the company's investment merit: valuation, growth prospects, "
        "competitive position, and management quality.\n"
        "4. Consider macroeconomic factors using the search tool.\n"
        "5. Formulate a clear investment thesis (Buy / Hold / Sell or equivalent).\n"
        "6. Include appropriate risk disclaimers and suitability considerations."
    ),
    expected_output=(
        "A professional investment recommendation report:\n"
        "- Investment thesis summary (1-2 paragraphs)\n"
        "- Valuation assessment with key ratios (P/E, P/B, EV/EBITDA if available)\n"
        "- Bull case and bear case scenarios\n"
        "- Recommended action with target price range (if applicable)\n"
        "- Risk disclaimers and investor suitability notes\n"
        "- Disclaimer: This is AI-generated analysis, not personalized financial advice"
    ),
    agent=investment_advisor,
    tools=[analyze_investment_data, search_tool],
    async_execution=False,
)

