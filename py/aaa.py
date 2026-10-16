def rewrite_source(source: str) -> tuple[str, list[str], bool]:
    tree = ast.parse(source)
    offsets = line_offsets(source)
    edits: list[Edit] = []
    imported_executor_names: set[str] = set(EXECUTOR_CLASS_NAMES)
    imported_helper_names: set[str] = set(HELPER_NAMES)
    requires_pool = False
    helpers_to_import: set[str] = set()
    has_direct_concurrent_import = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "concurrent.futures":
            executor_aliases = [
                alias.asname or alias.name for alias in node.names if alias.name in EXECUTOR_CLASS_NAMES
            ]
            helper_aliases = [alias.asname or alias.name for alias in node.names if alias.name in HELPER_NAMES]
            imported_executor_names.update(executor_aliases)
            imported_helper_names.update(helper_aliases)
            requires_pool = requires_pool or bool(executor_aliases)
            helpers_to_import.update(alias.name for alias in node.names if alias.name in HELPER_NAMES)
            replacement_lines: list[str] = []
            if executor_aliases:
                replacement_lines.append("from multiprocessing.pool import Pool")
            if helper_aliases:
                imported = ", ".join(
                    f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                    for alias in node.names
                    if alias.name in HELPER_NAMES
                )
                replacement_lines.append(f"from dh import {imported}")
                start, end = node_span(source, offsets, node)
                add_edit(
                    edits,
                    Edit(
                        start,
                        end,
                        "\n".join(replacement_lines),
                        "replace futures import",
                    ),
                )
        elif isinstance(node, ast.Import):
            concurrent_aliases = [alias for alias in node.names if alias.name == "concurrent.futures"]
            if concurrent_aliases:
                has_direct_concurrent_import = True
                start, end = node_span(source, offsets, node)
                add_edit(
                    edits,
                    Edit(
                        start,
                        end,
                        "from multiprocessing.pool import Pool\nfrom dh import as_completed",
                        "replace futures module import",
                    ),
                )
                requires_pool = True
                helpers_to_import.add("as_completed")
        pool_already_bound = has_top_level_pool_binding(tree)
        if pool_already_bound:
            for edit in list(edits):
                if edit.reason == "replace futures import" and edit.replacement.startswith(
                    "from multiprocessing.pool import Pool\n"
                ):
                    replacement = edit.replacement.replace("from multiprocessing.pool import Pool\n", "", 1)
                    edits.remove(edit)
                    edits.append(Edit(edit.start, edit.end, replacement, edit.reason))
    pool_variables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    func = item.context_expr.func
                    is_executor = (isinstance(func, ast.Name) and func.id in imported_executor_names) or any(
                        is_concurrent_attribute(func, name) for name in EXECUTOR_CLASS_NAMES
                    )
                    if is_executor and isinstance(item.optional_vars, ast.Name):
                        pool_variables.add(item.optional_vars.id)
        elif isinstance(node, ast.AsyncWith):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call) and isinstance(item.optional_vars, ast.Name):
                    func = item.context_expr.func
                    if isinstance(func, ast.Name) and func.id in imported_executor_names:
                        pool_variables.add(item.optional_vars.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_executor_constructor = (isinstance(func, ast.Name) and func.id in imported_executor_names) or any(
            is_concurrent_attribute(func, name) for name in EXECUTOR_CLASS_NAMES
        )
        if is_executor_constructor:
            start, end = node_span(source, offsets, node)
            add_edit(
                edits,
                Edit(start, end, "Pool(processes=MAX_WORKERS)", "fixed pool constructor"),
            )
            requires_pool = True
            continue
        if is_concurrent_attribute(func, "as_completed"):
            start, end = node_span(source, offsets, func)
            add_edit(edits, Edit(start, end, "as_completed", "unqualify completion helper"))
            helpers_to_import.add("as_completed")
            continue
        if not isinstance(func, ast.Attribute):
            continue
        receiver = ast.unparse(func.value)
        if func.attr in {"submit", "map", "shutdown"} and receiver in pool_variables:
            start, end = node_span(source, offsets, node)
            if func.attr == "submit":
                replacement = build_submit_replacement(node)
            elif func.attr == "map":
                replacement = build_map_replacement(node)
            else:
                replacement = f"{receiver}.terminate()"
            if replacement is not None:
                add_edit(edits, Edit(start, end, replacement, f"convert {func.attr}"))
                continue
        if func.attr == "result" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, func)
            add_edit(edits, Edit(start, end, f"{receiver}.get", "AsyncResult get"))
        elif func.attr == "done" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, func)
            add_edit(edits, Edit(start, end, f"{receiver}.ready", "AsyncResult ready"))
        elif func.attr == "cancelled" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, node)
            add_edit(edits, Edit(start, end, "False", "Pool jobs cannot be cancelled"))
        elif func.attr == "cancel" and receiver in FUTURE_RESULT_RECEIVERS:
            start, end = node_span(source, offsets, node)
            add_edit(edits, Edit(start, end, "None", "Pool jobs cannot be cancelled"))
    if requires_pool:
        assignments = top_level_max_workers(tree)
        if assignments:
            for assignment in assignments:
                start, end = node_span(source, offsets, assignment)
                add_edit(edits, Edit(start, end, "MAX_WORKERS = 8", "fix worker constant"))
        else:
            insertion = import_end_index(source, offsets, tree)
            add_edit(
                edits,
                Edit(insertion, insertion, "\nMAX_WORKERS = 8", "insert worker constant"),
            )
    if not edits:
        return source, [], requires_pool
    output = source
    for edit in sorted(edits, key=lambda current: (current.start, current.end), reverse=True):
        output = output[: edit.start] + edit.replacement + output[edit.end :]
    return output, [edit.reason for edit in edits], requires_pool
