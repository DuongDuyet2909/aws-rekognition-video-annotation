"""Video-to-YOLO annotation with resumable Rekognition and offline tools."""
import argparse
import json
import os
from pathlib import Path
import sys

from evaluation import evaluate,prepare_review
from pipeline import audit,detect,export_yolo,render,repair_legacy,settings

BASE_DIR=Path(__file__).resolve().parent


def positive(value):
    number=int(value)
    if number<1:
        raise argparse.ArgumentTypeError('Must be positive.')
    return number


def nonnegative(value):
    number=int(value)
    if number<0:
        raise argparse.ArgumentTypeError('Must not be negative.')
    return number


def percent(value):
    number=float(value)
    if not 0<=number<=100:
        raise argparse.ArgumentTypeError('Must be between 0 and 100.')
    return number


def fraction(value):
    number=float(value)
    if not 0<number<1:
        raise argparse.ArgumentTypeError('Must be greater than 0 and below 1.')
    return number


def parser():
    root=argparse.ArgumentParser(description=__doc__)
    commands=root.add_subparsers(dest='command',required=True)
    for name in ['repair','detect','render','audit','export-yolo','prepare-review','evaluate']:
        command=commands.add_parser(name)
        command.add_argument('--output',type=Path,default=BASE_DIR/'output')
        if name in {'repair','detect','render'}:
            command.add_argument('--video',type=Path,default=BASE_DIR/'zebras.mp4')
        if name=='detect':
            command.add_argument('--profile',default=os.environ.get('AWS_PROFILE'))
            command.add_argument('--region',default=os.environ.get('AWS_DEFAULT_REGION','ap-southeast-2'))
            command.add_argument('--target',choices=['Zebra'],default='Zebra')
            command.add_argument('--stride',type=positive,default=30)
            command.add_argument('--max-api-calls',type=nonnegative,default=25)
            command.add_argument('--label-confidence',type=percent,default=50)
            command.add_argument('--instance-confidence',type=percent,default=0,
                                 help='Default 0 preserves legacy behavior; use e.g. 70 for stricter new detections.')
            command.add_argument('--jpeg-quality',type=positive,default=95)
            command.add_argument('--max-dimension',type=nonnegative,default=1280)
            command.add_argument('--offline',action='store_true')
            command.add_argument('--refresh',action='store_true')
        if name in {'export-yolo','prepare-review'}:
            command.add_argument('--every',type=positive,default=5 if name=='export-yolo' else 30)
        if name=='export-yolo':
            command.add_argument('--validation-fraction',type=fraction,default=.2)
            command.add_argument('--gap',type=nonnegative,default=30)
        if name=='prepare-review':
            command.add_argument('--destination',type=Path)
        if name=='evaluate':
            command.add_argument('--ground-truth',type=Path,required=True)
            command.add_argument('--iou',type=fraction,default=.5)
    return root


def main(argv=None):
    cli=parser()
    args=cli.parse_args(argv)
    try:
        if args.command=='repair':
            result=repair_legacy(args.video,args.output)
        elif args.command=='render':
            result=render(args.video,args.output)
        elif args.command=='audit':
            result=audit(args.output)
        elif args.command=='export-yolo':
            result=export_yolo(args.output,args.every,args.validation_fraction,args.gap)
        elif args.command=='prepare-review':
            result=prepare_review(args.output,args.destination or args.output/'review',args.every)
        elif args.command=='evaluate':
            result=evaluate(args.output,args.ground_truth,args.iou)
        else:
            if args.jpeg_quality>100:
                cli.error('--jpeg-quality must be at most 100.')
            if args.offline and args.refresh:
                cli.error('--offline cannot be combined with --refresh.')
            result=detect(args.video,args.output,
                settings(args.target,args.region,args.label_confidence,args.instance_confidence,args.jpeg_quality,args.max_dimension),
                args.stride,args.max_api_calls,args.offline,args.refresh,args.profile)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
        return 2 if args.command=='detect' and not result['complete'] else 0
    except (OSError,ValueError,KeyError) as exc:
        print(f'Error: {exc}',file=sys.stderr,flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
