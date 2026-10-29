# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import sys

TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('city_query_policy_test', TOOLS / 'evaluate_query_policy.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def prediction(image, query, category, score):
    return {'image_id': image, 'queryIndex': query, 'category_id': category, 'score': score, 'bbox': [1, 2, 3, 4]}


def test_query_policy_removes_competing_labels_but_never_spatial_overlap():
    values = [prediction(1, 0, 6, .355), prediction(1, 0, 8, .660), prediction(1, 1, 6, .75)]
    result = m.one_city_class_per_query(values)
    assert [(p['queryIndex'], p['category_id']) for p in result] == [(1, 6), (0, 8)]
    assert result[0]['bbox'] == result[1]['bbox']
    assert len(values) == 3  # The reference prediction set remains untouched.


def test_query_identity_is_per_image_and_equal_scores_use_sparse_category_order():
    values = [prediction(1, 0, 8, .5), prediction(2, 0, 6, .9), prediction(1, 0, 6, .5)]
    result = m.one_city_class_per_query(values)
    assert [(p['image_id'], p['category_id']) for p in result] == [(1, 6), (2, 6)]


def test_empty_query_predictions_stay_empty():
    assert m.one_city_class_per_query([]) == []
