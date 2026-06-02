import os
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from app.routes import pm2_routes, auth_routes

load_dotenv()

app = FastAPI(title="PM2Dash")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "your-secret-key"),
    max_age=3600 * 24,  # 24시간 유지
)

app.include_router(auth_routes.router)
app.include_router(pm2_routes.router)
