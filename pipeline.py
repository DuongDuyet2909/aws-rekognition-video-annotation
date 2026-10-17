"""Rekognition annotation pipeline and offline maintenance. Importing makes no AWS calls."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
import zipfile

import cv2


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


def write_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def video_info(video):
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise ValueError(f'Cannot open video: {video}')
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            raise ValueError('Video has no valid FPS.')
        return {'sha256': sha256(video), 'frames': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                'fps': fps, 'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}
    finally:
        cap.release()


def bind_output(output, info):
    path = Path(output) / 'input.json'
    if path.exists() and read_json(path)['sha256'] != info['sha256']:
        raise ValueError('This output belongs to a different video. Choose another --output.')
    write_json(path, info)


def bind_settings(output, config):
    path = Path(output)/'settings.json'
    if path.exists():
        existing = read_json(path)
    else:
        metadata = next((Path(output)/'metadata').glob('frame_*.json'), None)
        existing = read_json(metadata)['settings'] if metadata else config
    if existing != config:
        raise ValueError('Output contains another detection policy. Use a different --output for changed settings.')
    write_json(path, config)


def validate_box(values):
    if len(values) != 4:
        raise ValueError('A box must have four coordinates.')
    x, y, w, h = map(float, values)
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError('Non-finite or empty bounding box.')
    if min(x-w/2, y-h/2) < -1e-6 or max(x+w/2, y+h/2) > 1+1e-6:
        raise ValueError('YOLO box is outside the image.')
    return [x, y, w, h]


def read_yolo(path):
    records, seen, duplicates = [], set(), 0
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            parts = line.split()
            if len(parts) != 5 or parts[0] != '0':
                raise ValueError('Expected class 0 followed by four coordinates.')
            box = validate_box(parts[1:])
        except ValueError as exc:
            raise ValueError(f'{Path(path).name}:{number}: {exc}') from exc
        key = tuple(box)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
            records.append({'class_id': 0, 'bbox': box, 'confidence': None})
    return records, duplicates


def write_yolo(path, records):
    text = ''.join('0 ' + ' '.join(format(v, '.17g') for v in validate_box(row['bbox'])) + '\n'
                   for row in records)
    atomic_text(path, text)


def settings(target='Zebra', region='ap-southeast-2', label_confidence=50.0,
             instance_confidence=0.0, jpeg_quality=95, max_dimension=1280):
    return {'target': target, 'region': region, 'label_confidence': label_confidence,
            'instance_confidence': instance_confidence, 'jpeg_quality': jpeg_quality,
            'max_dimension': max_dimension}


def extract_detections(response, config):
    records, seen = [], set()
    for label in response.get('Labels', []):
        if label.get('Name') != config['target'] or label.get('Confidence', 0) < config['label_confidence']:
            continue
        for instance in label.get('Instances', []):
            confidence = instance.get('Confidence')
            if confidence is None or not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
                continue
            if not 0 <= confidence <= 100 or confidence < config['instance_confidence']:
                continue
            box = instance.get('BoundingBox', {})
            try:
                left, top, width, height = [float(box[key]) for key in ('Left', 'Top', 'Width', 'Height')]
                if not all(math.isfinite(v) for v in (left, top, width, height)) or min(width, height) <= 0:
                    continue
                x1, y1, x2, y2 = max(0.0, left), max(0.0, top), min(1.0, left+width), min(1.0, top+height)
                normalized = validate_box([(x1+x2)/2, (y1+y2)/2, x2-x1, y2-y1])
            except (KeyError, ValueError, TypeError):
                continue
            key = tuple(normalized)
            if key not in seen:
                seen.add(key)
                records.append({'class_id': 0, 'bbox': normalized, 'confidence': float(confidence)})
    return records


def frame_paths(output, index):
    stem = f'frame_{index:04d}'
    output = Path(output)
    return {name: output / folder / (stem + extension) for name, folder, extension in
            [('image', 'images', '.jpg'), ('label', 'annotations', '.txt'),
             ('yolo', 'labels', '.txt'), ('metadata', 'metadata', '.json'),
             ('response', 'responses', '.json')]}


def cache_valid(paths, info, config):
    try:
        metadata = read_json(paths['metadata'])
        valid = (metadata['video_sha256'] == info['sha256'] and metadata['settings'] == config
                 and metadata['annotation_sha256'] == sha256(paths['label'])
                 and metadata['image_sha256'] == sha256(paths['image']))
        if valid:
            read_yolo(paths['label'])
        return valid
    except (OSError, ValueError, KeyError):
        return False


def save_frame(paths, image, records, info, config, index, origin, response=None):
    if image is not None:
        paths['image'].parent.mkdir(parents=True, exist_ok=True)
        temporary = paths['image'].with_suffix('.tmp.jpg')
        if not cv2.imwrite(str(temporary), image, [cv2.IMWRITE_JPEG_QUALITY, config['jpeg_quality']]):
            raise OSError(f'Unable to save frame {index}')
        os.replace(temporary, paths['image'])
    write_yolo(paths['label'], records)
    write_yolo(paths['yolo'], records)
    metadata = {'schema_version': 1, 'frame_index': index, 'video_sha256': info['sha256'],
                'settings': config, 'origin': origin, 'detections': records,
                'raw_response_available': response is not None,
                'label_model_version': response.get('LabelModelVersion') if response else None,
                'annotation_sha256': sha256(paths['label']), 'image_sha256': sha256(paths['image'])}
    write_json(paths['metadata'], metadata)


def repair_legacy(video, output):
    """Back up and deduplicate all legacy labels; preserve unknown confidence as null."""
    output = Path(output)
    info = video_info(video)
    bind_output(output, info)
    bind_settings(output, settings())
    label_files = sorted((output/'annotations').glob('frame_*.txt'))
    if not label_files:
        raise ValueError('No existing annotations to repair.')
    # Validate the full set before modifying any annotation.
    parsed = [(path, *read_yolo(path)) for path in label_files]
    for path, _, _ in parsed:
        if not (output/'images'/(path.stem+'.jpg')).is_file():
            raise ValueError(f'Missing image for {path.name}')
        if not 0 <= int(path.stem.split('_')[1]) < info['frames']:
            raise ValueError('Legacy annotation refers to a frame outside the video.')
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = output/'backups'/f'annotations_before_repair_{timestamp}.zip'
    backup.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path, _, _ in parsed:
            archive.write(path, arcname=path.name)
    total_removed = 0
    for path, records, duplicates in parsed:
        index = int(path.stem.split('_')[1])
        paths = frame_paths(output, index)
        # Preserve newer AWS metadata/confidences when maintenance is repeated.
        if paths['metadata'].exists():
            old = read_json(paths['metadata'])
            if old.get('video_sha256') == info['sha256'] and old.get('origin') == 'aws_rekognition':
                scores = {tuple(r['bbox']): r['confidence'] for r in old['detections']}
                for row in records:
                    row['confidence'] = scores.get(tuple(row['bbox']))
                write_yolo(paths['label'], records)
                write_yolo(paths['yolo'], records)
                old['detections'] = records
                old['annotation_sha256'] = sha256(paths['label'])
                write_json(paths['metadata'], old)
                total_removed += duplicates
                continue
        save_frame(paths, None, records, info, settings(), index, 'legacy_import')
        total_removed += duplicates
    report = {'operation': 'repair', 'frames': len(parsed),
              'duplicates_removed': total_removed, 'boxes': sum(len(r) for _,r,_ in parsed),
              'confidence_note': 'Legacy detections have unknown confidence; no confidence was invented.',
              'backup': str(backup)}
    write_json(output/'repair_report.json', report)
    return report


def make_client(profile, region):
    import boto3
    from botocore.config import Config
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client('rekognition', config=Config(
        connect_timeout=10, read_timeout=30,
        retries={'mode': 'standard', 'total_max_attempts': 3}))


def detect(video, output, config, stride=30, max_api_calls=25, offline=False,
           refresh=False, profile=None, delay=0.25, client_factory=make_client):
    """Resume valid cached frames; save raw responses before other output writes."""
    from botocore.exceptions import BotoCoreError, ClientError
    output = Path(output)
    info = video_info(video)
    bind_output(output, info)
    bind_settings(output, config)
    report = {'operation': 'detect', 'selected_frames': 0, 'cached_frames': 0,
              'recovered_from_response': 0, 'new_api_calls': 0, 'sdk_retries': 0,
              'legacy_frames_used': 0, 'failures': [], 'missing_cache': [],
              'request_budget_reached': False, 'complete': False}
    client = None
    cap = cv2.VideoCapture(str(video))
    index = -1
    previous_call = None
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            index += 1
            if index % stride:
                continue
            report['selected_frames'] += 1
            paths = frame_paths(output, index)
            if not refresh and cache_valid(paths, info, config):
                report['cached_frames'] += 1
                if read_json(paths['metadata'])['origin'] == 'legacy_import':
                    report['legacy_frames_used'] += 1
                if not paths['yolo'].exists():
                    atomic_text(paths['yolo'], paths['label'].read_text(encoding='utf-8'))
                continue
            envelope = None
            if not refresh and paths['response'].exists():
                try:
                    candidate = read_json(paths['response'])
                    if candidate['video_sha256'] == info['sha256'] and candidate['settings'] == config:
                        envelope = candidate
                except (ValueError, KeyError):
                    pass
            if envelope is None and offline:
                report['missing_cache'].append(index)
                continue
            if envelope is None and report['new_api_calls'] >= max_api_calls:
                report['request_budget_reached'] = True
                continue
            ok, image = cap.retrieve()
            if not ok:
                report['failures'].append({'frame': index, 'error': 'VideoDecodeError'})
                continue
            try:
                if envelope is None:
                    if client is None:
                        client = client_factory(profile, config['region'])
                    frame = image
                    height, width = frame.shape[:2]
                    longest = max(height, width)
                    if config['max_dimension'] and longest > config['max_dimension']:
                        scale = config['max_dimension']/longest
                        frame = cv2.resize(frame, (round(width*scale), round(height*scale)), interpolation=cv2.INTER_AREA)
                    encoded, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, config['jpeg_quality']])
                    if not encoded:
                        raise OSError('JPEG encoding failed.')
                    if buffer.nbytes > 5*1024*1024:
                        raise ValueError('JPEG exceeds the 5 MB image-bytes limit; reduce --max-dimension or --jpeg-quality.')
                    if previous_call is not None:
                        time.sleep(max(0, delay - (time.monotonic()-previous_call)))
                    report['new_api_calls'] += 1
                    previous_call = time.monotonic()
                    response = client.detect_labels(Image={'Bytes':buffer.tobytes()},
                                                    MinConfidence=config['label_confidence'])
                    report['sdk_retries'] += response.get('ResponseMetadata', {}).get('RetryAttempts', 0)
                    envelope = {'video_sha256': info['sha256'], 'frame_index': index,
                                'settings': config, 'response': response}
                    write_json(paths['response'], envelope)
                else:
                    report['recovered_from_response'] += 1
                records = extract_detections(envelope['response'], config)
                save_frame(paths, image, records, info, config, index, 'aws_rekognition', envelope['response'])
                print(f'Frame {index}: {len(records)} boxes', flush=True)
            except ClientError as exc:
                code = exc.response.get('Error', {}).get('Code', 'ClientError')
                report['sdk_retries'] += exc.response.get('ResponseMetadata', {}).get('RetryAttempts', 0)
                report['failures'].append({'frame':index, 'error':code})
                print(f'Frame {index}: AWS error {code}', flush=True)
                if code in {'AccessDeniedException','UnrecognizedClientException','InvalidClientTokenId','ExpiredTokenException','InvalidSignatureException'}:
                    break
            except BotoCoreError as exc:
                report['failures'].append({'frame':index, 'error':type(exc).__name__})
                print(f'Frame {index}: {type(exc).__name__}', flush=True)
                break
            except (OSError, ValueError) as exc:
                report['failures'].append({'frame':index,'error':str(exc)})
            finally:
                write_json(output/'run_summary.json', report)
        report['complete'] = not (report['failures'] or report['missing_cache'] or report['request_budget_reached'])
        report['selected_frames_expected'] = math.ceil(info['frames']/stride)
        report['video_frames_read'] = index+1
        if index+1 < info['frames'] or report['selected_frames'] < report['selected_frames_expected']:
            report['complete'] = False
            report['failures'].append({'error':'Video ended before metadata frame count.'})
    finally:
        cap.release()
        write_json(output/'run_summary.json', report)
    return report


def render(video, output):
    """Render at the source FPS; sparse/missing frames are explicitly unanalysed."""
    output = Path(output)
    info = video_info(video)
    bind_output(output, info)
    destination = output/'annotated_video.mp4'
    temporary = output/'annotated_video.tmp.mp4'
    writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*'mp4v'), info['fps'],
                             (info['width'], info['height']))
    cap = cv2.VideoCapture(str(video))
    annotated_dir = output/'annotated_images'
    annotated_dir.mkdir(parents=True, exist_ok=True)
    if not writer.isOpened():
        cap.release()
        raise OSError('Cannot initialize MP4 writer.')
    written = labelled = boxes = 0
    try:
        while True:
            ok, image = cap.read()
            if not ok:
                break
            paths = frame_paths(output, written)
            if paths['label'].exists():
                records, _ = read_yolo(paths['label'])
                for row in records:
                    x,y,w,h = row['bbox']
                    x1,y1 = round((x-w/2)*info['width']),round((y-h/2)*info['height'])
                    x2,y2 = min(info['width']-1,round((x+w/2)*info['width'])),min(info['height']-1,round((y+h/2)*info['height']))
                    cv2.rectangle(image,(max(0,x1),max(0,y1)),(x2,y2),(0,255,90),2)
                cv2.putText(image,f'Frame {written} | Zebra detections: {len(records)}',
                            (12,28),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,255,90),2)
                image_path = annotated_dir/paths['image'].name
                if not cv2.imwrite(str(image_path),image,[cv2.IMWRITE_JPEG_QUALITY,90]):
                    raise OSError(f'Cannot save {image_path.name}')
                if labelled == 0:
                    shutil.copy2(image_path,output/'preview.jpg')
                labelled += 1
                boxes += len(records)
            else:
                cv2.putText(image,f'Frame {written} | Not analysed',(12,28),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,180,255),2)
            writer.write(image)
            written += 1
    finally:
        cap.release()
        writer.release()
    if written != info['frames']:
        raise OSError(f'Video render incomplete: {written}/{info["frames"]} frames')
    os.replace(temporary,destination)
    report={'operation':'render','video_frames':written,'labelled_frames':labelled,
            'boxes_drawn':boxes,'fps':info['fps'],'video':str(destination)}
    write_json(output/'render_report.json',report)
    return report


def export_yolo(output, every=5, validation_fraction=.2, gap=30):
    output=Path(output)
    indices=sorted(int(p.stem.split('_')[1]) for p in (output/'annotations').glob('frame_*.txt')
                   if int(p.stem.split('_')[1]) % every == 0)
    if len(indices)<2:
        raise ValueError('Need at least two sampled frames to export.')
    count=max(1,math.ceil(len(indices)*validation_fraction))
    validation=indices[-count:]
    train=[i for i in indices[:-count] if i < validation[0]-gap]
    if not train:
        raise ValueError('No training frames remain; reduce --gap or --every.')
    for index in train+validation:
        paths=frame_paths(output,index)
        if not paths['image'].is_file():
            raise ValueError(f'Missing image {index}')
        records,_=read_yolo(paths['label'])
        write_yolo(paths['yolo'],records)
    for name, subset in [('train',train),('val',validation)]:
        atomic_text(output/'splits'/f'{name}.txt',''.join(frame_paths(output,i)['image'].resolve().as_posix()+'\n' for i in subset))
    # JSON is valid YAML and avoids an extra dependency.
    write_json(output/'data.yaml',{'path':output.resolve().as_posix(),'train':'splits/train.txt',
                                 'val':'splits/val.txt','names':{'0':'Zebra'}})
    report={'operation':'export-yolo','train':len(train),'validation':len(validation),
            'excluded_gap_frames':len(indices)-len(train)-len(validation),'every':every,'gap':gap,
            'note':'Single-video pseudo-labels, not independent validation; review before training.'}
    write_json(output/'dataset_report.json',report)
    return report


def audit(output):
    output=Path(output)
    images={p.stem for p in (output/'images').glob('frame_*.jpg')}
    annotations={p.stem:p for p in (output/'annotations').glob('frame_*.txt')}
    total=duplicates=unknown=0
    origins=Counter()
    for stem,path in annotations.items():
        rows,extra=read_yolo(path)
        total+=len(rows)
        duplicates+=extra
        metadata=output/'metadata'/(stem+'.json')
        if metadata.exists():
            value=read_json(metadata)
            origins[value['origin']]+=1
            unknown+=sum(row.get('confidence') is None for row in value['detections'])
        else:
            unknown+=len(rows)
    report={'operation':'audit','images':len(images),'annotations':len(annotations),
            'boxes':total,'duplicate_rows':duplicates,'unknown_confidence_boxes':unknown,
            'missing_images':sorted(annotations.keys()-images),'missing_labels':sorted(images-annotations.keys()),
            'metadata_origins':dict(origins),'accuracy':None,
            'accuracy_note':'No human-verified ground truth supplied.'}
    write_json(output/'audit_report.json',report)
    return report
