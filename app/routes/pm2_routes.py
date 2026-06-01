import asyncio
from fastapi import (
    APIRouter,
    Request,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import psutil
from app.services.pm2_service import PM2Service
from app.services.auth_service import AuthService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def pm2_manager_page(request: Request):
    if not AuthService.is_authenticated(request):
        return RedirectResponse(url="/login")

    processes = PM2Service.get_processes()
    return templates.TemplateResponse(
        request=request,
        name="process.html",
        context={"processes": processes, "active_page": "pm2"},
    )


@router.post("/control/{action}/{name}")
async def control_process(request: Request, action: str, name: str):
    if not AuthService.is_authenticated(request):
        return RedirectResponse(url="/login")

    if action not in ["restart", "stop", "start", "delete"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    success = PM2Service.run_command(action, name)
    if not success:
        raise HTTPException(status_code=500, detail="Command failed")

    return {"status": "success"}


@router.get("/status")
async def get_pm2_status_api(request: Request):
    if not AuthService.is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return PM2Service.get_processes()


@router.get("/server-stats")
async def get_server_stats(request: Request):
    if not AuthService.is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    du = psutil.disk_usage("/")
    net = psutil.net_io_counters()

    return {
        "cpu_percent": psutil.cpu_percent(),
        "cpu_cores": psutil.cpu_percent(percpu=True),
        "cpu_count_logical": psutil.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "memory_total": vm.total,
        "memory_available": vm.available,
        "memory_used": vm.used,
        "memory_percent": vm.percent,
        "swap_total": sw.total,
        "swap_used": sw.used,
        "swap_percent": sw.percent,
        "disk_total": du.total,
        "disk_used": du.used,
        "disk_free": du.free,
        "disk_percent": du.percent,
        "net_bytes_sent": net.bytes_sent,
        "net_bytes_recv": net.bytes_recv,
    }


@router.websocket("/ws/logs/{name}")
async def websocket_endpoint(websocket: WebSocket, name: str):
    if not websocket.session.get("user"):
        await websocket.accept()
        await websocket.send_text("Error: Unauthorized access.")
        await websocket.close(code=1008)
        return

    await websocket.accept()

    process = await asyncio.create_subprocess_exec(
        "pm2",
        "logs",
        name,
        "--lines",
        "50",
        "--raw",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break

            await websocket.send_text(line.decode().strip())

    except WebSocketDisconnect:
        if process.returncode is None:
            process.terminate()
    except Exception as e:
        print(f"Log Streaming Error for {name}: {e}")
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


@router.post("/toggle-watch/{name}")
async def toggle_watch(request: Request, name: str):
    if not AuthService.is_authenticated(request):
        return RedirectResponse(url="/login")

    processes = PM2Service.get_processes()
    target_proc = next((p for p in processes if p["name"] == name), None)

    if not target_proc:
        raise HTTPException(status_code=404, detail="Process not found")

    current_watch = target_proc.get("pm2_env", {}).get("watch", False)

    new_flag = ["--watch", "false"] if current_watch else ["--watch"]

    new_flag.append("--update-env")

    success = PM2Service.run_command("restart", name, new_flag)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to toggle watch mode")

    return {"status": "success", "watch": not current_watch}


@router.get("/startup-status")
async def get_startup_status():
    status = PM2Service.get_startup_status()
    return {"is_registered": status}


@router.post("/save")
async def save_pm2_list():
    success = PM2Service.save_processes()
    if not success:
        raise HTTPException(status_code=500, detail="Save failed")
    return {"status": "success"}
