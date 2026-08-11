# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for function-scoped CA-RAG storage initialization."""

from copy import deepcopy

from ca_rag_config import prune_inactive_ca_rag_entries


def _config(active_functions):
    return {
        "context_manager": {"functions": active_functions},
        "functions": {
            "summarization": {
                "tools": {"db": "elasticsearch_db", "llm": "nvidia_llm"}
            },
            "ingestion_function": {
                "tools": {"db": "graph_db", "llm": "nvidia_llm"}
            },
            "custom_function": {"tools": {"db": "custom_storage"}},
        },
        "tools": {
            "vector_db": {"type": "milvus"},
            "elasticsearch_db": {"type": "elasticsearch"},
            "graph_db_arango": {"type": "arango"},
            "graph_db": {"type": "neo4j"},
            "nvidia_llm": {"type": "llm"},
            "nvidia_embedding": {"type": "embedding"},
            "custom_storage": {"type": "custom"},
        },
    }


def test_summarization_keeps_only_elasticsearch_storage_tool():
    config = _config(["summarization"])
    original = deepcopy(config)

    pruned = prune_inactive_ca_rag_entries(config)

    assert config == original
    assert set(pruned["functions"]) == {"summarization"}
    assert set(pruned["tools"]) == {
        "elasticsearch_db",
        "nvidia_llm",
        "nvidia_embedding",
        "custom_storage",
    }


def test_graph_qa_keeps_only_neo4j_storage_tool():
    pruned = prune_inactive_ca_rag_entries(_config(["ingestion_function"]))

    assert set(pruned["functions"]) == {"ingestion_function"}
    assert set(pruned["tools"]) == {
        "graph_db",
        "nvidia_llm",
        "nvidia_embedding",
        "custom_storage",
    }


def test_unknown_storage_and_nonstorage_tools_are_preserved():
    pruned = prune_inactive_ca_rag_entries(_config(["custom_function"]))

    assert set(pruned["functions"]) == {"custom_function"}
    assert set(pruned["tools"]) == {
        "nvidia_llm",
        "nvidia_embedding",
        "custom_storage",
    }


def test_empty_active_function_set_removes_all_known_storage_tools():
    pruned = prune_inactive_ca_rag_entries(_config([]))

    assert pruned["functions"] == {}
    assert set(pruned["tools"]) == {
        "nvidia_llm",
        "nvidia_embedding",
        "custom_storage",
    }


def test_malformed_configuration_is_copied_without_semantic_changes():
    config = {"context_manager": {"functions": "summarization"}, "tools": {"vector_db": {}}}

    pruned = prune_inactive_ca_rag_entries(config)

    assert pruned == config
    assert pruned is not config
