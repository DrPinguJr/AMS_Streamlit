from __future__ import annotations

import re


BLOCKED_KEYWORDS = {
    "ALTER", "BACKUP", "CREATE", "DBCC", "DELETE", "DENY", "DROP", "EXEC",
    "EXECUTE", "GRANT", "INSERT", "KILL", "MERGE", "RESTORE", "REVOKE",
    "TRUNCATE", "UPDATE", "USE",
}


class UnsafeQueryError(ValueError):
    pass


def _mask_literals_and_comments(sql: str) -> str:
    result: list[str] = []
    index = 0
    state = "normal"
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "normal":
            if char == "'":
                state = "string"
                result.append(" ")
            elif char == "-" and next_char == "-":
                state = "line_comment"
                result.extend("  ")
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                result.extend("  ")
                index += 1
            else:
                result.append(char)
        elif state == "string":
            result.append(" ")
            if char == "'" and next_char == "'":
                result.append(" ")
                index += 1
            elif char == "'":
                state = "normal"
        elif state == "line_comment":
            result.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "normal"
        else:
            result.append(" ")
            if char == "*" and next_char == "/":
                result.append(" ")
                index += 1
                state = "normal"
        index += 1
    return "".join(result)


def validate_read_only_sql(sql: str) -> str:
    query = sql.strip()
    if not query:
        raise UnsafeQueryError("Enter a SQL query first.")
    masked = _mask_literals_and_comments(query)
    statements = [part for part in masked.split(";") if part.strip()]
    if len(statements) != 1:
        raise UnsafeQueryError("Query blocked: only one read-only SQL statement is allowed.")
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", masked.upper())
    if not tokens or tokens[0] not in {"SELECT", "WITH"} or "SELECT" not in tokens:
        raise UnsafeQueryError("Query blocked: only read-only SQL is allowed.")
    blocked = sorted(BLOCKED_KEYWORDS.intersection(tokens))
    if blocked or re.search(r"\bSELECT\s+.*?\bINTO\b", masked, flags=re.IGNORECASE | re.DOTALL):
        raise UnsafeQueryError("Query blocked: only read-only SQL is allowed.")
    try:
        from sqlglot import exp, parse
        from sqlglot.errors import ParseError

        try:
            expressions = parse(query, read="tsql")
        except ParseError:
            expressions = []  # SSRS expressions can exceed sqlglot's T-SQL grammar.
        if expressions:
            if len(expressions) != 1 or not next(expressions[0].find_all(exp.Select), None):
                raise UnsafeQueryError("Query blocked: only read-only SQL is allowed.")
            mutation_types = tuple(
                kind for kind in (
                    getattr(exp, "Alter", None), getattr(exp, "Create", None),
                    getattr(exp, "Delete", None), getattr(exp, "Drop", None),
                    getattr(exp, "Execute", None), getattr(exp, "Insert", None),
                    getattr(exp, "Into", None), getattr(exp, "Merge", None),
                    getattr(exp, "Update", None),
                )
                if kind is not None
            )
            if mutation_types and any(isinstance(node, mutation_types) for node in expressions[0].walk()):
                raise UnsafeQueryError("Query blocked: only read-only SQL is allowed.")
    except ImportError:
        pass
    return query.rstrip(";").rstrip()


def detect_parameters(sql: str) -> list[str]:
    masked = _mask_literals_and_comments(sql)
    names = re.findall(r"(?<!@)@([A-Za-z_][A-Za-z0-9_]*)", masked)
    return list(dict.fromkeys(names))


def bind_parameters(sql: str, names: list[str]) -> str:
    allowed = set(names)
    result: list[str] = []
    index = 0
    state = "normal"
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "normal" and char == "'":
            state = "string"
        elif state == "normal" and char == "-" and next_char == "-":
            state = "line_comment"
        elif state == "normal" and char == "/" and next_char == "*":
            state = "block_comment"
        elif state == "normal" and char == "@" and next_char != "@":
            match = re.match(r"@([A-Za-z_][A-Za-z0-9_]*)", sql[index:])
            if match and match.group(1) in allowed:
                result.append(f":{match.group(1)}")
                index += len(match.group(0))
                continue
        elif state == "string" and char == "'":
            if next_char == "'":
                result.extend((char, next_char))
                index += 2
                continue
            state = "normal"
        elif state == "line_comment" and char == "\n":
            state = "normal"
        elif state == "block_comment" and char == "*" and next_char == "/":
            result.extend((char, next_char))
            index += 2
            state = "normal"
            continue
        result.append(char)
        index += 1
    return "".join(result)
