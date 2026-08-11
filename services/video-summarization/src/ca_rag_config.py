# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CA-RAG configuration selection helpers for the LVS runtime."""

from copy import deepcopy


# CA-RAG instantiates every declared storage tool, even when none of the active
# context-manager functions reference that tool. The released LVS config
# declares all supported backends so one image can select Milvus,
# Elasticsearch, Neo4j, or ArangoDB. Filter only the known inactive storage
# declarations before constructing or reconfiguring a manager.
STORAGE_TOOL_NAMES = frozenset(
    {"vector_db", "elasticsearch_db", "graph_db_arango", "graph_db"}
)


def prune_inactive_ca_rag_entries(config):
    """Copy *config* and retain only active functions and their storage.

    Unknown and non-storage tools are preserved. Malformed configuration is
    returned unchanged so CA-RAG's authoritative validator reports it rather
    than this compatibility layer silently changing its meaning.
    """

    pruned = deepcopy(config)
    if not isinstance(pruned, dict):
        return pruned

    context_manager = pruned.get("context_manager")
    functions = pruned.get("functions")
    tools = pruned.get("tools")
    if not isinstance(context_manager, dict) or not isinstance(functions, dict):
        return pruned
    if not isinstance(tools, dict):
        return pruned

    active_function_names = context_manager.get("functions")
    if not isinstance(active_function_names, (list, tuple, set)):
        return pruned

    active_storage_tools = set()
    for function_name in active_function_names:
        function_config = functions.get(function_name)
        if not isinstance(function_config, dict):
            continue
        function_tools = function_config.get("tools")
        if not isinstance(function_tools, dict):
            continue
        db_tool = function_tools.get("db")
        if db_tool in STORAGE_TOOL_NAMES:
            active_storage_tools.add(db_tool)

    # ContextManagerConfig validates references in every declared function,
    # even declarations omitted from context_manager.functions. Retaining an
    # inactive summarization declaration after removing Elasticsearch would
    # therefore invalidate an otherwise self-contained Neo4j QA config.
    pruned["functions"] = {
        function_name: functions[function_name]
        for function_name in active_function_names
        if function_name in functions
    }
    for tool_name in STORAGE_TOOL_NAMES - active_storage_tools:
        tools.pop(tool_name, None)
    return pruned
