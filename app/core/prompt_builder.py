def format_schema_for_prompt(schema: dict[str, list[str]]) -> str:
    lines = []
    for table, columns in schema.items():
        lines.append(f"{table}: {', '.join(columns)}")
    return "\n".join(lines)


def format_fk_for_prompt(fk_list: list[dict]) -> str:
    if not fk_list:
        return "No foreign key relationships found."

    lines = []
    for fk in fk_list:
        lines.append(
            f"[{fk['parent_table']}].[{fk['parent_column']}] -> [{fk['referenced_table']}].[{fk['referenced_column']}]"
        )
    return "\n".join(lines)


def build_prompt(user_query: str, schema_text: str, fk_text: str, database_name: str = "") -> tuple[str, str]:
    selected_database = database_name or "UNSPECIFIED"

    system_content = """
You are a senior data engineer and SQL expert specializing in Azure SQL.

Your job is to convert natural language queries into precise, optimized, and safe T-SQL queries.

STRICT RULES (MUST FOLLOW):
1. ONLY generate SELECT queries (read-only)
2. NEVER use SELECT *
3. ALWAYS explicitly list required columns
4. ALWAYS use TOP 20 unless user specifies otherwise
5. ALWAYS include ORDER BY when query implies sorting (e.g., recent, latest)
6. NEVER hallucinate tables or columns
7. ONLY use tables and columns provided in the schema
8. ALWAYS use correct JOINs based on foreign key relationships
9. NEVER guess relationships; use ONLY defined foreign keys
10. NEVER generate multiple SQL statements
11. NEVER include explanations, comments, or markdown; return ONLY SQL
12. If a column name is a reserved keyword (e.g., start, end, order), ALWAYS wrap it in square brackets []
13. Select ONLY business-relevant columns by default: id, jobId, label, workOrderStatus, sellTotal, createdAt
14. DO NOT include technical/internal columns unless explicitly needed by the user
15. CRITICAL JOIN RULE: If user asks about relationships (for example, jobs with allocations/reminders/work orders), you MUST use JOIN clauses.
16. For relationship requests, use ONLY defined foreign key relationships and DO NOT substitute joins with simple column filtering.

DATABASE CONTEXT:
- PRIME: jobs, work orders, customers, allocations
- ENDATA: insurance, claims, financial data
- IN4MO: inspections and property data

INTENT MAPPING:
- jobs -> t_jobs
- work orders -> t_work-orders
- allocations -> t_allocations
- reminders -> t_reminders

OUTPUT FORMAT:
Return ONLY a valid T-SQL query.
No explanation. No markdown. No extra text.
""".strip()

    combined_schema = schema_text
    if fk_text:
        combined_schema = f"{schema_text}\n\nForeign Key Relationships:\n{fk_text}"

    user_prompt = f"""
Selected database: {selected_database}

Schema context:
{combined_schema}

Generate SQL for this user query:
{user_query}
""".strip()

    return system_content, user_prompt
