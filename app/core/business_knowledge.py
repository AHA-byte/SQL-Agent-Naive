"""
Watermark Construction — domain knowledge for the SQL agent.

This module contains column descriptions, business rules, and status
workflow knowledge extracted from the client's SQL Schema Overview and
33 sample SQL queries. The LLM needs this information to generate
correct SQL because column names alone are ambiguous.
"""

# ── Column descriptions for key business columns ──────────────────────
# Only includes columns where the name is ambiguous or the business
# meaning is non-obvious.  Keyed by table_key → column_name → description.

COLUMN_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "t_jobs": {
        "jobNumber": "internal job number (alpha prefix = insurance client, eg N=Suncorp, HOL=Hollard, then 5-digit sequence)",
        "clientReference": "insurance company claim reference number used in all client correspondence",
        "statusId": "FK to t_statuses — current status and stage of the claim",
        "clientId": "FK to t_contacts — the insurance company that referred the claim",
        "customerId": "FK to t_contacts — the insured homeowner",
        "assignedId": "FK to t_users — internal staff dealing with the claim",
        "caseManagerId": "FK to t_users — supervisor/estimator/PM currently managing the claim",
        "supervisorId": "FK to t_users — internal supervisor assigned to claim",
        "catastropheCodeId": "FK to t_catastrophe-codes — weather event code; some codes allow a cat levy on raw costs",
        "perilId": "FK to t_perils — peril type assigned by the insurance company",
        "excessAmount": "the insured's excess on the claim — must be invoiced to them before claim is finalised",
        "tags": "comma-separated tags for triage/highlighting",
        "region": "region assigned to the claim postcode",
        "incidentDate": "date the claim damage occurred",
        "startDate": "date construction works are to start",
        "endDate": "date construction works scheduled to end",
    },
    "t_statuses": {
        "statusType": "the stage/phase: Booking → Quoting → Submission → Pending Approval → Contract → Construction → Accounts → Closed",
        "description": "the specific status name within that stage",
        "name": "display name of the status",
    },
    "t_status-histories": {
        "objectType": "what the status change is for: 'job', 'allocation', or 'appointment'",
        "objectId": "the ID of the job/allocation/appointment this status change applies to",
        "oldStatus": "previous status name",
        "newStatus": "new status name",
        "oldStatusId": "FK to t_statuses",
        "newStatusId": "FK to t_statuses",
    },
    "t_estimates-snapshot": {
        "estimateType": "'Authorised Works' = construction scope, 'Direct Allocation' = allocation scope",
        "estimateStatus": "'Authorised' or 'Authorised Variation' for approved estimates",
        "totalIncludingTax": "total inc GST — divide by 1.1 for ex-GST SOW value",
        "authorisedTotalExcludingTax": "sum of lines issued to work orders only",
        "isVariation": "whether this is a variation or original scope",
    },
    "t_estimates-snapshot-items": {
        "description": "line item description — search for '%qbcc%', '%prime cost%', '%pc allow%', '%ps allow%'",
        "materialTotal": "total material cost for the line",
        "labourTotal": "total labour cost for the line",
    },
    "t_allocations": {
        "allocationStatusId": "FK to t_allocation-statuses — tracked in status-histories under objectType='allocation'",
        "allocationType": "roof report, assessment report, specialist report, etc.",
        "allocationNumber": "human-readable ID like 'A42121'",
        "siteAttended": "datetime when assessment appointment was booked",
        "completed": "datetime when allocation was marked completed (IS NOT NULL = completed)",
    },
    "t_work-orders": {
        "workOrderType": "'direct allocation' (allocation) or 'authorised works' (construction)",
        "workOrderStatus": "draft → locked → in progress → completed → cancelled",
        "sellTotal": "sell price (scope value) for the work order",
        "costTotal": "cost total (what we pay the subcontractor)",
        "assignedId": "FK to t_contacts — the subcontractor assigned the work order",
    },
    "t_work-orders-items": {
        "ps/pc": "NULL=fixed work, 'PC Allow'=Prime Cost (variable), 'PS Allow'=Provisional Sum (variable)",
        "estimateItemId": "FK to t_estimates-snapshot-items — source authorised estimate line",
    },
    "t_accounts-receivable-invoices": {
        "accountsReceivableInvoiceStatus": "approved, canceled, draft, paid, sent",
        "accountsReceivableType": "make safe, assessment report, specialist report, progress, or final",
        "subtotal": "ex-GST total",
        "total": "inc-GST total",
        "accountNumber": "xero account code — works invoices use 201-240 (excl 212-214)",
        "invoicedTo": "FK to t_contacts — which insurance company",
    },
    "t_accounts-payable-invoices": {
        "accountsPayableInvoiceStatus": "canceled, approved, paid, sent, draft",
        "subTotal": "ex-GST amount",
        "amount": "inc-GST amount",
        "workOrderId": "FK to t_work-orders",
        "accountNumber": "xero account code — works invoices use 301-340 (excl 312-314)",
    },
    "t_reminders": {
        "reminderStatus": "new, completed, cancelled",
        "userId": "FK to t_users — who the reminder is assigned to",
        "title": "type of reminder (e.g. 'QBCC', 'Follow up')",
        "dueDate": "date the reminder needs to be completed by",
        "completedDate": "date the reminder was marked completed",
    },
    "t_notifications": {
        "notificationChannel": "email, note, or sms",
        "notificationType": "Internal, Customer, Customer Contact, Client, Client Contact, Contractor",
    },
    "t_timesheets": {
        "commencedAt": "start datetime — use DATEDIFF with completedAt for duration",
        "completedAt": "end datetime",
    },
    "Clients": {
        "Instructing Client": "insurance company name that referred the claim",
        "Client Group": "umbrella company grouping (IAG, AAI, Hollard, etc.)",
    },
    "Clients-Markup": {
        "MinTier": "min raw cost range for markup tier",
        "Maxtier": "max raw cost range for markup tier",
        "Markup": "markup % for that client group and cost range",
    },
}


# ── Business rules extracted from sample queries ──────────────────────
# These encode domain logic that cannot be derived from column names alone.

BUSINESS_RULES = """
WATERMARK CONSTRUCTION BUSINESS RULES (CRITICAL — use these for correct SQL):

STATUS WORKFLOW (t_statuses.statusType stages in order):
  Booking → Quoting → Submission → Pending Approval → Contract → Construction → Accounts → Closed
  To filter by status: JOIN t_statuses s ON s.id = t_jobs.statusId, then filter on s.statusType or s.name

KEY STATUS NAMES (t_statuses.name — exact strings to use):
  'SUP Validate Endata Scope' — Endata scope validation step (Quoting stage)
  'ATPR VAR Approved' — variation approved by insurer (Contract stage)
  'Excess Required' — excess payment needed from customer (Contract stage)
  'Submitted to Insurer' — claim submitted to insurance company (Pending Approval stage)
  'Approved Job' — insurer approved repairs (Contract stage)
  'Ready To Invoice' — ready for final invoice (Accounts stage)
  'Invoiced' — final invoice issued (Accounts stage)
  'Construction' — construction ready to start
  'Works In Progress' — construction underway
  'Works Complete' — construction finished
  'Customer Satisfied' — customer signed off

SOW (SCOPE OF WORKS) CALCULATION:
  SOW = SUM(ROUND(es.totalIncludingTax / 1.1, 2)) FROM t_estimates-snapshot es
  WHERE es.estimateType = 'Authorised Works' AND es.estimateStatus LIKE '%auth%'
  Always divide totalIncludingTax by 1.1 to get ex-GST value.
  Exclude test jobs: j.jobNumber NOT LIKE '%test%'

VARIABLE COSTS (Prime Cost / Provisional Sum):
  Work order items with [ps/pc] = 'PC Allow' are Prime Cost (variable).
  Work order items with [ps/pc] = 'PS Allow' are Provisional Sum (variable).
  To find variable cost items: WHERE [ps/pc] IN ('PC Allow', 'PS Allow')
  Or search estimate item descriptions: LIKE '%prime cost%' OR LIKE '%pc allow%' OR LIKE '%ps allow%'

ALLOCATION STATUS TRACKING:
  Allocation statuses are in t_allocation-statuses (label column).
  Status history for allocations: t_status-histories WHERE objectType = 'allocation' AND objectId = allocation.id
  Active allocation statuses: NOT IN ('Cancelled', 'Completed', 'Draft')

BAU/CAT CLASSIFICATION:
  BAU (Business As Usual) = catastrophe code IN ('BAU', 'NO-CAT')
  CAT (Catastrophe) = all other codes (except Commercial client group → 'COM')

WORKS AR (Revenue tracking):
  AR invoices for construction works: accountNumber BETWEEN '201' AND '240' AND accountNumber NOT IN ('212','213','214')
  AP invoices for construction works: accountNumber BETWEEN '301' AND '340' AND accountNumber NOT IN ('312','313','314')
  AR Remaining = SOW - SUM(ar.subtotal)

CLIENT / INSURER TERMINOLOGY (CRITICAL — read carefully):
  The [Clients] table maps individual insurance companies to their parent group.
  - [Instructing Client] = the specific insurance company name (e.g., 'Suncorp', 'AAMI', 'GIO')
  - [Client Group] = the parent insurer group (e.g., 'AAI', 'Hollard', 'Allianz')
  WHEN USER SAYS "insurer" or "insurer client group" or "by insurer" → use [Client Group]
  WHEN USER SAYS "instructing client" or "by client" → use [Instructing Client]
  WHEN USER SAYS "client group" → use [Client Group]
  JOIN PATH: t_jobs j → JOIN t_contacts c ON c.id = j.clientId → JOIN [Clients] cl ON cl.[Instructing Client] = c.name
  Then use cl.[Client Group] for grouping by insurer.
  To count "how many insurer clients" or "how many clients" → SELECT COUNT(DISTINCT [Instructing Client]) FROM [Clients]
  To count "how many client groups" → SELECT COUNT(DISTINCT [Client Group]) FROM [Clients]
  To list insurer clients → SELECT DISTINCT [Instructing Client], [Client Group] FROM [Clients] ORDER BY [Client Group]

CLAIM = JOB (CRITICAL):
  In PRIME database context, a "claim" is a "job" in the t_jobs table.
  "how many claims" = COUNT from t_jobs
  "active claims" = active jobs (see status rules below)
  "claims received" = jobs created (use createdAt date)
  "claims won" = jobs NOT closed (statusType != 'Closed')
  "claims lost" / "claims closed" = statusType = 'Closed'

ACTIVE vs CLOSED DEFINITIONS:
  "Active" jobs/claims = t_statuses.statusType IN ('Booking','Quoting','Submission','Pending Approval','Contract','Construction')
  "Closed" jobs/claims = t_statuses.statusType = 'Closed'
  "In Accounts" / "Invoiced" = t_statuses.statusType = 'Accounts'
  IMPORTANT: "active" EXCLUDES both 'Closed' AND 'Accounts' stages.
  When user asks for "active claims by insurer": JOIN t_jobs → t_statuses (filter active) → t_contacts → Clients (group by Client Group)

VULNERABLE CLAIMS:
  Jobs tagged as vulnerable have 'vulnerable' in t_jobs.tags column (comma-separated).
  Filter: t_jobs.tags LIKE '%vulnerable%'
  "customer contact" = t_notifications WHERE notificationType IN ('Customer', 'Customer Contact')
  "no customer contact in X days" = LEFT JOIN t_notifications n ON n.jobId = j.id
    AND n.notificationType IN ('Customer', 'Customer Contact')
    AND n.createdAt >= DATEADD(DAY, -X, GETDATE())
    WHERE n.id IS NULL

MARKUP CALCULATION:
  The [Clients-Markup] table stores markup tiers per client group.
  Columns: [Client Group], [MinTier], [MaxTier], [Markup]
  To find "average markup achieved": compare sell vs cost on work orders or estimates.
  JOIN PATH: t_jobs → t_contacts → Clients → [Clients-Markup] ON [Clients-Markup].[Client Group] = [Clients].[Client Group]

CROSS-DATABASE NOTE:
  IN4MO and PRIME are separate databases. Cross-database JOINs are NOT possible.
  IN4MO ClaimsID links to PRIME t_jobs.[client reference] but only via manual lookup, not SQL JOIN.

ENDATA DATABASE — ACTUAL TABLE STRUCTURE (CRITICAL):
  ENDATA contains: invoices, job_info, claim_form_data, claim_history, job_progress,
    scope, scope_lines, variations, variations_lines, make_safe, site_report,
    s_serviceRequests, t_serviceRequests, documents
  JOIN KEY: All ENDATA tables link via [insurance_ref] — there are NO formal FK constraints.
  Example JOIN: invoices i JOIN job_info j ON j.insurance_ref = i.insurance_ref

  [invoices] table — exact columns:
    client, insurance_ref, type, items, authorised_amount,
    invoice_number, invoice_amount, invoice_status, created_date, updated_date
  invoice_status EXACT values (case-sensitive): 'Recommend', 'Paid', 'Auto paid', 'Unpaid',
    'Rejected', 'Pending RACQ Processing', NULL, '' (empty)
  "Overdue" or "unpaid" invoices = WHERE invoice_status IN ('Unpaid', 'Recommend')
  "Paid" invoices = WHERE invoice_status IN ('Paid', 'Auto paid')

  [t_serviceRequests] — the MAIN ENDATA claims table (1490 records, data from Jan 2024 only):
    claimId, referenceID, scope (insurer e.g. 'Hollard'), requestType ('Quote','Scope','MakeSafe'),
    requestStatus ('Awaiting','Accepted','Removed'), requestDate (datetime2),
    completed (bool), reviewed (bool), authorised (bool), hold (bool),
    makeSafeRequired (bool), toCollectExcess (bool), toProvideSiteReport (bool),
    [name.1] (customer name), phone1, phone2, phone3
  IMPORTANT: job_info, claim_form_data, claim_history, scope, job_progress are ALL EMPTY — never use them.
  For ENDATA "claims" or "service requests": use t_serviceRequests, date = requestDate, insurer = scope

  XERO/INVOICES QUERIES:
  "Xero invoices" or "overdue invoices" → use [invoices] table in ENDATA
  "overdue" = invoice_status IN ('Unpaid', 'Recommend')
  "paid" = invoice_status IN ('Paid', 'Auto paid')
  Example: SELECT TOP 20 client, insurance_ref, type, invoice_number, invoice_amount, invoice_status, created_date
    FROM [invoices] WHERE invoice_status IN ('Unpaid', 'Recommend') ORDER BY created_date DESC

  ENDATA DATA RANGE: Only contains data from January 2024. Queries for 2025/2026 will return 0 rows.
"""


def get_column_description(table_key: str, column_name: str) -> str | None:
    """Return business description for a column, or None."""
    table_descs = COLUMN_DESCRIPTIONS.get(table_key)
    if not table_descs:
        # Try without schema prefix
        short = table_key.split(".", 1)[1] if "." in table_key else table_key
        table_descs = COLUMN_DESCRIPTIONS.get(short)
    if not table_descs:
        return None
    return table_descs.get(column_name)


def annotate_schema_with_descriptions(schema: dict[str, list[str]]) -> dict[str, list[str]]:
    """Add business descriptions to column names in the schema dict."""
    annotated = {}
    for table_key, columns in schema.items():
        new_cols = []
        for col in columns:
            # Strip existing type annotation to get base name
            base_name = col.split(" (")[0]
            desc = get_column_description(table_key, base_name)
            if desc:
                new_cols.append(f"{col} -- {desc}")
            else:
                new_cols.append(col)
        annotated[table_key] = new_cols
    return annotated
