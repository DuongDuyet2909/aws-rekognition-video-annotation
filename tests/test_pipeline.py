import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np
from botocore.exceptions import ClientError

from evaluation import evaluate,iou,prepare_review,score_detections
from pipeline import (audit,cache_valid,detect,export_yolo,extract_detections,frame_paths,
                      read_json,read_yolo,render,repair_legacy,settings,video_info,write_json)


def response(confidence=88):
    instance={'Confidence':confidence,'BoundingBox':{'Left':.2,'Top':.2,'Width':.2,'Height':.4}}
    return {'Labels':[{'Name':'Zebra','Confidence':99,'Instances':[instance,instance]},
                      {'Name':'Grass','Confidence':99,'Instances':[]}],
            'LabelModelVersion':'test-model','ResponseMetadata':{'RetryAttempts':0}}


class BoxTests(unittest.TestCase):
    def test_filter_and_deduplicate_api_instances(self):
        rows=extract_detections(response(),settings(instance_confidence=80))
        self.assertEqual(len(rows),1)
        np.testing.assert_allclose(rows[0]['bbox'],[.3,.4,.2,.4])
        self.assertEqual(rows[0]['confidence'],88)
        self.assertEqual(extract_detections(response(79),settings(instance_confidence=80)),[])

    def test_invalid_confidence_rejected(self):
        self.assertEqual(extract_detections(response(float('nan')),settings()),[])

    def test_iou_and_one_to_one_match(self):
        box={'bbox':[.5,.5,.2,.2],'confidence':90}
        self.assertAlmostEqual(iou(box['bbox'],box['bbox']),1)
        scored=score_detections({'frame_0000':[box,box]}, {'frame_0000':[box]})
        self.assertEqual((scored['tp'],scored['fp'],scored['fn']),(1,1,0))
        self.assertEqual(scored['precision'],.5)
        self.assertEqual(scored['recall'],1)

    def test_legacy_confidence_does_not_invent_ap(self):
        box={'bbox':[.5,.5,.2,.2],'confidence':None}
        score=score_detections({'frame_0000':[box]}, {'frame_0000':[box]})
        self.assertEqual(score['f1'],1)
        self.assertIsNone(score['ap_101_point'])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.video=self.root/'sample.mp4'
        self.output=self.root/'output'
        writer=cv2.VideoWriter(str(self.video),cv2.VideoWriter_fourcc(*'mp4v'),10,(64,48))
        self.assertTrue(writer.isOpened())
        for index in range(6):
            writer.write(np.full((48,64,3),index*20,dtype=np.uint8))
        writer.release()

    def tearDown(self):
        self.temp.cleanup()

    def client(self):
        client=Mock()
        client.detect_labels.return_value=response()
        return client

    def test_request_budget_and_resume_without_rebilling(self):
        client=self.client()
        factory=Mock(return_value=client)
        first=detect(self.video,self.output,settings(),stride=1,max_api_calls=2,delay=0,client_factory=factory)
        self.assertEqual(first['new_api_calls'],2)
        self.assertFalse(first['complete'])
        second=detect(self.video,self.output,settings(),stride=1,max_api_calls=4,delay=0,client_factory=factory)
        self.assertEqual(second['cached_frames'],2)
        self.assertEqual(second['new_api_calls'],4)
        self.assertTrue(second['complete'])
        offline_factory=Mock(side_effect=AssertionError('Offline run created AWS client'))
        last=detect(self.video,self.output,settings(),stride=1,offline=True,client_factory=offline_factory)
        self.assertEqual(last['cached_frames'],6)
        self.assertEqual(last['new_api_calls'],0)
        offline_factory.assert_not_called()
        self.assertEqual(audit(self.output)['duplicate_rows'],0)

    def test_raw_response_recovers_interrupted_output(self):
        client=self.client()
        detect(self.video,self.output,settings(),stride=6,max_api_calls=1,delay=0,client_factory=lambda *_:client)
        paths=frame_paths(self.output,0)
        paths['metadata'].unlink()
        paths['label'].unlink()
        forbidden=Mock(side_effect=AssertionError('Unexpected AWS request'))
        recovered=detect(self.video,self.output,settings(),stride=6,offline=True,client_factory=forbidden)
        self.assertEqual(recovered['recovered_from_response'],1)
        self.assertEqual(recovered['new_api_calls'],0)
        forbidden.assert_not_called()

    def test_changed_settings_do_not_reuse_cache(self):
        client=self.client()
        detect(self.video,self.output,settings(),stride=6,max_api_calls=1,delay=0,client_factory=lambda *_:client)
        with self.assertRaisesRegex(ValueError,'different --output'):
            detect(self.video,self.output,settings(instance_confidence=95),stride=6,offline=True)

    def test_auth_error_stops_instead_of_looping_requests(self):
        client=self.client()
        client.detect_labels.side_effect=ClientError({'Error':{'Code':'AccessDeniedException'}},'DetectLabels')
        report=detect(self.video,self.output,settings(),stride=1,max_api_calls=25,delay=0,client_factory=lambda *_:client)
        self.assertEqual(client.detect_labels.call_count,1)
        self.assertFalse(report['complete'])

    def test_legacy_repair_backup_and_render(self):
        cap=cv2.VideoCapture(str(self.video))
        for index in range(6):
            ok,image=cap.read()
            self.assertTrue(ok)
            paths=frame_paths(self.output,index)
            paths['image'].parent.mkdir(parents=True,exist_ok=True)
            paths['label'].parent.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(paths['image']),image)
            paths['label'].write_text('0 .5 .5 .2 .2\n0 .5 .5 .2 .2\n')
        cap.release()
        report=repair_legacy(self.video,self.output)
        self.assertEqual(report['duplicates_removed'],6)
        self.assertTrue(Path(report['backup']).is_file())
        self.assertEqual(audit(self.output)['boxes'],6)
        self.assertEqual(audit(self.output)['unknown_confidence_boxes'],6)
        rendered=render(self.video,self.output)
        info=video_info(Path(rendered['video']))
        self.assertEqual(info['frames'],6)
        self.assertEqual(info['fps'],10)

    def test_export_uses_temporal_gap(self):
        client=self.client()
        detect(self.video,self.output,settings(),stride=1,max_api_calls=6,delay=0,client_factory=lambda *_:client)
        report=export_yolo(self.output,every=1,validation_fraction=.3,gap=1)
        self.assertEqual((report['train'],report['validation'],report['excluded_gap_frames']),(3,2,1))
        self.assertTrue((self.output/'data.yaml').is_file())
        self.assertTrue((self.output/'labels/frame_0000.txt').is_file())

    def test_unreviewed_annotations_cannot_be_ground_truth(self):
        client=self.client()
        detect(self.video,self.output,settings(),stride=1,max_api_calls=6,delay=0,client_factory=lambda *_:client)
        review=self.root/'review'
        prepare_review(self.output,review,every=1)
        with self.assertRaisesRegex(ValueError,'reviewed'):
            evaluate(self.output,review)
        with (review/'review.csv').open(newline='') as stream:
            rows=list(csv.DictReader(stream))
        for row in rows:
            row['status']='reviewed'
            row['reviewer']='synthetic-test-only'
        with (review/'review.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['frame','status','reviewer','notes'])
            writer.writeheader()
            writer.writerows(rows)
        report=evaluate(self.output,review)
        self.assertEqual(report['tp'],6)
        self.assertEqual(report['fp'],0)
        self.assertEqual(report['ap50'],1)
        self.assertEqual(report['map50_95'],1)

    def test_bad_label_rejected_before_repair(self):
        path=self.root/'bad.txt'
        path.write_text('0 .99 .5 .5 .5\n')
        with self.assertRaises(ValueError):
            read_yolo(path)


if __name__=='__main__':
    unittest.main()
