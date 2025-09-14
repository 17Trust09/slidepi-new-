import platform
import shutil
import psutil
from datetime import datetime

def get_system_info():
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage(".")
    boot = datetime.fromtimestamp(psutil.boot_time())

    return {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "load_percent": psutil.cpu_percent(interval=0.3),
        },
        "memory": {
            "total_mb": round(vm.total / (1024*1024)),
            "used_mb": round(vm.used / (1024*1024)),
            "percent": vm.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024*1024*1024), 1),
            "used_gb": round(disk.used / (1024*1024*1024), 1),
            "percent": round(disk.used / disk.total * 100, 1) if disk.total else 0,
        },
        "uptime": {
            "since": boot.isoformat(timespec="seconds"),
        }
    }
