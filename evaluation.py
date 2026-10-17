"""Human review workflow and single-class object-detection evaluation."""
import csv
import io
import math
from pathlib import Path
import shutil

from pipeline import atomic_text, read_json, read_yolo, write_json, write_yolo


def prepare_review(output, destination, every=30):
    output, destination=Path(output),Path(destination)
    manifest=destination/'review.csv'
    if manifest.exists():
        raise ValueError('Review set already exists. Choose another --destination to preserve edits.')
    selected=[p for p in sorted((output/'annotations').glob('frame_*.txt'))
              if int(p.stem.split('_')[1]) % every == 0]
    if not selected:
        raise ValueError('No annotations to review.')
    rows=[]
    (destination/'images').mkdir(parents=True,exist_ok=True)
    for path in selected:
        records,_=read_yolo(path)
        image=output/'images'/(path.stem+'.jpg')
        if not image.is_file():
            raise ValueError(f'Missing image: {image.name}')
        shutil.copy2(image,destination/'images'/image.name)
        write_yolo(destination/'labels'/path.name,records)
        rows.append({'frame':path.stem,'status':'pending','reviewer':'','notes':''})
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=['frame','status','reviewer','notes'])
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(manifest,stream.getvalue())
    atomic_text(destination/'README.md',
        '# Human review required\n\n'
        'labels/ contains automatically generated suggestions, NOT verified ground truth.\n'
        'Open images and labels in a YOLO-compatible annotation tool. Correct missed, false and misplaced boxes.\n'
        'Only then mark that frame status=reviewed in review.csv and provide reviewer.\n'
        'Keep reviewed labels separate from the prediction output. Do not mark uninspected frames reviewed.\n'
        'Evaluation refuses pending frames and reports this sampled subset only.\n')
    return {'operation':'prepare-review','frames':len(rows),'status':'pending','directory':str(destination)}


def iou(box_a,box_b):
    def corners(box):
        x,y,w,h=box
        return x-w/2,y-h/2,x+w/2,y+h/2
    a,b=corners(box_a),corners(box_b)
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=box_a[2]*box_a[3]+box_b[2]*box_b[3]-intersection
    return intersection/union if union>0 else 0.0


def score_detections(predictions,truth,threshold=.5):
    """One-to-one matches, ordered by confidence when every score is available."""
    ranked=[]
    confidence_available=all(p.get('confidence') is not None for rows in predictions.values() for p in rows)
    for stem,rows in predictions.items():
        ranked.extend((stem,row) for row in rows)
    if confidence_available:
        ranked.sort(key=lambda item:item[1]['confidence'],reverse=True)
    else:
        # Confidence-free legacy labels have no meaningful AP ranking.
        ranked.sort(key=lambda item:item[0])
    matched={stem:set() for stem in truth}
    flags=[]
    matched_ious=[]
    for stem,row in ranked:
        candidates=[(iou(row['bbox'],gt['bbox']),index) for index,gt in enumerate(truth[stem])
                    if index not in matched[stem]]
        overlap,index=max(candidates,default=(0,-1))
        success=index>=0 and overlap>=threshold
        flags.append(int(success))
        if success:
            matched[stem].add(index)
            matched_ious.append(overlap)
    positives=sum(len(rows) for rows in truth.values())
    tp=sum(flags)
    fp=len(flags)-tp
    fn=positives-tp
    precision=tp/(tp+fp) if tp+fp else None
    recall=tp/positives if positives else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    ap=None
    if confidence_available and positives:
        running_tp=0
        curve=[]
        for index,flag in enumerate(flags,1):
            running_tp+=flag
            curve.append((running_tp/positives,running_tp/index))
        ap=sum(max((p for r,p in curve if r>=point/100),default=0.0) for point in range(101))/101
    return {'tp':tp,'fp':fp,'fn':fn,'precision':precision,'recall':recall,'f1':f1,
            'mean_matched_iou':sum(matched_ious)/len(matched_ious) if matched_ious else None,
            'ap_101_point':ap,'confidence_available':confidence_available}


def evaluate(output,ground_truth,threshold=.5):
    output,ground_truth=Path(output).resolve(),Path(ground_truth).resolve()
    if ground_truth == output or output/'annotations' == ground_truth or output/'labels' == ground_truth:
        raise ValueError('Ground truth must be a separate human-reviewed directory.')
    manifest=ground_truth/'review.csv'
    if not manifest.is_file():
        raise ValueError('Missing review.csv. Run prepare-review and complete human review first.')
    with manifest.open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    if not rows or any(r.get('status')!='reviewed' or not r.get('reviewer','').strip() for r in rows):
        raise ValueError('Every frame needs status=reviewed and a reviewer; automatic suggestions are not ground truth.')
    stems=[r['frame'] for r in rows]
    if len(set(stems)) != len(stems) or any(not s.startswith('frame_') or not s[6:].isdigit() for s in stems):
        raise ValueError('Invalid or duplicate frame identifiers in review.csv.')
    predictions,truth={},{}
    for stem in stems:
        truth[stem],duplicates=read_yolo(ground_truth/'labels'/(stem+'.txt'))
        if duplicates:
            raise ValueError(f'Ground truth still has duplicate boxes: {stem}')
        prediction_path=output/'annotations'/(stem+'.txt')
        if not prediction_path.is_file():
            raise ValueError(f'Missing predictions for reviewed frame: {stem}')
        predictions[stem],_=read_yolo(prediction_path)
        metadata=output/'metadata'/(stem+'.json')
        if metadata.exists():
            value=read_json(metadata)
            known={tuple(r['bbox']):r.get('confidence') for r in value['detections']}
            for detection in predictions[stem]:
                detection['confidence']=known.get(tuple(detection['bbox']))
    result=score_detections(predictions,truth,threshold)
    result.update({'operation':'evaluate','frames':len(stems),'iou_threshold':threshold,
                   'scope':'Human-reviewed subset only; not proof of independent test performance.',
                   'matching':'Single class; one-to-one greedy matching; 101-point interpolated AP when scores exist.'})
    if result['confidence_available'] and sum(len(v) for v in truth.values()):
        result['ap50']=score_detections(predictions,truth,.5)['ap_101_point']
        result['map50_95']=sum(score_detections(predictions,truth,.5+i*.05)['ap_101_point'] for i in range(10))/10
    else:
        result['ap50']=result['map50_95']=None
        result['ap_note']='Legacy outputs have no confidence scores; AP/mAP cannot be reconstructed.'
    write_json(output/'evaluation_report.json',result)
    return result
