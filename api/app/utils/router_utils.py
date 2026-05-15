import importlib
import pkgutil
from pathlib import Path

def get_routers():
    import api.app.routers as routers
    routers_path = Path(routers.__path__[0])
    return [name for _, name, _ in pkgutil.iter_modules([str(routers_path)])]

def load_router(router_name: str):
    return importlib.import_module(f"api.app.routers.{router_name}")