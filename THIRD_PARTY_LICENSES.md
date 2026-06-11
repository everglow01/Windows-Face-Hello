# Third-Party Licenses & Usage Notice

FaceHello's own source code is licensed under the **Apache License 2.0** (see
[`LICENSE`](./LICENSE)). This file documents the third-party components that
FaceHello depends on or bundles, and one important constraint that affects how
the project as a whole — especially the prebuilt installer — may be used.

> This file is informational, not legal advice. If you intend to use FaceHello
> beyond personal / research use, review each component's license yourself.

## ⚠️ Important: bundled face-recognition models are NON-COMMERCIAL

FaceHello's recognition is powered by **InsightFace** models (`buffalo_l`:
`det_10g.onnx` + `w600k_r50.onnx`), which are bundled into the release
installer. InsightFace releases its **code** under the MIT License, but its
**pretrained models, training data, and related assets are made available for
non-commercial research purposes only.**

Because these models are required for FaceHello to function and are shipped in
the installer, **the project as distributed (and its normal use) is limited to
non-commercial, personal, and research use**, regardless of FaceHello's own
Apache-2.0 code license.

To use FaceHello commercially, you would need to replace the InsightFace model
with a face-recognition model you are licensed to use commercially (e.g. one you
train yourself or license from a vendor) and re-calibrate the thresholds.

## Components

| Component | Used for | License | Notes |
|---|---|---|---|
| [InsightFace](https://github.com/deepinsight/insightface) | Face detection + 512-d ArcFace recognition | Code: MIT · **Models (`buffalo_l`): non-commercial research only** | The decisive constraint above. |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) + `face_landmarker.task` | Liveness (EAR blink + head-pose) | Apache-2.0 | Google. |
| [OpenCV](https://github.com/opencv/opencv) (opencv-python) | Camera capture & image ops | Apache-2.0 | OpenCV 4.x. |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | CPU inference of the `.onnx` models | MIT | Microsoft. |
| [NumPy](https://numpy.org/) | Array math | BSD-3-Clause | |
| [PySide6 (Qt for Python)](https://doc.qt.io/qtforpython/) | Console GUI | **LGPL-3.0** | Dynamically linked (imported); you may replace your PySide6/Qt copy with a compatible version. The LGPL text and relinking rights are preserved. Commercial Qt licensing is also available from The Qt Company. |
| [pywin32](https://github.com/mhammond/pywin32) | Windows APIs (services, DPAPI, LSA, named pipes) | PSF (Python Software Foundation License) | |

The portable runtime ships a standalone **CPython** distribution (Python
Software Foundation License). The C++ Credential Provider links only Windows
system libraries.

## Disclaimer

FaceHello modifies Windows services and registers a Credential Provider. It is
provided **"AS IS", without warranty of any kind**, and may carry risk
(including sign-in failure). Single-RGB-camera liveness is far weaker than real
Windows Hello (infrared/depth) and can be defeated by high-quality photos or
video. **Do not use it on machines holding sensitive data.** You assume all risk
and consequences of use. See `LICENSE` sections 7–8 and the Security Notice in
the README.
