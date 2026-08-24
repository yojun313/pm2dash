import subprocess
import json
import shutil
import logging


logger = logging.getLogger(__name__)


class PM2Service:
    @staticmethod
    def get_processes():
        pm2_path = shutil.which("pm2")
        if not pm2_path:
            logger.debug("PM2 실행 파일을 찾지 못했습니다.")
            return []
        try:
            result = subprocess.run(
                f"{pm2_path} jlist",
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(result.stdout)
        except Exception as e:
            logger.exception("PM2 프로세스 목록을 불러오지 못했습니다: %s", e)
            return []

    @staticmethod
    def run_command(action: str, name: str, extra_args: list = None):
        pm2_path = shutil.which("pm2")
        if not pm2_path:
            logger.warning("PM2 명령을 실행할 수 없습니다: 실행 파일 없음")
            return False

        args_str = " ".join(extra_args) if extra_args else ""
        command = f"{pm2_path} {action} {name} {args_str}"

        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(
                    "PM2 명령 실패 · command=%s · error=%s",
                    command,
                    result.stderr.strip() or "unknown error",
                )
                return False

            return True
        except Exception as e:
            logger.exception("PM2 명령 실행 중 오류가 발생했습니다: %s", e)
            return False

    @staticmethod
    def save_processes():
        pm2_path = shutil.which("pm2")
        if not pm2_path:
            logger.warning("PM2 프로세스를 저장할 수 없습니다: 실행 파일 없음")
            return False
        try:
            subprocess.run(f"{pm2_path} save", shell=True, check=True)
            logger.info("PM2 프로세스 목록을 저장했습니다.")
            return True
        except (subprocess.SubprocessError, OSError) as error:
            logger.exception("PM2 프로세스 저장에 실패했습니다: %s", error)
            return False

    @staticmethod
    def get_startup_status():
        """PM2가 OS 재부팅 시 자동 실행되도록 설정되어 있는지 확인합니다."""
        pm2_path = shutil.which("pm2")
        if not pm2_path:
            return False
        try:
            result = subprocess.run(
                f"{pm2_path} startup", shell=True, capture_output=True, text=True
            )
            return (
                "already configured" in result.stdout.lower()
                or "sudo" in result.stdout.lower()
            )
        except (subprocess.SubprocessError, OSError) as error:
            logger.debug("PM2 시작 프로그램 상태 확인 실패: %s", error)
            return False
