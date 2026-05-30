import os
import json
import configparser


SESSION_FILE = os.path.expanduser("~/.cn_profile.json")
DEVICE_FILE = os.path.expanduser("~/.cn_device.json")



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



ini_config = configparser.ConfigParser()
_dir = os.path.dirname(os.path.abspath(__file__))
ini_config.read(os.path.join(_dir, "..", "worker", "container", "config.ini"))


REST_BASE_URL = ini_config["rest"]["base_url"]
REST_BASE_PORT = ini_config["rest"]["base_port"]

WS_BASE_URL = ini_config["ws"]["base_url"]
WS_BASE_PORT = ini_config["ws"]["base_port"]
