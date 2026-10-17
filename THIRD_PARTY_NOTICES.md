# Source and data attribution

## Original tutorial

This project extends [computervisioneng/object-detection-aws-rekognition-tutorial](https://github.com/computervisioneng/object-detection-aws-rekognition-tutorial) by Computer Vision Engineer / computervisiondeveloper. The original code is MIT licensed, copyright 2022 computervisiondeveloper. That notice is retained in LICENSE.

- Video tutorial: https://www.youtube.com/watch?v=C9H_v44670s
- The project owner identified this repository as the tutorial/data reference.
- Engineering additions here include duplicate-label repair, cache/resume, request budgets, output rendering, dataset export, review gating, evaluation tools and automated tests.

## Demo video and derived data

The upstream README points to [this Google Drive data download](https://drive.google.com/file/d/1redK38hzH3_t5r4wD7T3t1Qfq7T97-ed/view?usp=sharing). The local video is named zebras.mp4. The project owner supplied the local video and existing generated outputs, which are packaged in the demo release.

An independent media license and original videographer are not specified in the available project records. The MIT notice above covers the code; it is not a new license grant for third-party footage. Retain this attribution with the demo, and verify original media terms for further redistribution or commercial use.

Frames and previews are derived from the supplied video. Existing bounding boxes are imported automatic suggestions from the earlier tutorial implementation, not human-verified labels. Their confidence values and raw AWS responses were not retained. New pipeline requests save those fields; this publication did not make new AWS recognition requests.

## AWS and dependencies

Amazon Rekognition is an AWS service, not a model trained in this repository. AWS service use is governed by AWS terms and pricing. Boto3, Botocore, OpenCV and NumPy retain their own licenses. No AWS credentials are bundled with the repository or release archive.
