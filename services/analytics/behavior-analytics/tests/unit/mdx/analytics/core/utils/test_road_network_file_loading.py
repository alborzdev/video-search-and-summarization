# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import osmnx as ox
from networkx import MultiDiGraph

from mdx.analytics.core.schema.config import GraphConfig
from mdx.analytics.core.utils.crs import RoadNetworkGraph


class TestRoadNetworkFileLoading(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_directory.name)

    def tearDown(self):
        self.temp_directory.cleanup()

    @staticmethod
    def file_config(file_path: str, *, osm_type: str = "drive", simplify: bool = False) -> GraphConfig:
        return GraphConfig(
            graphFromOSM=True,
            osmLoadMethod="from_file",
            osmType=osm_type,
            osmSimplify=simplify,
            osmQueryFile=file_path,
        )

    def test_loads_graphml_without_network_access(self):
        graph_path = self.temp_path / "road-network.graphml"
        graph_path.touch()
        expected_graph = MultiDiGraph()

        with patch("mdx.analytics.core.utils.crs.ox.load_graphml", return_value=expected_graph) as load_graphml:
            road_network = RoadNetworkGraph(self.file_config(str(graph_path)))

        self.assertIs(road_network.graph, expected_graph)
        load_graphml.assert_called_once_with(str(graph_path))

    def test_round_trips_an_osmnx_graphml_file_locally(self):
        graph_path = self.temp_path / "road-network.graphml"
        source_graph = MultiDiGraph()
        source_graph.graph["crs"] = "EPSG:4326"
        source_graph.add_node(1, x=-121.946801, y=37.392908)
        source_graph.add_node(2, x=-121.946700, y=37.393000)
        source_graph.add_edge(1, 2, length=12.0, osmid=1)
        ox.save_graphml(source_graph, graph_path)

        road_network = RoadNetworkGraph(self.file_config(str(graph_path)))

        self.assertEqual(set(road_network.graph.nodes), {1, 2})
        self.assertTrue(road_network.graph.has_edge(1, 2))

    def test_loads_osm_xml_with_configured_simplification(self):
        graph_path = self.temp_path / "road-network.osm"
        graph_path.touch()
        expected_graph = MultiDiGraph()

        with (
            patch("mdx.analytics.core.utils.crs.ox.settings.bidirectional_network_types", ["walk"]),
            patch("mdx.analytics.core.utils.crs.ox.graph_from_xml", return_value=expected_graph) as graph_from_xml,
        ):
            road_network = RoadNetworkGraph(self.file_config(str(graph_path), osm_type="walk", simplify=True))

        self.assertIs(road_network.graph, expected_graph)
        graph_from_xml.assert_called_once_with(
            str(graph_path),
            bidirectional=True,
            simplify=True,
            retain_all=False,
        )

    def test_rejects_pbf_with_an_actionable_error(self):
        graph_path = self.temp_path / "road-network.osm.pbf"
        graph_path.touch()

        with self.assertRaisesRegex(ValueError, "Use OSMnx GraphML or OSM XML"):
            RoadNetworkGraph(self.file_config(str(graph_path)))

    def test_rejects_a_missing_local_graph(self):
        graph_path = self.temp_path / "missing.graphml"

        with self.assertRaisesRegex(FileNotFoundError, "Road network file does not exist"):
            RoadNetworkGraph(self.file_config(str(graph_path)))
