# Local Voice Robot Command

노트북 마이크로 입력받은 한국어 음성 명령을 로컬 환경에서 처리해,
서비스 로봇이 사용할 수 있는 제한된 JSON 명령으로 변환하는 테스트 프로젝트입니다.

모든 음성 인식과 명령 분류는 로컬에서 실행됩니다.

## 처리 구조

```text
PulseAudio 기본 마이크
        ↓
WebRTC VAD 음성 시작/종료 감지
        ↓
발화 길이만 WAV 녹음 (16 kHz, mono, signed 16-bit PCM)
        ↓
faster-whisper small (CPU, int8)
        ↓
한국어 텍스트
        ↓
Ollama + qwen3:4b-instruct
        ↓
JSON 로봇 명령
```

현재 출력은 다음 세 가지로 제한됩니다.

```json
{"action":"fetch","object":"coke"}
```

```json
{"action":"fetch","object":"tissue"}
```

```json
{"action":"unknown","object":"none"}
```

## 주요 파일

- `voice_command_test.py`: 마이크 녹음, STT, 명령 분류를 연결한 통합 프로그램
- `vad_test.py`: 반복 음성 시작/종료 감지를 확인하는 VAD 단독 테스트
- `llm_test.py`: Ollama를 이용한 명령 분류 및 JSON 검증
- `requirements.txt`: Python 패키지 의존성

## 확인된 환경

- Ubuntu 22.04
- Python 3.10.12
- CPU: Intel Core i7-10510U (4코어/8스레드)
- RAM: 15 GiB
- NVIDIA GPU 없음
- faster-whisper 1.2.1
- Ollama 0.33.3
- Whisper 모델: `small`
- Ollama 모델: `qwen3:4b-instruct`

## 준비 사항

다음 명령이 실행 가능한 상태여야 합니다.

```bash
pactl get-default-source
parec --help
ollama --version
```

Ollama 서버를 실행하고 모델을 준비합니다.

```bash
ollama serve
ollama pull qwen3:4b-instruct
```

이미 Ollama 서비스가 실행 중이라면 `ollama serve`를 중복 실행할 필요가 없습니다.
API는 기본적으로 `http://127.0.0.1:11434`를 사용합니다.

## Python 환경 설치

시스템 Python과 분리된 가상환경 사용을 권장합니다.

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

Whisper `small` 모델은 첫 실행 시 다운로드될 수 있습니다.

## 실행

통합 음성 명령 테스트:

```bash
./.venv/bin/python voice_command_test.py
```

Whisper 모델은 시작할 때 한 번만 로드됩니다. 다음 안내가 표시되면 말합니다.

```text
[LISTENING]
말씀해주세요.
```

프로그램은 음성을 자동 감지하고 발화 종료 후 STT와 LLM을 실행한 다음 다시
`[LISTENING]`으로 돌아갑니다. Ctrl+C로 안전하게 종료할 수 있습니다.

녹음은 `recordings/vad_command_*.wav`에 고유한 이름으로 저장되며 기존 파일을
덮어쓰지 않습니다. 다른 저장 디렉터리는 다음과 같이 지정합니다.

```bash
./.venv/bin/python voice_command_test.py \
  --output-dir recordings
```

VAD만 반복 테스트하려면 다음 명령을 사용합니다. WAV, Whisper, LLM은 실행되지
않습니다.

```bash
./.venv/bin/python vad_test.py
```

LLM 분류만 테스트하려면 다음과 같이 실행합니다.

```bash
./.venv/bin/python llm_test.py "뭐 흘렸는데 닦을 거 가져다줘"
```

## 통합 테스트 결과

| 음성 명령 | STT 결과 예시 | 최종 JSON | 결과 |
|---|---|---|---|
| 목마른데 마실 거 가져다줘 | 목마른 데 마실 거 가져다 줘 | `{"action":"fetch","object":"coke"}` | 성공 |
| 뭐 흘렸는데 닦을 거 가져다줘 | 뭐 흘렸는데 닦을거 가져다줘 | `{"action":"fetch","object":"tissue"}` | 성공 |
| 오늘 날씨 어때 | 오늘 날씨 어때? | `{"action":"unknown","object":"none"}` | 성공 |
| 목마른데 … (0.3초 쉼) … 마실 거 가져다줘 | 목마린데 마실 거 가져다 줘 | `{"action":"fetch","object":"coke"}` | 성공 |

Whisper 전사에 사소한 띄어쓰기 차이가 있어도 최종 명령의 의미가 맞으면 성공으로
판정했습니다.

## VAD 설정

- WebRTC VAD mode: `3`
- PCM frame: `30 ms` (`480 samples`, `960 bytes`)
- Stream warm-up: `1.2초` 입력 폐기
- Start window: 최근 `300 ms` 중 speech `80%` 이상
- Start RMS gate: `200` (LISTENING 상태에만 적용)
- Pre-roll: `450 ms`
- End silence: `900 ms`
- 최대 발화 길이: `15초`

Stream warm-up은 이 장치에서 새 `parec` 연결 직후 관찰된 DC-offset 감쇠 신호가
음성으로 오인되는 것을 막습니다. RMS gate는 음성 시작에만 적용되므로 작은 음절이
발화 중간의 종료 판정에 영향을 주지 않습니다.

WebRTC VAD는 화자 식별기가 아닙니다. 주변 사람이 말하면 정상적인 음성으로
감지하므로 여러 사람이 대화하는 환경에서는 wake word 또는 별도의 화자 인식이
추가로 필요할 수 있습니다.

## 오류 처리

통합 프로그램은 다음 오류를 단계별 메시지로 표시합니다.

- PulseAudio 기본 입력 장치 또는 녹음 실패
- WAV 생성 및 오디오 검사 실패
- Whisper 모델 로드 또는 전사 실패
- Ollama API 연결 실패
- LLM 응답 JSON 형식 또는 허용 값 검증 실패

## 저장소에 포함하지 않는 데이터

다음 데이터는 `.gitignore`로 제외됩니다.

- Python 가상환경과 캐시
- 녹음된 WAV 파일
- 로컬 로그와 임시 파일
- Whisper 및 Ollama 모델 데이터

실제 음성이 담긴 녹음 파일에는 개인정보가 포함될 수 있으므로 공개 저장소에
커밋하지 않는 것을 권장합니다.

## 현재 범위

현재까지 다음 기능을 개별적으로 구현 및 테스트했습니다.

- 로컬 마이크 기반 한국어 음성 명령 인식
- Whisper 기반 STT
- LLM 기반 제한된 JSON 로봇 명령 생성
- YOLO11 기반 `coke`, `tissue`, `airpod`, `vaseline` 객체 검출
- Intel RealSense RGB 영상 기반 실시간 Bounding Box 검출

현재 음성 명령 시스템과 객체 인식 시스템은 각각 독립적으로 검증한 상태입니다.

다음 단계에서는 두 시스템을 ROS2로 연결하여,

```text
음성 명령
    ↓
요청 물체 결정
    ↓
YOLO 객체 탐지
    ↓
RealSense Depth를 이용한 물체 위치 계산
    ↓
TurtleBot3 이동
    ↓
OpenManipulator Pick & Place
```

형태의 서비스 로봇 파이프라인으로 확장할 예정입니다.

## YOLO 기반 객체 인식

음성 명령으로 지정된 물체를 실제 카메라 영상에서 찾기 위해 YOLO11 기반 객체 인식 모델을 학습했습니다.

현재 하나의 모델에서 다음 4개 클래스를 탐지할 수 있습니다.

```text
coke
tissue
airpod
vaseline
```

### 데이터셋 구성

Roboflow에서 Object Detection 데이터셋을 구성하고 YOLO11 형식으로 변환하여 학습에 사용했습니다.

최종 데이터셋은 다음과 같이 구성했습니다.

- Train: 학습 데이터
- Validation: 학습 중 성능 확인
- Test: 최종 성능 평가
- Classes: `coke`, `tissue`, `airpod`, `vaseline`

모델 학습과 최종 평가는 서로 분리된 Validation/Test 데이터셋을 이용했습니다.

### 학습 환경

- Ubuntu 22.04
- NVIDIA GeForce RTX 5060 Ti 8GB
- Python 3.11.16
- PyTorch 2.11.0 + CUDA 12.8
- Ultralytics 8.4.152
- Model: YOLO11n
- Input Size: 640 × 640
- Epochs: 100
- Batch Size: 16

학습 명령:

```bash
yolo detect train \
  model=yolo11n.pt \
  data=$HOME/yolo_ws/datasets/coke_tissue_airpod_vaseline/data.yaml \
  epochs=100 \
  imgsz=640 \
  batch=16 \
  device=0 \
  patience=20 \
  project=$HOME/yolo_ws/runs \
  name=coke_tissue_airpod_vaseline
```

학습 완료 후 가장 성능이 좋았던 weight는 다음 위치에 생성됩니다.

```text
~/yolo_ws/runs/coke_tissue_airpod_vaseline/weights/best.pt
```

### Test 결과

학습에 사용하지 않은 Test 데이터 151장을 이용하여 최종 모델을 평가했습니다.

| Class | Precision | Recall | mAP50 | mAP50-95 |
| --- | ---: | ---: | ---: | ---: |
| All | 0.952 | 0.924 | 0.949 | 0.823 |
| airpod | 0.959 | 1.000 | 0.995 | 0.796 |
| coke | 0.965 | 0.839 | 0.951 | 0.822 |
| tissue | 0.998 | 1.000 | 0.995 | 0.938 |
| vaseline | 0.884 | 0.857 | 0.855 | 0.734 |

전체 Test 데이터 기준 `mAP50 = 0.949`, `mAP50-95 = 0.823`을 확인했습니다.

`tissue`와 `airpod`은 높은 검출 성능을 보였으며, `coke`와 `vaseline`은 일부 환경에서 미검출 또는 클래스 혼동이 발생할 수 있습니다.

### Bounding Box 검출

학습된 `best.pt`를 이용하면 카메라 영상에서 물체의 클래스, confidence score, bounding box를 실시간으로 확인할 수 있습니다.

Intel RealSense RGB 카메라 테스트에서는 다음과 같이 실행했습니다.

```bash
yolo detect predict \
  model=$HOME/yolo_ws/runs/coke_tissue_airpod_vaseline/weights/best.pt \
  source=4 \
  conf=0.25 \
  show=True \
  device=0
```

현재는 다음 형태의 검출 결과를 얻을 수 있습니다.

```text
[coke      confidence + bounding box]
[tissue    confidence + bounding box]
[airpod    confidence + bounding box]
[vaseline  confidence + bounding box]
```

### 현재 확인된 문제

실제 카메라 환경에서 비슷한 형태의 물체 사이에 일부 class confusion이 확인되었습니다.

예를 들어 다음과 같은 경우가 있습니다.

- `airpod`을 `tissue`로 판단
- `vaseline`을 `airpod`으로 판단

추후 실제 로봇 카메라에서 촬영한 실패 사례를 데이터셋에 추가하고 fine-tuning하여 실제 환경에서의 분류 성능을 개선할 예정입니다.

최종적으로는 객체의 Bounding Box뿐만 아니라 RealSense Depth 정보를 이용해 객체의 거리 또는 3차원 위치를 계산하고, TurtleBot3 OpenManipulator의 Pick & Place 동작과 연결하는 것을 목표로 합니다.
