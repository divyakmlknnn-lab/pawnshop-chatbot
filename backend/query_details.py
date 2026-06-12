from query_trace import build_final_query_entry


def _select_final_execution(
    classification,
    executions: list[tuple[str, dict, object]],
) -> tuple[str, dict, object] | None:
    if not executions:
        return None

    primary_tool = (classification.tool or "").split(",")[0].strip()
    candidates = list(reversed(executions))

    if primary_tool:
        for tool_name, tool_args, result in candidates:
            if tool_name != primary_tool:
                continue
            if isinstance(result, dict) and result.get("error"):
                continue
            if build_final_query_entry(tool_name, tool_args, result):
                return tool_name, tool_args, result

    for tool_name, tool_args, result in candidates:
        if isinstance(result, dict) and result.get("error"):
            continue
        if build_final_query_entry(tool_name, tool_args, result):
            return tool_name, tool_args, result

    for tool_name, tool_args, result in candidates:
        if isinstance(result, dict) and result.get("error"):
            continue
        return tool_name, tool_args, result

    return executions[-1]


def build_query_details(classification, executions: list[tuple[str, dict, object]]) -> dict:
    queries: list[dict] = []
    final_execution = _select_final_execution(classification, executions)

    if final_execution:
        tool_name, tool_args, result = final_execution
        entry = build_final_query_entry(tool_name, tool_args, result)
        if entry:
            queries.append(entry)

    return {
        "intent": classification.intent,
        "confidence": classification.confidence,
        "tool": classification.tool,
        "queries": queries,
    }
