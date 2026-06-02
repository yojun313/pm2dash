import os
from fastapi import Request
from dotenv import load_dotenv

load_dotenv()


class AuthService:
    @staticmethod
    def authenticate(username, password):
        admin_user = os.getenv("ADMIN_USER", "admin")
        admin_pass = os.getenv("ADMIN_PASS", "admin1234")
        return username == admin_user and password == admin_pass

    @staticmethod
    def is_authenticated(request: Request):
        return request.session.get("user") is not None
