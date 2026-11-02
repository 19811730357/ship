"""Project-owned storage; configure before cache-creating third-party imports."""
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT_DIR / "output"
TEMP_DIR = OUTPUT_DIR / "temp"
LOG_DIR = ROOT_DIR / "logs"
CACHE_DIR = OUTPUT_DIR / "cache"
SOURCE_DIR = OUTPUT_DIR / "sources"


def configure_runtime():
    if os.name == "nt" and ROOT_DIR.drive.upper() != "D:":
        raise RuntimeError("项目运行目录必须位于 D 盘")
    for path in (OUTPUT_DIR, TEMP_DIR, LOG_DIR, CACHE_DIR, SOURCE_DIR):
        path.mkdir(parents=True, exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(TEMP_DIR)
    for key, name in {
        "XDG_CACHE_HOME": "", "MPLCONFIGDIR": "matplotlib",
        "HF_HOME": "huggingface", "TORCH_HOME": "torch",
        "NUMBA_CACHE_DIR": "numba", "STREAMLIT_CACHE_DIR": "streamlit",
    }.items():
        os.environ[key] = str(CACHE_DIR / name)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(TEMP_DIR)
    return ROOT_DIR


def configure_streamlit_storage(file_util=None):
    """Redirect Streamlit's credentials/machine-id helper without changing user home.

    The installed Streamlit uses this helper rather than an environment variable.
    The override is local to this Python process and leaves installed files intact.
    """
    configure_runtime()
    if file_util is None:
        from streamlit import file_util
    directory = CACHE_DIR / "streamlit"
    directory.mkdir(parents=True, exist_ok=True)

    def streamlit_path(*parts):
        candidate = directory.joinpath(*parts).resolve()
        if not candidate.is_relative_to(directory):
            raise ValueError("Streamlit文件路径超出项目缓存目录")
        return str(candidate)

    file_util.get_streamlit_file_path = streamlit_path
    # Streamlit imports this helper by value in its disk cache module.
    cache_module = sys.modules.get("streamlit.runtime.caching.storage.local_disk_cache_storage")
    if cache_module is not None:
        cache_module.get_streamlit_file_path = streamlit_path
    return directory


def launch_streamlit():
    configure_runtime()
    os.chdir(ROOT_DIR)
    configure_streamlit_storage()
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", str(ROOT_DIR / "app.py"),
                "--browser.gatherUsageStats=false", "--server.headless=true"]
    return cli.main()
