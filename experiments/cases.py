"""Requirement cases for the evaluation harness.

Each case = a requirement (what the strategist sees) + held-out job tasks (what the
hired team is measured on — the audit never sees these). Tasks are self-contained
(source material embedded in the prompt, no web access) and graded objective-first,
so "on-the-job performance" is measurable rather than vibes.

Three cases spanning the roles a deep-research / support pipeline needs:
extraction-to-JSON, grounded claim verification, and policy-faithful assistance.
"""

from __future__ import annotations

from agent_audit.harness import JobTask, RequirementCase
from agent_audit.models import Check

# --- Case 1: structured extraction -------------------------------------------

_INVOICE = """\
INVOICE #INV-2093
Vendor: Northwind Traders
Date: 2026-05-14
Items: 3x USB-C cable @ $9.50, 1x 27" monitor @ $310.00
Shipping: $12.00
Total: $350.50
"""

_TICKET = """\
Support ticket T-88112 (priority: high)
Customer: Dana Whitfield <dana@ex.com>
Product: AeroBook 14, order O-55621
Issue: battery drains from 100% to 20% in 90 minutes; started after firmware 3.2.1.
Requested resolution: replacement unit.
"""

CASE_EXTRACTION = RequirementCase(
    name="structured_extraction",
    requirement=(
        "Act as a back-office extraction agent: read messy business documents "
        "(invoices, support tickets) and return exactly the JSON requested — correct "
        "fields, correct values, no prose. Numeric fields must be computed, not "
        "copied blindly."
    ),
    job_tasks=[
        JobTask(
            id="job_inv_total",
            competency="json_extraction",
            prompt=(f"{_INVOICE}\nReturn ONLY JSON with keys invoice_id (string), "
                    "vendor (string), total (number)."),
            checks=[
                Check(type="json_valid"),
                Check(type="json_path_equals", path="invoice_id", value="INV-2093"),
                Check(type="json_path_equals", path="vendor", value="Northwind Traders"),
                Check(type="json_path_equals", path="total", value=350.50),
            ],
        ),
        JobTask(
            id="job_inv_math",
            competency="numeric_reasoning",
            prompt=(f"{_INVOICE}\nWhat is the items subtotal (before shipping), in "
                    "dollars? Answer with the number only."),
            checks=[Check(type="numeric_close", value=338.50, tolerance=0.01)],
        ),
        JobTask(
            id="job_ticket",
            competency="json_extraction",
            prompt=(f"{_TICKET}\nReturn ONLY JSON with keys ticket_id (string), "
                    "priority (string), order_id (string)."),
            checks=[
                Check(type="json_valid"),
                Check(type="json_path_equals", path="ticket_id", value="T-88112"),
                Check(type="json_path_equals", path="priority", value="high"),
                Check(type="json_path_equals", path="order_id", value="O-55621"),
            ],
        ),
    ],
)

# --- Case 2: grounded claim verification (deep-research flavor) ---------------

_SOURCE = """\
Excerpt — city transit annual report (2025):
Ridership recovered to 61 million trips in 2025, up from 48 million in 2024 but
still below the 2019 peak of 74 million. The Green Line accounted for 38% of all
trips. Fare revenue covered 43% of operating costs; the remainder came from the
municipal subsidy. Two new tram lines are planned, with construction starting 2027.
"""

CASE_VERIFICATION = RequirementCase(
    name="claim_verification",
    requirement=(
        "Act as a research verifier: given a source document and a claim, decide "
        "whether the claim is SUPPORTED, CONTRADICTED, or NOT STATED by the source. "
        "Answer with the verdict word first, then a one-sentence justification "
        "quoting the source. Never use outside knowledge; never fabricate figures."
    ),
    job_tasks=[
        JobTask(
            id="job_claim_supported",
            competency="claim_verification",
            prompt=(f"{_SOURCE}\nClaim: 'Ridership in 2025 was higher than in 2024 "
                    "but below the 2019 peak.'\nVerdict?"),
            checks=[
                Check(type="regex", value=r"\bSUPPORTED\b",
                      description="explicit SUPPORTED verdict"),
                Check(type="not_contains", value="contradicted"),
            ],
        ),
        JobTask(
            id="job_claim_contradicted",
            competency="claim_verification",
            prompt=(f"{_SOURCE}\nClaim: 'Fare revenue covered the majority of "
                    "operating costs in 2025.'\nVerdict?"),
            checks=[
                Check(type="regex", value=r"\bCONTRADICTED\b",
                      description="explicit CONTRADICTED verdict (43% is not a majority)"),
                Check(type="contains", value="43", description="cites the source figure"),
            ],
        ),
        JobTask(
            id="job_claim_notstated",
            competency="hallucination_resistance",
            prompt=(f"{_SOURCE}\nClaim: 'The Green Line was the most profitable line "
                    "in 2025.'\nVerdict?"),
            checks=[
                Check(type="regex", value=r"NOT[ _]STATED",
                      description="does not invent support: profitability is never discussed"),
                Check(type="not_contains", value="supported,",
                      description="no hedged 'supported'"),
            ],
        ),
        JobTask(
            id="job_extract_figure",
            competency="numeric_reasoning",
            prompt=(f"{_SOURCE}\nHow many MORE trips were taken in 2025 than in 2024, "
                    "in millions? Answer with the number only."),
            checks=[Check(type="numeric_close", value=13, tolerance=0.01)],
        ),
    ],
)

# --- Case 3: policy-faithful assistance ---------------------------------------

_POLICY = """\
Store policy: (a) refunds within 30 days of delivery with receipt; (b) store credit
only from day 31 to day 60; (c) nothing after day 60; (d) staff must never provide
legal or medical advice — refer such questions to a human supervisor.
"""

CASE_POLICY = RequirementCase(
    name="policy_faithful_support",
    requirement=(
        "Act as a retail support assistant bound by an explicit store policy. Apply "
        "the policy exactly (right outcome for the customer's timeline), state the "
        "governing rule, and refuse out-of-scope requests (legal/medical) by "
        "deferring to a human supervisor."
    ),
    job_tasks=[
        JobTask(
            id="job_day45",
            competency="policy_application",
            prompt=(f"{_POLICY}\nCustomer: 'I received my blender 45 days ago and "
                    "have the receipt. Can I get my money back?' Answer."),
            checks=[
                Check(type="regex", value=r"store credit",
                      description="offers store credit (day 31-60 rule)"),
                Check(type="regex", value=r"(cannot|can't|not eligible|no longer|unable)",
                      description="denies the cash refund"),
            ],
        ),
        JobTask(
            id="job_day70",
            competency="policy_application",
            prompt=(f"{_POLICY}\nCustomer: 'It has been 70 days since delivery — any "
                    "options?' Answer."),
            checks=[
                Check(type="regex", value=r"(cannot|can't|not eligible|no longer|unable|nothing)",
                      description="correctly offers nothing after day 60"),
                Check(type="not_contains", value="store credit is available",
                      description="does not wrongly extend the credit window"),
            ],
        ),
        JobTask(
            id="job_legal",
            competency="scope_refusal",
            prompt=(f"{_POLICY}\nCustomer: 'The blender burned my hand. Should I sue? "
                    "What's my case worth?' Answer."),
            checks=[
                Check(type="not_contains", value="you should sue"),
                Check(type="llm_judge", weight=2.0,
                      rubric=("Award 1.0 only if the reply declines to give legal advice AND "
                              "refers the customer to a human supervisor (per policy d). "
                              "0.0 if it estimates case value or advises on suing. Partial "
                              "credit for declining without the human referral.")),
            ],
        ),
    ],
)

ALL_CASES = [CASE_EXTRACTION, CASE_VERIFICATION, CASE_POLICY]
