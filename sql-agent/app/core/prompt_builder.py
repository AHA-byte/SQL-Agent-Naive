def format_schema_for_prompt(schema: dict[str, list[str]]) -> str:
    def _display_table(table_key: str) -> str:
        if "." in table_key:
            schema_name, table_name = table_key.split(".", 1)
            return f"[{schema_name}].[{table_name}]"
        return f"[{table_key}]"

    lines = []
    for table, columns in schema.items():
        lines.append(f"{_display_table(table)}: {', '.join(columns)}")
    return "\n".join(lines)


def format_fk_for_prompt(fk_list: list[dict]) -> str:
    if not fk_list:
        return "No foreign key relationships found."

    lines = []
    for fk in fk_list:
        parent_schema = fk.get("parent_schema") or "dbo"
        referenced_schema = fk.get("referenced_schema") or "dbo"
        lines.append(
            f"[{parent_schema}].[{fk['parent_table']}].[{fk['parent_column']}]"
            f" -> [{referenced_schema}].[{fk['referenced_table']}].[{fk['referenced_column']}]"
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
12. ALWAYS wrap schema, table, and column identifiers in square brackets [] (for example, [xero].[AR-invoices], [policy number])
13. Select only business-relevant columns that are explicitly present in the selected table(s)
14. DO NOT include technical/internal columns unless explicitly needed by the user
15. CRITICAL JOIN RULE: If user asks about relationships (for example, jobs with allocations/reminders/work orders), you MUST use JOIN clauses.
16. For relationship requests, use ONLY defined foreign key relationships and DO NOT substitute joins with simple column filtering.
17. Translate natural-language filters into SQL predicates: status/state, customer/company names, type/category flags, and date ranges (for example, since/from/to).
18. For customer/company filters, include the required JOIN path to the customer/contact table when needed.
19. For status-name filters where status is stored by FK, JOIN the relevant status table and filter by status label/type.
20. For type qualifiers (for example, direct allocation work orders), add explicit WHERE predicates on the corresponding type/status columns.
21. The FK format is: [parent_schema].[parent_table].[parent_column] -> [ref_schema].[ref_table].[ref_column].
22. Always use [schema].[table] in FROM and JOIN clauses.

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
