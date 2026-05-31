import os
import json
import configparser


SESSION_FILE = os.path.expanduser("~/.cn_profile.json")
DEVICE_FILE = os.path.expanduser("~/.cn_device.json")
CONFIG_DIR = os.path.expanduser("~/.config/synergia")
CONFIG_INI  = os.path.join(CONFIG_DIR, "config.ini")


def load_config():
    config = {}

    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            config.update(json.load(f))

    if os.path.exists(DEVICE_FILE):
        with open(DEVICE_FILE, "r") as f:
            config.update(json.load(f))

    return config

config = load_config()


TOKEN = config.get("token", None)
USERNAME = config.get("username", None)
EMAIL = config.get("email", None)
GPU_DEVICE = config.get("gpu_device", None)
CPU_THREADS = config.get("cpu_threads", None)
RAM = config.get("ram", None)

if not os.path.exists(CONFIG_INI):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    import importlib.resources
    example = importlib.resources.files("client").joinpath("config.ini.example")
    with importlib.resources.as_file(example) as src:
        import shutil
        shutil.copy(src, CONFIG_INI)
    print(f"[!] Configuración creada en {CONFIG_INI} — edítala con las URLs del servidor")

ini_config = configparser.ConfigParser()
ini_config.read(CONFIG_INI)


REST_BASE_URL = ini_config["rest"]["base_url"]
REST_BASE_PORT = ini_config["rest"]["base_port"]

WS_BASE_URL = ini_config["ws"]["base_url"]
WS_BASE_PORT = ini_config["ws"]["base_port"]
