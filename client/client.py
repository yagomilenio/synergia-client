import argparse
import requests
import json
import sys
import jwt
import os
import psutil
from worker.worker import subscribe, confirm, test, test_input
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from tabulate import tabulate
from functools import partial
from  worker.docker_util import run_in_docker, start_docker, end_docker, docker_exists
from worker.utils.github_util import GithubUtil
from worker.utils.configuration_interpreter import load_config, cfg
import asyncio
import GPUtil
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import shlex
import hashlib
from client import scheduler
from . import config
from rich.table import Table as RTable
from rich import box as rbox
from rich.panel import Panel
from datetime import  datetime
from rich.console import Console as _C
from worker.utils.logger import section, ok, fail, warn, info, debug, container_started, commit_info, info_inline, THEME


        

BASE_URL = f"{config.REST_BASE_URL}:{config.REST_BASE_PORT}"

VALID_RESOURCES = {'cpu': 1, 'gpu': 2, 'ram': 3}

VALID_METRICS = {
    'min_threads', 'min_freq_mhz',   
    'min_vram_mb', 'min_cuda_cc',    
    'min_ram_mb',                    
}

ASCII_LOGO = r"""
[bold #7B8CDE]     ____                               _       [/]
[bold #7B8CDE]    / ___| _   _ _ __   ___ _ __ __ _  (_) __ _ [/]
[bold #6575C4]    \___ \| | | | '_ \ / _ \ '__/ _` | | |/ _` |[/]
[bold #5464B5]     ___) | |_| | | | |  __/ | | (_| | | | (_| |[/]
[bold #4352A5]    |____/ \__, |_| |_|\___|_|  \__, | |_|\__,_|[/]
[bold #324195]           |___/                |___/           [/]
[dim #555566] ──── Distributed Computing Client · v1.0.0 ────[/]
"""

_console = _C()



def save_session(token, username, email):
    with open(config.SESSION_FILE, "w") as f:
        json.dump({
            "token": token,
            "username": username,
            "email": email
        }, f)


def clear_session(args=None):
    if os.path.exists(config.SESSION_FILE):
        os.remove(config.SESSION_FILE)
    else:
        warn("[ ! ] - No hay ninguna sesión previamente iniciada")


# ---------------- Guardar config ----------------
def save_device_config(cpu_threads=None, gpu_device=None, ram=None):

    data = {}
    if os.path.exists(config.DEVICE_FILE):
        with open(config.DEVICE_FILE, "r") as f:
            data = json.load(f)


    gpus = GPUtil.getGPUs()
    gpu_identifiers = [gpu.id for gpu in gpus]
    total_ram = round(psutil.virtual_memory().total / (1024**2))

    if cpu_threads is not None:
        data["cpu_threads"] = cpu_threads
    else: 
        data["cpu_threads"] = os.cpu_count() or 1
    if gpu_device is not None:
        data["gpu_device"] = gpu_device
    else: 
        data["gpu_device"] = gpu_identifiers[0] if gpus else None
    if ram is not None:
        data["ram"] = ram
    else:
        data["ram"] = f"{total_ram}" #devuelve ram total en MB

    if int(data["cpu_threads"]) > os.cpu_count() or int(data["cpu_threads"]) <= 0 or int(data["gpu_device"]) not in gpu_identifiers or int(data["ram"]) <= 0 or int(data["ram"]) > total_ram:
        fail("Los recursos especificados son inválidos, compruebe la configuración")
        return


    with open(config.DEVICE_FILE, "w") as f:
        json.dump(data, f)


    info(f"Configuración guardada:\n{json.dumps(data, indent=4)}")

    return data  



# ---------- FUNCIONES API ----------

def login_user(args):

    try:

        if not args.username and not args.email:
            fail("Username o email requeridos")
            return 

        payload={
            "username": args.username,
            "email": args.email,
            "passwd": args.passwd
        }
        
        r = requests.post(f"{BASE_URL}/token", json=payload)

        if r.status_code == 200:
            data = r.json()
            token = data.get("token")
            username = data.get("username")
            email = data.get("email")


            if not token:
                fail("Login fallido")
                return None

            save_session(token, username, email)

            info("Login exitoso")
        else:

            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)
            return 

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)



def sign_up_user(args):
    try:


        payload = {
            "username": args.username,
            "passwd": args.passwd,
            "email": args.email
        }

        r = requests.post(f"{BASE_URL}/account", json=payload)

        if r.status_code == 200:
            info("Usuario creado correctamente. Revisa tu email para verificar la cuenta.")
        else:

            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)
            return

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)

def get_account_details(args):

    try:
        if args.username == None: 
            if config.USERNAME == None:
                warn("Usuario no logueado")
                return
            r = requests.get(f"{BASE_URL}/account/{config.USERNAME}") #si no se especifica otro usuario se obtienen datos del user logueado
        else:
            r = requests.get(f"{BASE_URL}/account/{args.username}")

        if r.status_code != 200:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)
            return

        data = r.json()
        account = data["account"]
        transfers = data["transfers"]


        t = RTable.grid(padding=(0, 2))
        t.add_column(style="dim #555566", width=14)
        t.add_column(style="bold #C8C8D4")
        t.add_row("usuario",    account['username'])
        if args.username == None and config.EMAIL != None:
            t.add_row("email",      config.EMAIL)
        t.add_row("creado",     str(account['created_at']))
        t.add_row("reputación", str(account['reputation']))
        t.add_row("balance",    f"[bold #4EC99B]↯ {account['balance']:.2f}[/]")
        _console.print(Panel(t, title="[bold #7B8CDE]cuenta[/]", border_style="#3a3a4a", expand=False, padding=(0,1)))


        if transfers:
            rt = RTable(box=rbox.SIMPLE, show_header=True, header_style="bold #7B8CDE", border_style="#3a3a4a")
            for h in ["ID", "Dir", "Contraparte", "Importe", "Tarea", "Proceso", "Fecha"]:
                rt.add_column(h, style="#C8C8D4")
 
            for t in transfers:
                if t["to_user"] == account["username"] == t["from_user"]:
                    direction, counterparty = "↕", account["username"]
                elif t["to_user"] == account["username"]:
                    direction, counterparty = "[bold #4EC99B]↓ IN[/]", t["from_user"]
                else:
                    direction, counterparty = "[bold #E05555]↑ OUT[/]", t["to_user"]
 
                date_str = t.get("created_at", "")
     
                date_obj = datetime.fromisoformat(date_str)
                date_str = date_obj.strftime("%Y-%m-%d %H:%M")


                amount_color = "#FFFFFF"

                if "IN" in direction:
                    amount_color = "#4EC99B"
                
                if "OUT" in direction:
                    amount_color = "#E05555"

                rt.add_row(
                    str(t["id"]), direction, counterparty,
                    f"[{amount_color}]{t['amount']:.2f}[/]",
                    str(t["task_id"] or "-"), str(t["process_id"] or "-"), date_str
                )
            _console.print(rt)

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)


def _oauth_login(provider: str):

    r = requests.get(f"{BASE_URL}/auth/{provider}")
    if r.status_code != 200:
        fail("Error obteniendo URL de autenticación")
        return
    
    auth_url = r.json()["url"]
    token_result = [None]
    username_result = [None]
    email_result = [None]
    server_ready = threading.Event()
    server_done = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]

            if code and state:

                resp = requests.get(f"{BASE_URL}/auth/{provider}/callback", params={"code": code, "state": state})
                if resp.status_code == 200:
                    data = resp.json()
                    token_result[0] = data.get("token")
                    username_result[0] = data.get("username")
                    email_result[0] = data.get("email")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h2>Login exitoso, puedes cerrar esta ventana.</h2>")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"<h2>Error en el login.</h2>")
            else:
                self.send_response(400)
                self.end_headers()

            server_done.set()

        def log_message(self, format, *args):
            pass


    info(f"Abriendo navegador para autenticación con {provider.capitalize()}...")
    webbrowser.open(auth_url)

    httpd = HTTPServer(("127.0.0.1", 8080), CallbackHandler)
    
    def serve():
        server_ready.set()
        httpd.handle_request()

    t = threading.Thread(target=serve)
    t.daemon = True
    t.start()

    server_ready.wait()
    server_done.wait(timeout=120)
    httpd.server_close()

    if token_result[0]:
        save_session(token_result[0], username_result[0], email_result[0])
        info(f"Login con {provider.capitalize()} exitoso")
    else:
        fail("Login fallido o timeout")


def login_google(args):
    try:
        _oauth_login("google")

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)
    except: 
        fail("Fallo interno del servidor", True)

def login_github(args):
    try:
        _oauth_login("github")
        
    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)
    except: 
        fail("Fallo interno del servidor", True)    

def get_hash_by_github_url(url: str):

    docker_name = "client-task"

    try:

        gu = GithubUtil(url)
        branch = gu.get_branch()

        start_docker(cpu_threads=config.CPU_THREADS, ram_mb=config.RAM, gpu_id=config.GPU_DEVICE, name=docker_name, cache=False)
        
        load_config(url)

        run_in_docker(command=f"git clone {gu.get_repo_link()} /repo", name=docker_name, network=True)

        run_in_docker(command=f"chown -R worker:worker /repo", name=docker_name, root=True)

        if branch is not None:

            run_in_docker(command=f"git config --global --add safe.directory /repo", name=docker_name)
            run_in_docker(command=f"git checkout {branch}", name=docker_name)

        

        packages = cfg().requirements.packages
        cmd_packages = " ".join(packages)
        run_in_docker(command=f"apt update -y && apt install -y {cmd_packages}", root=True, name=docker_name)

        for dl in cfg().download.files:
            run_in_docker(command=f"cd /repo && curl -fsSL '{dl.url}' --output '{dl.dest}'", name=docker_name)
            run_in_docker(command=f"chown worker:worker /repo/{dl.dest}", name=docker_name, root=True)
            if dl.post:
                run_in_docker(command=f"cd /repo && {dl.post}", name=docker_name)



        repo_hash_pre_setup= run_in_docker(
            "python3 /scripts/hash_util.py /repo",
            output=True,
            name=docker_name,
            root=True
        )  

        run_in_docker(command=f"cd /repo && make setup", name=docker_name)
        run_in_docker(command=f"cd /repo && make clean", name=docker_name)

        hash_excludes = cfg().hash.exclude
        exclude_args = " ".join(shlex.quote(e) for e in hash_excludes)

        repo_hash_post_setup= run_in_docker(
            f"python3 /scripts/hash_util.py /repo {exclude_args}",
            output=True,
            name=docker_name,
            root=True
        )

        repo_commit = run_in_docker(
            command="git -C /repo rev-parse HEAD",
            output=True,
            name=docker_name
        ).strip()

        end_docker(docker_name, delete=True)

        repo_hash_pre_setup = repo_hash_pre_setup.strip()
        repo_hash_post_setup = repo_hash_post_setup.strip()

        repo_hash = hashlib.sha256(f"{repo_hash_pre_setup}{repo_hash_post_setup}".encode()).hexdigest()

        debug(f"hash del repositorio: {repo_hash}")

        debug(f"último commit del repositorio: {repo_commit}")

        return repo_hash, repo_commit

    except:
        end_docker(docker_name, delete=True)
        raise 


def parse_requirements(require_list):
    result = {}
    for item in (require_list or []):
        if '=' not in item:
            fail(f"Formato invalido en --require: '{item}' (usa metrica=valor)")
            return None
        key, _, val = item.partition('=')
        key = key.strip()
        if key not in VALID_METRICS:
            fail(f"Metrica desconocida: '{key}'. Validas: {', '.join(sorted(VALID_METRICS))}")
            return None
        try:
            result[key] = float(val)
        except ValueError:
            fail(f"Valor no numerico en --require: '{item}'")
            return None
        if result[key] <= 0:
            fail(f"El valor de '{key}' debe ser mayor que 0")
            return None
    return result


def create_task(args):
    try:

        # Validar resources
        resources = []
        for res in (args.resources or []):
            res_lower = res.lower()
            if res_lower not in VALID_RESOURCES:
                fail(f"Recurso desconocido: '{res}'. Validos: cpu, gpu, ram")
                return
            resources.append(res_lower)

        # Validar requirements
        requirements = parse_requirements(args.require)
        if args.require and requirements is None:
            return

        repo_hash, repo_commit = get_hash_by_github_url(args.github_url)

        params = {
            "name":        args.name,
            "description": "" if args.description is None else args.description,
            "github_url":  args.github_url,
            "repo_hash":   repo_hash,
            "repo_commit": repo_commit,
        }
        if resources:
            params["resources"] = ",".join(resources)
        if requirements:
            params["requirements"] = ",".join(f"{k}={v}" for k, v in requirements.items())

        r = requests.post(
            f"{BASE_URL}/task",
            json=params,
            headers={"token": config.TOKEN}
        )

        if r.status_code == 200:
            task_id = r.json()["task_id"]
            ok(f"Tarea creada con id {task_id}")
            if resources:
                info(f"Recursos: {', '.join(r.upper() for r in resources)}")
            if requirements:


                rt = RTable(box=rbox.SIMPLE, show_header=True, header_style="bold #7B8CDE", border_style="#3a3a4a")
                rt.add_column("Metrica", style="#C8C8D4")
                rt.add_column("Min",     style="bold #4EC99B")
                for metric, value in requirements.items():
                    rt.add_row(metric, str(value))
                _console.print(rt)
        else:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)

    except (RuntimeError, AttributeError):
        fail("Compruebe la dirección del repositorio y la sintaxis del fichero config.toml", True)





def configure_device(args):

    save_device_config(args.cpu_threads, args.gpu_device, args.ram)


def get_my_tasks(args):

    try:

        r = requests.get(
            f"{BASE_URL}/task?token={config.TOKEN}"
        )

        if r.status_code == 200:
            debug(f"Mis tareas: {r.json()["result"]}")
        else:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)


def get_task(task_id: str):
    try:
        r = requests.get(f"{BASE_URL}/task/{task_id}")
        if r.status_code == 200:
            return r.json()
        else:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)
            return None
    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)
        return None

def find_task(args):
    try:
        params = {}
        if getattr(args, "subscribed", False):
            params["subscribed"] = True

        if args.global_search:
            r = requests.get(f"{BASE_URL}/task", params=params)
        else:
            r = requests.get(f"{BASE_URL}/task", headers={"token": config.TOKEN}, params=params)

        if r.status_code != 200:
            try:
                fail(f"Error: {r.json().get('detail')}")
            except:
                fail("Fallo interno del servidor")
            return

        tasks = r.json().get("result", [])

        if not tasks:
            warn("No hay tareas disponibles.")
            return

        if args.name:
            tasks = [t for t in tasks if args.name.lower() in t["name"].lower()]

        if args.status:
            tasks = [t for t in tasks if t.get("status") == args.status]

        if not tasks:
            warn("No se encontraron tareas con ese filtro.")
            return

        rt = RTable(box=rbox.SIMPLE, show_header=True, header_style="bold #7B8CDE", border_style="#3a3a4a")
        for h in ["ID", "Nombre", "Estado", "Descripción", "GitHub"]:
            rt.add_column(h, style="#C8C8D4")

        status_colors = {
            "ACTIVE":    "#4EC99B",
            "PAUSED":    "#E0A455",
            "CANCELLED": "#E05555",
            "COMPLETED": "#7B8CDE",
        }

        for t in tasks:
            s = t.get("status", "—")
            color = status_colors.get(s, "#C8C8D4")
            rt.add_row(
                str(t["task_id"]),
                t["name"] or "-",
                f"[bold {color}]{s}[/]",
                t["description"] or "[dim]-[/]",
                t["github_url"] or "-",
            )
        _console.print(rt)

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.")


def get_outputs(args):

    try:

        url = f"{BASE_URL}/task/{args.task_id}/output"
        params = {}
        if getattr(args, "download", False):
            params["download"] = True
        if getattr(args, "process_id", None):
            params["process_id"] = args.process_id
        if getattr(args, "canonical_only", None):
            params["canonical_only"] = args.canonical_only

        r = requests.get(url, params=params, stream=True)

        if r.status_code != 200:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)
            return


        if getattr(args, "download", False):
            cd = r.headers.get("content-disposition", "")
            filename = cd.split("filename=")[-1].strip('"') if "filename=" in cd else f"task_{args.task_id}_outputs.zip"
            filename = filename.strip('"')
            filename = os.path.join(args.task_id, filename)
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, "wb") as f:
                for chunk in r.iter_content(1024*1024): #1MB por chunk
                    f.write(chunk)
            info(f"Archivo descargado: {filename}")
            return

        outputs = r.json().get("result", [])
        if not outputs:
            warn("No hay outputs para esta tarea.")
            return

        for output in outputs:
            print(f"\n=== Output {output['original_name']} ===")

            meta = {k: v for k, v in output.items() if k != "content"}
            print(json.dumps(meta, indent=2))

            if "content" in output:
                print("\n--- content preview ---")
                print(output["content"])

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)



def subscribe_task(args):

    if not args.yes:

        try:
            gu = GithubUtil(get_task(args.task_id)['github_url'])
            makefile = gu.read_file("Makefile")

        except:
            fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)
            
        print("\n  ADVERTENCIA: Vas a ejecutar código de un repositorio externo.")
        print("El make setup tiene acceso a internet. Revisa el Makefile:\n")
        print("=" * 60)
        print(makefile)
        print("=" * 60)
        
        confirm = input("\n¿Aceptas ejecutar esta tarea? [S/N] ").strip().lower()
        if confirm.lower() != 's':
            print("Abortando.")
            return

    asyncio.run(subscribe(args.task_id, not args.no_cache))



def sync_task(args):
    try:

        task = get_task(args.task_id)

        if not task:
            return

        repo_hash, repo_commit = get_hash_by_github_url(task['github_url'])
        
        r = requests.patch(
            f"{BASE_URL}/task/{args.task_id}",
            json={"repo_hash": repo_hash, "repo_commit": repo_commit},
            headers={"token": config.TOKEN}
        )
        
        if r.status_code == 200:
            info(f"Tarea sincronizada, nuevo hash: {repo_hash}")
        else:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)
    
    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)
    except (RuntimeError, AttributeError):
        fail("Compruebe la dirección del repositorio y la sintaxis del fichero config.toml", True)

def confirm_process(args):

    confirm(args.task_id, args.process_id, not args.no_cache,  terminate=True)

def change_status(args, status):

    try:
        r = requests.patch(
            f"{BASE_URL}/task/{args.task_id}/status",
            params={"status": status},
            headers={"token": config.TOKEN}
        )
        if r.status_code == 200:
            info(f"Estado actualizado de la tarea {args.task_id}: {r.json()["status"]}")
        else:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)

def test_task(args):

    if args.range:
        asyncio.run(test(args.github_url, args.range[0], args.range[1]))
    else:
        asyncio.run(test_input(args.github_url, args.word))

def add_inputs(args):

    try:
        delimiter = args.delimiter or "\n"

        if args.file:
            with open(args.file, "r") as f:
                content = f.read()
        elif args.text:
            content = args.text
        else:
            info("Pulse ctrl+d para finalizar")
            content = sys.stdin.read()

        items = [i.strip() for i in content.split(delimiter) if i.strip()]

        if not items:
            info("No hay items para añadir")
            return

        r = requests.post(
            f"{BASE_URL}/task/{args.task_id}/input",
            json={"items": items},
            headers={"token": config.TOKEN}
        )

        if r.status_code == 200:
            debug(f"Añadidos {r.json()['added']} items")
        else:
            try:
                fail(f"Error: {r.json().get("detail")}")
            except:
                fail("Fallo interno del servidor", True)

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.", True)


def unsubscribe_task(args):
    try:
        r = requests.delete(
            f"{BASE_URL}/task/{args.task_id}/subscription",
            headers={"token": config.TOKEN}
        )
        if r.status_code == 200:
            info(f"Desuscrito de la tarea {args.task_id}")
        else:
            try:
                fail(f"Error: {r.json().get('detail')}")
            except:
                fail("Fallo interno del servidor")
    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.")


def task_info(args):
    try:
        # datos de la tarea
        r = requests.get(f"{BASE_URL}/task/{args.task_id}")
        if r.status_code != 200:
            fail("Tarea no encontrada")
            return
        task = r.json()

        # progreso
        r3 = requests.get(f"{BASE_URL}/task/{args.task_id}/progress")
        progress = r3.json() if r3.status_code == 200 else None

        # procesos
        r2 = requests.get(
            f"{BASE_URL}/task/{args.task_id}/process",
            headers={"token": config.TOKEN}
        )
        processes = r2.json().get("result", []) if r2.status_code == 200 else []



        # panel info tarea
        t = RTable.grid(padding=(0, 2))
        t.add_column(style=f"dim {THEME['muted']}", width=14)
        t.add_column(style=f"bold {THEME['text']}")

        status_color = {"ACTIVE": THEME["success"], "PAUSED": THEME["warning"],
                        "CANCELLED": THEME["error"]}.get(task.get("status"), THEME["text"])

        t.add_row("nombre",      task.get("name", "—"))
        t.add_row("estado",      f"[bold {status_color}]{task.get('status', '—')}[/]")
        t.add_row("github",      f"[dim]{task.get('github_url', '—')}[/]")
        t.add_row("descripción", task.get("description") or "—")

        _console.print(Panel(t, title=f"[bold {THEME['primary']}]tarea #{args.task_id}[/]",
                             border_style=THEME["dim"], expand=False, padding=(0, 1)))

        # barra de progreso solo para tareas estáticas con inputs
        if progress and not progress.get("is_dynamic") and progress.get("total_items", 0) > 0:
            procesados = progress["items_procesados"]
            total = progress["total_items"]
            pct = procesados / total
            bar_filled = int(pct * 20)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            _console.print(
                f"\n  [dim {THEME['muted']}]progreso[/]   "
                f"[{THEME['primary']}]{bar}[/]  "
                f"[bold {THEME['text']}]{procesados:,}[/] / [{THEME['muted']}]{total:,}[/] entradas procesadas\n"
            )

        if not processes:
            info("No hay procesos aún.")
            return

        _console.print(
            f"[bold {THEME['primary']}]Listado de procesos:[/]  "
        )

        # tabla procesos
        pt = RTable(box=rbox.SIMPLE, show_header=True,
                   header_style=f"bold {THEME['primary']}", border_style=THEME["dim"])

        pt.add_column("ID",             style=f"dim {THEME['muted']}", no_wrap=True)
        pt.add_column("rango de entradas",          style=THEME["text"], no_wrap=True)
        pt.add_column("confirmaciones", justify="right", no_wrap=True)

        for p in processes:
            execution_count = p.get("execution_count")

            if execution_count is None or execution_count == 0:
                conf_str = f"[dim {THEME['muted']}]—[/]"
            else:
                confirmaciones = max(0, execution_count - 1)

                if confirmaciones == 0:
                    conf_str = f"[dim {THEME['muted']}]0[/]"
                elif confirmaciones == 1:
                    conf_str = f"[{THEME['warning']}]{confirmaciones}[/]"
                else:
                    conf_str = f"[bold {THEME['success']}]{confirmaciones}[/]"

            pt.add_row(
                str(p.get("id")),
                f"{p.get('input_start_index'):,} - {p.get('input_end_index'):,}",
                conf_str,
            )

        _console.print(pt)

    except requests.exceptions.ConnectionError:
        fail("Error de conexión con el servidor.", True)


def process_info(args):
    try:
        r = requests.get(f"{BASE_URL}/task/{args.task_id}/process/{args.process_id}/executions")
        if r.status_code != 200:
            fail("Proceso no encontrado")
            return

        data = r.json()
        process = data["process"]
        executions = data["executions"]


        # conteo de confirmaciones
        confirmaciones = sum(1 for e in executions if e.get("coincide") and e.get("status") == "SUCCESS")
        canonical_id = process.get("canonical_execution_id")

        t = RTable.grid(padding=(0, 2))
        t.add_column(style=f"dim {THEME['muted']}", width=16)
        t.add_column(style=f"bold {THEME['text']}")

        t.add_row("rango", f"{process['input_start_index']:,} → {process['input_end_index']:,}")
        t.add_row("confirmaciones", str(confirmaciones-1))

        if canonical_id and  confirmaciones > 1:
            resultado = f"[bold {THEME['success']}]✓ verificado[/]  [dim {THEME['muted']}]({confirmaciones} coinciden)[/]"
        else:
            resultado = f"[{THEME['warning']}]pendiente de confirmación[/]"
        t.add_row("estado", resultado)

        _console.print(Panel(
            t,
            title=f"[bold {THEME['primary']}]proceso #{args.process_id} · tarea #{args.task_id}[/]",
            border_style=THEME["dim"], expand=False, padding=(0, 1)
        ))

        if not executions:
            info("No hay ejecuciones aún.")
            return

        # tabla ejecuciones
        et = RTable(box=rbox.SIMPLE, show_header=True,
                   header_style=f"bold {THEME['primary']}", border_style=THEME["dim"])
        et.add_column("ID",        style=f"dim {THEME['muted']}", no_wrap=True)
        et.add_column("worker",    style=THEME["text"], no_wrap=True)
        et.add_column("estado",    no_wrap=True)
        et.add_column("resultado", style=f"dim {THEME['muted']}", no_wrap=True)

        for e in executions:
            is_canonical = e["id"] == canonical_id
            coincide = e.get("coincide")
            status = e.get("status", "—")

            # ID con estrella si es canónica
            id_str = f"[bold {THEME['accent']}]{e['id']} ★[/]" if is_canonical else str(e["id"])

            # estado
            if status == "SUCCESS" and coincide:
                if is_canonical:
                    estado_str = f"[bold {THEME['success']}]✓ canónica[/]"
                else:
                    estado_str = f"[{THEME['success']}]✓ coincide[/]"
            elif status == "SUCCESS" and not coincide:
                estado_str = f"[bold {THEME['error']}]✗ discrepa[/]"
            elif status == "PENDING":
                estado_str = f"[{THEME['warning']}]pendiente[/]"
            else:
                estado_str = f"[dim {THEME['muted']}]{status}[/]"

            # hash truncado como referencia para descarga
            hash_str = (e.get("hash_sha256") or "—")[:12] + "…" if e.get("hash_sha256") else "—"

            et.add_row(id_str, e.get("username", "—"), estado_str, hash_str)

        _console.print(et)
        _console.print(f"\n  [dim {THEME['muted']}]Para descargar un resultado:[/] "
                       f"[{THEME['primary']}]output-task --task-id {args.task_id} --process-id <ID>[/]\n")

    except requests.exceptions.ConnectionError:
        fail("Error de conexión con el servidor.", True)


# ---------- CLI ----------

def main():


    if len(sys.argv) == 1 or (len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help")):
        _console.print(ASCII_LOGO)
    

    parser = argparse.ArgumentParser(
        prog="Synergia",
        description="Plataforma de computación distribuida y gestión de tareas de alto rendimiento.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    subparsers = parser.add_subparsers(
        dest="command", 
        title="Comandos disponibles", 
        metavar="[comando]"
    )

    # ---- sign-up-user ----
    parser_sign = subparsers.add_parser("sign-up-user", help="Crea un usuario en la red Synergia")
    parser_sign.add_argument("--username", required=True)
    parser_sign.add_argument("--email", required=True)
    parser_sign.add_argument("--passwd", required=True)
    parser_sign.set_defaults(func=sign_up_user)


    # ---- login-user ----
    parser_login = subparsers.add_parser("login-user", help="Inicia sesión con credenciales locales")
    parser_login.add_argument("--username", required=False, help="Nombre del usuario")
    parser_login.add_argument("--email", required=False, help="Email del usuario")
    parser_login.add_argument("--passwd", required=True)
    parser_login.set_defaults(func=login_user)

    # Google
    parser_google = subparsers.add_parser("login-google", help="Autenticación segura vía Google OAuth2")
    parser_google.set_defaults(func=login_google)

    # GitHub
    parser_github = subparsers.add_parser("login-github", help="Autenticación segura vía GitHub OAuth2")
    parser_github.set_defaults(func=login_github)


    # ---- logout-user ----
    parser_login = subparsers.add_parser("logout-user", help="Cerrar sesion")
    parser_login.set_defaults(func=clear_session)


    # ---- get-user-details ----
    parser_login = subparsers.add_parser("get-user-details", help="Consulta datos de un usuario")
    parser_login.add_argument("--username", help="Nombre del usuario")
    parser_login.set_defaults(func=get_account_details)

    # ---- configure-device ----
    parser_device = subparsers.add_parser("configure-device", help="Configura los recursos del dispositivo")
    parser_device.add_argument("--cpu-threads")
    parser_device.add_argument("--gpu-device")
    parser_device.add_argument("--ram")
    parser_device.set_defaults(func=configure_device)


# ---- create-task ----
    parser_task = subparsers.add_parser("create-task", help="Crea una nueva tarea")
    parser_task.add_argument("--name",        required=True)
    parser_task.add_argument("--description")
    parser_task.add_argument("--github-url",  required=True)
    parser_task.add_argument(
        "--resources",
        nargs='+',
        metavar="RECURSO",
        help="Recursos que usa la tarea: cpu gpu ram (se pueden combinar)"
    )
    parser_task.add_argument(
        "--require",
        nargs='+',
        metavar="METRICA=VALOR",
        help="Requisitos minimos: min_threads=4 min_ram_mb=512 min_vram_mb=4096 ..."
    )
    parser_task.set_defaults(func=create_task)

    # ---- add-inputs ----
    parser_task = subparsers.add_parser("add-inputs", help="Añade inputs a una tarea")
    parser_task.add_argument("--task-id", required=True)
    parser_task.add_argument("--delimiter")
    group = parser_task.add_mutually_exclusive_group()
    group.add_argument("--file")
    group.add_argument("--text")
    parser_task.set_defaults(func=add_inputs)


    # ---- test-task ----
    parser_task = subparsers.add_parser("test-task", help="Prueba una tarea localmente")
    parser_task.add_argument("--github-url", required=True)
    group = parser_task.add_mutually_exclusive_group(required=True)
    group.add_argument("--word")
    group.add_argument("--range", nargs=2, type=int, metavar=("START", "END"))

    parser_task.set_defaults(func=test_task)
    

    # ---- find-task ----
    parser_task = subparsers.add_parser("find-task", help="Busca tareas disponibles")
    parser_task.add_argument("--global-search", action="store_true")
    parser_task.add_argument("--name")
    parser_task.add_argument("--status", choices=["ACTIVE", "PAUSED", "CANCELLED", "COMPLETED"])
    parser_task.add_argument("--subscribed", action="store_true", help="Mostrar solo tareas suscritas")
    parser_task.set_defaults(func=find_task)

    # ---- subscribe-task ----
    parser_task = subparsers.add_parser("subscribe-task", help="Suscríbe para ejecutar una tarea")
    parser_task.add_argument("--task-id", required=True)
    parser_task.add_argument("--no-cache", action="store_true")
    parser_task.add_argument("--yes", "-y", action="store_true", help="Acepta automáticamente sin confirmación")
    parser_task.set_defaults(func=subscribe_task)


    # ---- unsubscribe-task ----
    parser_unsub = subparsers.add_parser("unsubscribe-task", help="Cancela la suscripción a una tarea")
    parser_unsub.add_argument("--task-id", required=True)
    parser_unsub.set_defaults(func=unsubscribe_task)

    # ---- close-task -----
    parser_close = subparsers.add_parser("close-task", help="Marca una tarea como cerrada")
    parser_close.add_argument("--task-id", required=True)
    parser_close.set_defaults(func=partial(change_status, status='COMPLETED'))

    # ---- task-status ----

    parser_status_cancel = subparsers.add_parser("cancel-task", help="Cancela una tarea")
    parser_status_cancel.add_argument("--task-id", required=True)
    parser_status_cancel.set_defaults(func=partial(change_status, status='CANCELLED'))

    parser_status_pause = subparsers.add_parser("pause-task", help="Pausa una tarea")
    parser_status_pause.add_argument("--task-id", required=True)
    parser_status_pause.set_defaults(func=partial(change_status, status='PAUSED'))

    parser_status_active = subparsers.add_parser("active-task", help="Reactiva una tarea pausada")
    parser_status_active.add_argument("--task-id", required=True)
    parser_status_active.set_defaults(func=partial(change_status, status='ACTIVE'))


    # ---- output-task ----
    parser_task = subparsers.add_parser("output-task", help="Consulta o descarga los outputs de una tarea")
    parser_task.add_argument("--task-id", required=True)
    parser_task.add_argument("--process-id")
    parser_task.add_argument("--canonical-only", action="store_true")
    parser_task.add_argument("--download", action="store_true")
    parser_task.set_defaults(func=get_outputs)

    # ---- confirm-process ----
    parser_task = subparsers.add_parser("confirm-process", help="Confirma un proceso ejecutado")
    parser_task.add_argument("--task-id", required=True)
    parser_task.add_argument("--process-id", required=True)
    parser_task.add_argument("--no-cache", action="store_true")
    parser_task.set_defaults(func=confirm_process)

    # ---- sync-task ----
    parser_sync = subparsers.add_parser("sync-task", help="Actualiza el hash del repositorio de la tarea")
    parser_sync.add_argument("--task-id", required=True)
    parser_sync.set_defaults(func=sync_task)

    # ---- task-info ----
    parser_sync = subparsers.add_parser("task-info", help="Muestra información de una tarea específica")
    parser_sync.add_argument("--task-id", required=True)
    parser_sync.set_defaults(func=task_info)

    # ---- process-info ----
    parser_process = subparsers.add_parser("process-info", help="Detalle de un proceso y sus ejecuciones")
    parser_process.add_argument("--task-id", required=True)
    parser_process.add_argument("--process-id", required=True)
    parser_process.set_defaults(func=process_info)

        # ---- start-scheduler ----
    parser_sched = subparsers.add_parser("start-scheduler", help="Inicia el scheduler para ejecutar las tareas suscritas automáticamente")
    parser_sched.add_argument("--mode", required=True, choices=["round-robin", "split"], 
        help=(
            "round-robin: ejecuta las tareas en turnos, una a la vez. "
            "split: divide los nucleos CPU entre todas las tareas y las ejecuta en paralelo."
        )
    )
    parser_sched.add_argument("--rotation", type=int, default=5, metavar="CHUNKS",
        help="Chunks dedicados a cada tarea antes de rotar (solo round-robin). Por defecto: 5"
    )
    parser_sched.add_argument("--on-idle", action="store_true",
        help="Solo consumirá cpu no utilizada por el resto de procesos del sistema y del usuario"
    )
    parser_sched.set_defaults(func=scheduler.start_scheduler)



    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)


    args.func(args)


if __name__ == "__main__":
    main()
