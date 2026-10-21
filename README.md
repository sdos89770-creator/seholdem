# 색근테이블

친구 최대 5명이 방 코드와 초대 링크로 모여 플레이하는 무료 Texas Hold'em 토너먼트 MVP입니다. Python/FastAPI가 게임 상태와 카드 평가를 관리하고, 브라우저는 JavaScript와 WebSocket으로 테이블을 동기화합니다. 실제 돈이나 결제 기능은 없습니다.

## 로컬 실행

Python 3.11 이상이 필요합니다.

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

브라우저에서 `http://localhost:8000`을 엽니다. 같은 네트워크의 친구는 서버를 실행한 컴퓨터의 LAN 주소와 포트 `8000`으로 접속할 수 있습니다. Windows 방화벽에서 Python의 인바운드 연결을 허용해야 할 수 있습니다.

Vite 개발 서버를 사용하려면 Node.js 20 이상이 필요합니다.

```powershell
cd frontend
npm install
npm run dev
```

그 뒤 `http://localhost:5173`을 엽니다. Vite는 API와 WebSocket을 Python 백엔드로 프록시합니다. Node.js가 설치되어 있지 않다면 위의 Python 단독 실행을 사용하면 됩니다.

## 카카오톡 초대

테이블의 `초대 링크 복사`를 눌러 카카오톡 대화방에 붙여넣습니다. 별도의 카카오 SDK/API 키는 필요하지 않습니다. 친구들이 서로 다른 네트워크에서 접속하려면 이 앱을 HTTPS가 가능한 공개 호스트에 배포해야 합니다. 저장소 루트의 `Dockerfile`은 프런트 빌드와 FastAPI 서버를 한 컨테이너로 묶습니다. `docker build -t holdem-friends .`와 `docker run --rm -p 8000:8000 holdem-friends`로 확인할 수 있습니다. 배포 플랫폼에서 컨테이너의 포트 `8000`을 공개하면, 생성된 공개 주소로 초대 링크가 만들어집니다.

한 인스턴스의 메모리에 방을 저장하는 MVP입니다. 서버 재시작 시 방이 사라지므로, 운영 서비스로 확장할 때는 데이터베이스와 다중 인스턴스 동기화를 추가해야 합니다.

## GitHub 배포와 공유 도메인

1. GitHub 저장소의 `main` 브랜치에 프로젝트 파일을 올립니다.
2. Render 대시보드에서 `New` → `Blueprint`를 선택하고 `https://github.com/sdos89770-creator/seholdem`을 연결합니다. 저장소 루트의 `render.yaml` 설정을 검토하고 배포를 시작합니다.
3. 배포가 완료되면 공개 주소 [https://saekgeun-table.onrender.com](https://saekgeun-table.onrender.com)을 친구들에게 공유합니다.
4. 현재처럼 공개 Git 저장소 URL로 연결한 경우 GitHub에 push한 뒤 Render에서 `Manual Deploy` → `Deploy latest commit`을 실행합니다. Render에 GitHub 계정을 연결하면 커밋 자동 배포를 사용할 수 있습니다.
5. 직접 구매한 도메인을 쓰려면 Render 서비스의 `Settings` → `Custom Domains`에 도메인을 등록하고 안내된 DNS 레코드를 도메인 등록 업체에 설정합니다.

Render 무료 서비스는 사용하지 않을 때 잠들 수 있어 첫 접속에 시간이 걸릴 수 있습니다. 방은 단일 서버 인스턴스 메모리에 있으므로 인스턴스를 여러 개로 늘리지 마세요.

## 규칙 및 테스트

- 시작 칩 1,000, 최대 5명, 5 핸드마다 블라인드 2배
- 방장만 시작/다음 핸드 진행 가능
- 개인 홀카드는 본인에게만 전송되고, 쇼다운에서 공개
- 사이드 팟, 체크/콜, 베팅/레이즈, 올인, 폴드 지원
- 기본 단위 테스트: `python -m pytest backend/tests -q`
- 방은 메모리에만 저장되므로 한 서버 프로세스로 실행해야 합니다.
