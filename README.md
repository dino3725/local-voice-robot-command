# Local Voice Robot Command

노트북 마이크로 입력받은 한국어 음성 명령을 로컬 환경에서 처리해,
서비스 로봇이 사용할 수 있는 제한된 JSON 명령으로 변환하는 테스트 프로젝트입니다.

모든 음성 인식과 명령 분류는 로컬에서 실행됩니다.

## 처리 구조

```text
PulseAudio 기본 마이크
        ↓
10초 WAV 녹음 (16 kHz, mono, signed 16-bit PCM)
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
./.venv/bin/python voice_command_test.py \
  --output recordings/command.wav
```

프로그램에 다음 안내가 표시되면 바로 말합니다.

```text
[REC]
지금부터 10초간 녹음합니다.
지금 말씀해주세요.
```

기존 녹음 파일은 자동으로 덮어쓰지 않습니다. 반복 테스트에서는 새로운 파일명을
지정하세요.

```bash
./.venv/bin/python voice_command_test.py \
  --output recordings/command-02.wav \
  --expected-object tissue
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

Whisper 전사에 사소한 띄어쓰기 차이가 있어도 최종 명령의 의미가 맞으면 성공으로
판정했습니다.

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
