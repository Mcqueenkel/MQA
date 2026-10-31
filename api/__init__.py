"""HTTP route groups split out of main.py, mounted via app.include_router().

Each module here is a self-contained FastAPI APIRouter for one domain. Routers that need no shared
app state (static/asset serving, AI-brain endpoints) live here fully decoupled from main.py; the
stateful auth/session/career endpoints stay in main.py where their module-level state lives.
"""
