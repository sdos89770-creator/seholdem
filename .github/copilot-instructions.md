# Workspace Instructions

- The backend uses Python and FastAPI. Keep poker rules, turn validation, private cards, and settlement authoritative on the server.
- The frontend uses plain JavaScript, Vite, and CSS. Keep the no-Node Python static-serving path functional.
- Run backend tests with `python -m pytest backend/tests -q` after game or API changes.
- Keep invite links on the same origin as the API and WebSocket. KakaoTalk sharing uses a copy-and-paste URL; do not add Kakao credentials or SDKs.
- There is one in-memory shared room, limited to five players; keep host kick authorization and player tokens server-side.
- Do not imply persistence or real-money play.
