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

현재 버전은 로컬 음성 명령 분류까지만 구현합니다. ROS2 publisher, Jetson,
TurtleBot, Nav2 및 OpenManipulator 제어는 아직 포함하지 않습니다.
