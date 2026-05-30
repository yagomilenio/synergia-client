import requests
import sys
import configparser


ini_config = configparser.ConfigParser()
ini_config.read("/scripts/config.ini")

REST_BASE_URL = ini_config["rest"]["base_url"]
REST_BASE_PORT = ini_config["rest"]["base_port"]


BASE_URL = f"{REST_BASE_URL}:{REST_BASE_PORT}"

i=1
stdin_opcion = sys.argv[i]
stdin = True if stdin_opcion == "--stdin" else False
i+=1
token = sys.argv[i]
i+=1
task_id = sys.argv[i]
i+=1
process_id = sys.argv[i]
i+=1
execution_id = sys.argv[i]
i+=1
if not stdin:
    file_path = sys.argv[i]
    i+=1
cpu_cycles = sys.argv[i]
i+=1

ram_avg = sys.argv[i]
i+=1

vram_avg = sys.argv[i] if i < len(sys.argv) else None
i+=1
tdp_w = sys.argv[i] if i < len(sys.argv) else None
i+=1

extra = {}
if vram_avg is not None:
    extra["vram_avg"] = vram_avg
if tdp_w is not None:
    extra["tdp_w"] = tdp_w

if stdin:
    stdin_content = sys.stdin.read() 
    files = {"file": ("stdin_input.txt", stdin_content.encode(), "application/octet-stream")}

    r = requests.post(f"{BASE_URL}/task/{task_id}/process/{process_id}/execution/{execution_id}/result",
        data={"cpu_cycles": cpu_cycles, "ram_avg": ram_avg, **extra},
        files=files,
        headers={"token": token})

else:

    with open(file_path, "rb") as f:
        files = {"file": (file_path, f, "application/octet-stream")}
        r = requests.post(f"{BASE_URL}/task/{task_id}/process/{process_id}/execution/{execution_id}/result",
            data={"cpu_cycles": cpu_cycles, "ram_avg": ram_avg, **extra},
            files=files,
            headers={"token": token})


    

if r.status_code != 200:
    print("Error al subir:", r.text)
    sys.exit(1)