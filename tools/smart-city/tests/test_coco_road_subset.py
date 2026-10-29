# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import sys
import unittest
spec=importlib.util.spec_from_file_location('coco_road_subset',Path(__file__).parents[1]/'coco_road_subset.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)


def dataset():
    return {'images':[{'id':i}for i in range(1,40)],'annotations':[
        {'id':c*100+i,'image_id':i,'category_id':c,'area':100,'bbox':[0,0,10,10],'iscrowd':0}
        for c in m.ROAD_CLASSES for i in range(1,40)]}


class SubsetTests(unittest.TestCase):
    def test_selection_is_deterministic_unique_balanced(self):
        ids,anchors=m.select(dataset(),24)
        self.assertEqual((ids,anchors),m.select(dataset(),24))
        self.assertEqual(len(set(ids)),24)
        self.assertEqual({c:list(anchors.values()).count(c)for c in m.ROAD_CLASSES},{c:4 for c in m.ROAD_CLASSES})
    def test_crowds_cannot_supply_positive_anchors(self):
        value=dataset()
        for annotation in value['annotations']:
            if annotation['category_id']==8:annotation['iscrowd']=1
        with self.assertRaisesRegex(ValueError,'non-crowd'):
            m.select(value,24)
    def test_too_few_unique_images_rejected(self):
        with self.assertRaisesRegex(ValueError,'Not enough unique'):
            m.select(dataset(),40)
    def test_coarse_ground_truth_keeps_crowd_flags(self):
        value=dataset();value['annotations'][0]['iscrowd']=1
        coarse=m.coarse_road(value)
        self.assertEqual(coarse['annotations'][0]['iscrowd'],1)
        self.assertEqual({a['category_id']for a in coarse['annotations']},{1,2,3})


if __name__=='__main__':unittest.main()
