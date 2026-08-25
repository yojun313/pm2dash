import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.services.auth_service import AuthService
from app.services.git_service import GitService


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class GitActionRequest(BaseModel):
    rebase: bool = False


@router.get("/git")
async def git_manager_page(request: Request):
    if not AuthService.is_authenticated(request):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        request=request,
        name="process.html",
        context={
            "processes": [],
            "active_page": "git",
            "page_title": "Git Manager",
            "page_description": "저장소 상태와 커밋 기록을 확인하고 원격 변경 사항을 동기화합니다.",
        },
    )


@router.get("/api/git/repositories")
async def get_repositories(request: Request):
    if not AuthService.is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"repositories": await asyncio.to_thread(GitService.list_repositories)}


@router.get("/api/git/repositories/{repository_id}")
async def get_repository(request: Request, repository_id: str):
    if not AuthService.is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        return await asyncio.to_thread(GitService.get_repository_detail, repository_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/api/git/repositories/{repository_id}/{action}")
async def run_git_action(
    request: Request,
    repository_id: str,
    action: str,
    payload: GitActionRequest,
):
    if not AuthService.is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if action not in {"fetch", "pull", "push"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 Git 작업입니다.")
    try:
        return await asyncio.to_thread(
            GitService.run_action,
            repository_id,
            action,
            payload.rebase,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
