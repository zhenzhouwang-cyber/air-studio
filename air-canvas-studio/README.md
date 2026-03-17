# AIR Canvas Studio (Standalone)

Independent parallel project for interactive creation:
- Infinite canvas (pan/zoom/drag/basic nodes)
- Right-side command panel with instruction + reference image upload
- AI pipeline: optimize prompt -> generate image -> push image onto canvas

## 1) Backend

```bash
cd air-canvas-studio
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
copy .env.example .env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8020 --env-file .env
```

## 2) Frontend

```bash
cd air-canvas-studio
npm install
npm run dev
```

Frontend default: `http://127.0.0.1:5180`
Backend default: `http://127.0.0.1:8020`
