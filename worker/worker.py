import asyncio
import websockets
import json
from . docker_util import run_in_docker, start_docker, end_docker, docker_exists
import requests
import signal
import time
from client import config
from . utils.configuration_interpreter import load_config, cfg
from . utils.github_util import GithubUtil
import asyncio
import jwt
import os
import hashlib
import shlex
import re
from . utils.logger import section, ok, fail, warn, info, debug, container_started, commit_info


BASE_URL = f"{config.REST_BASE_URL}:{config.REST_BASE_PORT}" # hay que ponerlo en un fichero de configuracion 


UPLOAD_INTERVAL = 60 # minimo un minuto 
INACTIVE_STATUSES = {'paused', 'cancelled', 'stopped', 'completed'}


async def subscribe(task_id: str, cache: bool,  rotation=None, handle_signals=True):

    docker_name = get_container_name(task_id)

    if not config.TOKEN:
        fail("No has iniciado sesión. Usa 'login-user' primero.")
        return

    cfg, repo_hash, repo_commit = init_environment(task_id, cache)

    task = get_task(task_id)

    if not task:
        fail("Tarea no encontrada")
        return

    org_hash=task['repo_snapshot_hash']

    if repo_hash != org_hash and cache:
        warn("Hash del repositorio no coincide, reiniciando sin caché...")
        cfg, repo_hash, repo_commit = init_environment(task_id, cache=False)

    
    if cfg.inputs is None:
        await subscribe_without_input(task_id, docker_name, cache, repo_hash, repo_commit, cfg, rotation, handle_signals)

    else:
        await subscribe_with_input(task_id, docker_name, cache, repo_hash, repo_commit, cfg, rotation, handle_signals)






async def subscribe_with_input(task_id: str, docker_name: str, cache: bool, repo_hash: str, repo_commit: str, cfg, rotation, handle_signals=True):

    requested_chunks = 1

    uri = f"{config.WS_BASE_URL}:{config.WS_BASE_PORT}/ws/task/{task_id}?token={config.TOKEN}&n_consumes={requested_chunks}"

    stop_flag = asyncio.Event()

    if handle_signals:

        def handle_sigint():
            warn("\nCtrl+C detectado, cerrando conexión...")
            stop_flag.set()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, handle_sigint)
        loop.add_signal_handler(signal.SIGTERM, handle_sigint)



    input_type = cfg.inputs.type
    output_mode = cfg.outputs.mode
    filename_pattern = cfg.outputs.filename_pattern

    if input_type == "file_single":
        path = cfg.inputs.file_single.path
        index_file = cfg.inputs.file_single.index_file
        index_len = cfg.inputs.file_single.index_len
        delimiter = cfg.inputs.file_single.delimiter
        delimiter_escaped = delimiter.encode("unicode_escape").decode("ascii")


    try:
        async with websockets.connect(uri) as ws:
            ok(f"Conectado a tarea {task_id}")

            errors=0
            
            while not stop_flag.is_set() and (rotation is None or rotation > 0):

                if rotation is not None:
                    rotation -= 1

                try:
                    await ws.send(json.dumps({"action": "next", "n": requested_chunks}))
                    message = await ws.recv()
                except websockets.ConnectionClosedOK:
                    info("Servidor cerró la conexión limpiamente")
                    break
                except websockets.ConnectionClosedError:
                    fail("Conexión cerrada inesperadamente")
                    break

                data = json.loads(message)


                if isinstance(data, dict) and data.get("status") == "empty":
                    info("Cola vacía, esperando...")
                    await asyncio.sleep(5)
                    continue

                if isinstance(data, dict) and data.get("status") == "verification_required":
                    info("Realizando confirmacion...")
                    process_id = getConfirmationProcessId(task_id)

                    if process_id == None:
                        await asyncio.sleep(5)
                    else:
                        await asyncio.to_thread(confirm, task_id, process_id, cache, cfg, repo_hash, repo_commit)
                    await ws.send(json.dumps({"action": "confirmation_done"}))
                    section("RUN")
                    continue


                

                if isinstance(data, dict) and data.get("status") in INACTIVE_STATUSES:  
                    warn(f"Tarea en estado {data.get('status')}, no se puede procesar")
                    stop_flag.set()
                    return
                


                if not any('value' in item for item in data):
                    data = merge_consecutive_ranges(data)   #quitamos dividimos en los menores bloques posibles


                preprocesar=time.time()
                debug(f"lo que se va a procesar: {data}")
                
                for item in data:
                    start = item['index']
                    val = item.get('value')
                    if val is not None:
                        value = val
                        count = 1 
                        end = start
                        is_dynamic = True
                    else:
                        value=None
                        count =  item.get('count')
                        end = start + count - 1
                        is_dynamic = False
                    

                    continuar = await asyncio.to_thread(get_continue_information, task_id)
                    if not continuar:
                        warn(f"Deteniendo ejecucion, la tarea no está activa")
                        stop_flag.set()
                        break


                    result = await asyncio.to_thread(create_process, task_id, repo_hash, repo_commit, start, count, value)
                    
                    if result is None:
                        warn("No se puede crear el proceso, ya existe")

                        errors+=1
                        if errors > 3:
                            fail("Demasiados errores, deteniendo worker")
                            stop_flag.set()
                            break 

                        continue
                    else:
                        errors=0

                    process_id, execution_id = result

                    
                    if is_dynamic:

                        cmd = f"cd /repo && make run WORD={shlex.quote(value)}"
                        
                    else:
                        if input_type == "file_single":

                            if index_file != None and index_len != None:


                                raw_index = await asyncio.to_thread(
                                    run_in_docker,
                                    command=f"dd if=/repo/{index_file} bs={index_len} skip={start} count={count} 2>/dev/null",
                                    output=True, name=docker_name
                                )

                                entries = []
                                for line in raw_index.strip().splitlines():
                                    parts = line.split()
                                    entries.append((int(parts[0]), int(parts[1])))  # (offset, length)

                                byte_skip  = entries[0][0]
                                last_off, last_len = entries[-1]
                                byte_count = (last_off + last_len) - byte_skip

                                stdout= await asyncio.to_thread(
                                    run_in_docker,
                                    f"dd if=/repo/{path} bs=1 skip={byte_skip} count={byte_count} 2>/dev/null",
                                    output=True, name=docker_name
                                )



                            else:

                                stdout = await asyncio.to_thread(run_in_docker, command=f"awk 'BEGIN{{RS=\"{delimiter_escaped}\"}} NR>={start} && NR<={end}' /repo/{path}", output=True, name=docker_name)

                            words = stdout.strip().split(delimiter)

                            cmd = f"cd /repo && make run WORDS={shlex.quote(' '.join(words))}"
                        else:
                            cmd = f"cd /repo && make run START={start} END={end}"


                    #limpiar fichero de salida
                    await asyncio.to_thread(run_in_docker, command=f"cd /repo && make clean", name=docker_name)

                    result = await asyncio.to_thread(run_in_docker, command=cmd, stats=True, name=docker_name, output=True, gpu=config.GPU_DEVICE)
                    if config.GPU_DEVICE is not None:
                        stdout, cpu_cycles, cpu_time, ram_avg, vram_avg, tdp_w = result

                    else:
                        stdout, cpu_cycles, cpu_time, ram_avg = result

                    if stop_flag.is_set():
                        debug("Cancelado durante ejecución, no se suben resultados")
                        break
                    debug(f"CPU_CYCLES: {cpu_cycles} CPUT_TIME: {cpu_time} RAM_AVG {ram_avg}")

                    postprocesar=time.time()
                    debug(f"tiempo de procesamiento: {postprocesar-preprocesar}")
                    elapsed = postprocesar - preprocesar
                    if elapsed > 0:
                        requested_chunks = UPLOAD_INTERVAL * requested_chunks / elapsed

                    if(requested_chunks<1): 
                        requested_chunks=1

                    if str(output_mode) == "file":
                        output_file = filename_pattern.format(start=start, end=end)
                        OUTPUT = os.path.join(cfg.outputs.dir, output_file)

                        await asyncio.to_thread(run_in_docker, command=f"mkdir -p {cfg.outputs.dir} && touch {OUTPUT}", name=docker_name)

                        await asyncio.to_thread(run_in_docker, command=f"tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -cf - {OUTPUT} | gzip -n > {OUTPUT}.tar.gz", name=docker_name)

                        cmd=f"python3 /scripts/upload_results.py --no-stdin {config.TOKEN} {task_id} {process_id} {execution_id} {OUTPUT}.tar.gz {cpu_cycles} {ram_avg}"

                        
                    else:

                        cmd = f"python3 /scripts/upload_results.py --stdin {config.TOKEN} {task_id} {process_id} {execution_id} {cpu_cycles} {ram_avg}"

                    if config.GPU_DEVICE is not None:
                        cmd += f" {vram_avg} {tdp_w}"

                    stdout_lines = stdout.split('\n', 1)    #quitar commando de llamada
                    stdout_clean = stdout_lines[1] if len(stdout_lines) > 1 else stdout

                    await asyncio.to_thread(
                        run_in_docker, command=sanitize_command(cmd), name=docker_name, stdin=stdout_clean, root=True
                    )





    except websockets.exceptions.InvalidStatus as e:
        if "HTTP 403" in str(e): 
            fail("Acceso denegado. Revisa el token o permisos.")
        else:
            fail("Error en la comunicación con los servidores, reintentelo mas tarde.")
    except (ConnectionRefusedError, OSError):
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.")
    finally:
        info("Terminando entorno aislado...")
        end_docker(docker_name)


async def subscribe_without_input(task_id: str, docker_name: str, cache: bool, repo_hash: str, repo_commit: str, cfg, rotation, handle_signals=True):

    stop_flag = asyncio.Event()

    if handle_signals:
        def handle_sigint():
            nonlocal stop_flag
            info("\nCtrl+C detectado, cerrando conexión...")
            stop_flag.set()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, handle_sigint)
        loop.add_signal_handler(signal.SIGTERM, handle_sigint)

    output_mode = cfg.outputs.mode
    filename_pattern = cfg.outputs.filename_pattern


    while not stop_flag.is_set() and (rotation is None or rotation > 0) :

        if rotation is not None:
            rotation -= 1

        continuar = get_continue_information(task_id)
        if not continuar:
            fail(f"Deteniendo ejecucion, la tarea no está activa")
            stop_flag.set()
            break

        result = create_process(task_id, repo_hash, repo_commit)  #coje count = 1 y index el ultimo + 1 por defecto
        if result is None:
            fail(f"No se ha podido crear el proceso")
            break

        process_id, execution_id = result

        run_in_docker(command=f"cd /repo && make clean", name=docker_name)


        cmd = f"cd /repo && make run"
        result =result = await asyncio.to_thread(run_in_docker, cmd, stats=True, name=docker_name, output=True, gpu=config.GPU_DEVICE) 

        if config.GPU_DEVICE is not None:
            stdout, cpu_cycles, cpu_time, ram_avg, vram_avg, tdp_w = result
        else:
            stdout, cpu_cycles, cpu_time, ram_avg = result

        debug(f"CPU_CYCLES: {cpu_cycles} CPUT_TIME: {cpu_time} RAM_AVG {ram_avg}")


        if stop_flag.is_set():
            debug("Cancelado durante ejecución, no se suben resultados")
            break


        if str(output_mode) == "file":
            output_file = filename_pattern
            OUTPUT = os.path.join(cfg.outputs.dir, output_file)

            run_in_docker(command=f"mkdir -p {cfg.outputs.dir} && touch {OUTPUT}", name=docker_name)

            run_in_docker(command=f"tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -cf - {OUTPUT} | gzip -n > {OUTPUT}.tar.gz", name=docker_name)

            cmd=f"python3 /scripts/upload_results.py --no-stdin {config.TOKEN} {task_id} {process_id} {execution_id} {OUTPUT}.tar.gz {cpu_cycles} {ram_avg}"

            
        else:

            cmd = f"python3 /scripts/upload_results.py --stdin {config.TOKEN} {task_id} {process_id} {execution_id} {cpu_cycles} {ram_avg}"

        if config.GPU_DEVICE is not None:
            cmd += f" {vram_avg} {tdp_w}"

        stdout_lines = stdout.split('\n', 1)    #quitar commando de llamada
        stdout_clean = stdout_lines[1] if len(stdout_lines) > 1 else stdout

        
        run_in_docker(command=sanitize_command(cmd), name=docker_name, stdin=stdout_clean, root=True)

    end_docker(docker_name)


def confirm(task_id: str, process_id: str, cache: bool, cfg = None, repo_hash: str = None, actual_commit: str = None, terminate=False):
    docker_name = get_container_name(task_id)
    section("CONFIRM")

    try:

        process = get_process(task_id, process_id)

        if not process:
            fail("Proceso no encontrado")
            return

        proc = process[0]

        start = int(proc['input_start_index'])
        end = int(proc['input_end_index'])
        proc_hash = proc['repo_snapshot_hash']
        proc_commit = proc['repo_commit']


        if repo_hash is None or actual_commit is None or cfg is None:
            cfg, repo_hash, actual_commit=init_environment(task_id, cache, show_run=False)


        if proc_commit != actual_commit:
            warn("Intentando cambiar al commit con el que fue procesado el bloque")
            commit_exists = run_in_docker(
                command=f"git -C /repo cat-file -e {proc_commit} && echo 'exists'",
                output=True, name=docker_name
            )
            if not commit_exists or 'exists' not in commit_exists:
                fail(f"El commit {proc_commit} no existe en el repositorio, no se puede confirmar")
                return

            cfg, repo_hash, actual_commit=init_environment(task_id, cache=False, commit=proc_commit, show_run=False)


        if proc_hash != repo_hash:
            fail("El proceso no puede ser confirmado, alguno de los ficheros han sido alterados desde el momento de su subida")
            return 

        execution_id = create_execution(task_id, process_id)

        if execution_id is None:
            return



        filename_pattern = cfg.outputs.filename_pattern

        input_type = cfg.inputs.type



        if input_type == "file_single":
            path = cfg.inputs.file_single.path
            index_file = cfg.inputs.file_single.index_file
            index_len = cfg.inputs.file_single.index_len
            delimiter = cfg.inputs.file_single.delimiter
            delimiter_escaped = delimiter.encode("unicode_escape").decode("ascii")

            if index_file != None and index_len != None:
                n_entries = end - start + 1
                raw_index = run_in_docker(
                    command=f"dd if=/repo/{index_file} bs={index_len} skip={start} count={n_entries} 2>/dev/null",
                    output=True, name=docker_name
                )

                entries = []
                for line in raw_index.strip().splitlines():
                    parts = line.split()
                    entries.append((int(parts[0]), int(parts[1])))

                byte_skip  = entries[0][0]
                last_off, last_len = entries[-1]
                byte_count = (last_off + last_len) - byte_skip

                stdout = run_in_docker(
                    command=f"dd if=/repo/{path} bs=1 skip={byte_skip} count={byte_count} 2>/dev/null",
                    output=True, name=docker_name
                )

            else:

                stdout = run_in_docker(command=f"awk 'BEGIN{{RS=\"{delimiter_escaped}\"}} NR>={start} && NR<={end}' /repo/{path}", output=True, name=docker_name)

            words = stdout.strip().split(delimiter_escaped)
            cmd = f"cd /repo && make run WORDS={shlex.quote(' '.join(words))}"
        else:
            cmd = f"cd /repo && make run START={start} END={end}"

        result = run_in_docker(command=cmd, stats=True, name=docker_name, output=True, gpu=config.GPU_DEVICE)


        if config.GPU_DEVICE is not None:
            stdout, cpu_cycles, cpu_time, ram_avg, vram_avg, tdp_w = result
        else:
            stdout, cpu_cycles, cpu_time, ram_avg = result

        output_mode = cfg.outputs.mode
        filename_pattern = cfg.outputs.filename_pattern


        if str(output_mode) == "file":
            try:
                output_file = filename_pattern.format(start=start, end=end)
            except KeyError:
                output_file = filename_pattern 
            OUTPUT = os.path.join(cfg.outputs.dir, output_file)

            run_in_docker(command=f"mkdir -p {cfg.outputs.dir} && touch {OUTPUT}", name=docker_name)

            run_in_docker(command=f"tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner -cf - {OUTPUT} | gzip -n > {OUTPUT}.tar.gz", name=docker_name)

            cmd=f"python3 /scripts/upload_results.py --no-stdin {config.TOKEN} {task_id} {process_id} {execution_id} {OUTPUT}.tar.gz {cpu_cycles} {ram_avg}"

            
        else:

            cmd = f"python3 /scripts/upload_results.py --stdin {config.TOKEN} {task_id} {process_id} {execution_id} {cpu_cycles} {ram_avg}"

        if config.GPU_DEVICE is not None:
            cmd += f" {vram_avg} {tdp_w}"

        stdout_lines = stdout.split('\n', 1)    #quitar commando de llamada
        stdout_clean = stdout_lines[1] if len(stdout_lines) > 1 else stdout

        
        run_in_docker(command=sanitize_command(cmd), name=docker_name, stdin=stdout_clean, root=True)

    except requests.exceptions.ConnectionError:
        fail("Error en la comunicación con los servidores, reintentelo mas tarde.")
    finally:
        if terminate:
            end_docker(docker_name)


async def test(github_url: str, start: int, end: int):
    section("TEST")


    try:

        info("Iniciando entorno aislado...")
        start_docker(cpu_threads=config.CPU_THREADS, ram_mb=config.RAM, gpu_id=config.GPU_DEVICE, cache=False)

        info("Clonando repositorio...")

        run_in_docker(command=f"git clone {github_url} /repo")

        load_config(github_url)
        packages = cfg().requirements.packages  #devuelve lista
        filename_pattern = cfg().outputs.filename_pattern
        output_mode = cfg().outputs.mode

        input_type = cfg().inputs.type

        if input_type == "file_single":
            path = cfg().inputs.file_single.path
            index_file = cfg.inputs.file_single.index_file
            index_len = cfg.inputs.file_single.index_len
            delimiter = cfg().inputs.file_single.delimiter
            delimiter_escaped = delimiter.encode().decode("unicode_escape")

        cmd_packages = " ".join(packages)   #devuelve string con espacio entre cada item

        run_in_docker(command=f"apt update -y && apt install -y {cmd_packages}", root=True)     #solo se admiten paquetes originales de los repositorios por defecto ya que se debe ejecutar como root

        run_in_docker(command=f"cd /repo && make setup")

        if input_type == "file_single":

            if index_file != None and index_len != None:
                n_entries = end - start + 1
                raw_index = run_in_docker(
                    command=f"dd if=/repo/{index_file} bs={index_len} skip={start} count={n_entries} 2>/dev/null",
                    output=True
                )

                entries = []
                for line in raw_index.strip().splitlines():
                    parts = line.split()
                    entries.append((int(parts[0]), int(parts[1])))

                byte_skip  = entries[0][0]
                last_off, last_len = entries[-1]
                byte_count = (last_off + last_len) - byte_skip

                stdout = run_in_docker(
                    command=f"dd if=/repo/{path} bs=1 skip={byte_skip} count={byte_count} 2>/dev/null",
                    output=True
                )

            else:

                stdout = run_in_docker(command=f"awk 'BEGIN{{RS=\"{delimiter_escaped}\"}} NR>={start} && NR<={end}' /repo/{path}", output=True)

            words = stdout.strip().split(delimiter_escaped)
            cmd = f"cd /repo && make run WORDS={shlex.quote(' '.join(words))}"
        else:
            cmd = f"cd /repo && make run START={start} END={end}"

        result = run_in_docker(command=cmd, stats=True, output=True, gpu=config.GPU_DEVICE)
        if config.GPU_DEVICE is not None:
            stdout, cpu_cycles, cpu_time, ram_avg, vram_avg, tdp_w = result

        else:
            stdout, cpu_cycles, cpu_time, ram_avg = result

        if output_mode == 'stdout':
            debug(f"Salida obtenida: {stdout}")
        else:

            output_file = filename_pattern.format(start=start, end=end)
            OUTPUT = os.path.join(cfg().outputs.dir, output_file)

            check_cmd = f'[ -f "{OUTPUT}" ] && ([ -r "{OUTPUT}" ] && cat "{OUTPUT}" || echo "No legible") || echo "No existe"'
            run_in_docker(command=check_cmd)  

        debug(f"CPU_CYCLES: {cpu_cycles} CPUT_TIME: {cpu_time}")
    
    finally:
        end_docker()


async def test_input(github_url: str, word: str):

    section("TEST")


    try:

        info("Iniciando entorno aislado...")
        start_docker(cpu_threads=config.CPU_THREADS, ram_mb=config.RAM, gpu_id=config.GPU_DEVICE, cache=False)

        info("Clonando repositorio...")

        run_in_docker(command=f"git clone {github_url} /repo")

        load_config(github_url)
        packages = cfg().requirements.packages  #devuelve lista
        filename_pattern = cfg().outputs.filename_pattern

        input_type = cfg().inputs.type
        output_mode = cfg().outputs.mode

        if input_type != "dynamic":
            fail("Este tipo de tests solo están pensados para tareas dinámicas")
            exit()

        cmd_packages = " ".join(packages)   #devuelve string con espacio entre cada item

        run_in_docker(command=f"apt update -y && apt install -y {cmd_packages}", root=True)     #solo se admiten paquetes originales de los repositorios por defecto ya que se debe ejecutar como root

        run_in_docker(command=f"cd /repo && make setup")

        cmd = f"cd /repo && make run WORD={shlex.quote(word)}"

        result = run_in_docker(command=cmd, stats=True, output=True, gpu=config.GPU_DEVICE)
        if config.GPU_DEVICE is not None:
            stdout, cpu_cycles, cpu_time, ram_avg, vram_avg, tdp_w = result

        else:
            stdout, cpu_cycles, cpu_time, ram_avg = result

        if output_mode != 'stdout':
            output_file = filename_pattern.format(word=word)
            OUTPUT = os.path.join(cfg().outputs.dir, output_file)

            check_cmd = f'[ -f "{OUTPUT}" ] && ([ -r "{OUTPUT}" ] && cat "{OUTPUT}" || echo "No legible") || echo "No existe"'
            run_in_docker(command=check_cmd)  

        debug(f"CPU_CYCLES: {cpu_cycles} CPUT_TIME: {cpu_time}")
    
    finally:
        end_docker()



def init_environment(task_id, cache=True, commit=None, show_run=True):

    if show_run: 
        section("RUN")


    info("Obteniendo datos de la tarea...")
    task = get_task(task_id)

    if task == None:
        fail("Tarea no encontrada")
        exit()
        


    docker_name = get_container_name(task_id)

    exists=False

    if cache:
        exists = docker_exists(docker_name)

    info("Iniciando entorno aislado...")
    start_docker(cpu_threads=config.CPU_THREADS, ram_mb=config.RAM, gpu_id=config.GPU_DEVICE, name=docker_name, cache=cache)


    load_config(task['github_url'])

    gu = GithubUtil(task['github_url'])
    branch = gu.get_branch()
    
    HASH_FILE = "/home/worker/.repo_hash"

    if not exists:

        info("Clonando repositorio...")

        run_in_docker(command=f"git clone {gu.get_repo_link()} /repo", name=docker_name, network=True)

        run_in_docker(command=f"chown -R worker:worker /repo", name=docker_name, root=True)

        if branch != None:

            run_in_docker(command=f"cd /repo && git checkout {branch}", name=docker_name)

        if commit is not None:

            run_in_docker(command=f"git -C /repo checkout {commit}", name=docker_name)


        EXCLUDED_PACKAGES = {"wget", "curl"}        #necesario para evitar que se cargue los wrappers

        packages = [p for p in cfg().requirements.packages if p not in EXCLUDED_PACKAGES]

        cmd_packages = " ".join(packages)   #devuelve string con espacio entre cada item

        info("Instalando dependencias y actualizando sistema...")

        run_in_docker(command=f"apt update -y && apt install -y {cmd_packages}", root=True, name=docker_name)     #solo se admiten paquetes originales de los repositorios por defecto ya que se debe ejecutar como root

        for dl in cfg().download.files:
            run_in_docker(command=f"cd /repo && curl -fsSL '{dl.url}' --output '{dl.dest}'", name=docker_name)
            run_in_docker(command=f"cd /repo && chown worker:worker {dl.dest}", name=docker_name, root=True)
            if dl.post:
                run_in_docker(command=f"cd /repo && {dl.post}", name=docker_name)


        repo_hash_pre_setup = run_in_docker(
            command="python3 /scripts/hash_util.py /repo",
            output=True,
            name=docker_name,
            root=True
        )

        run_in_docker(command=f"cd /repo && make setup", name=docker_name)

    info("Aplicando políticas de seguridad...")

    allowed = cfg().network.allowed_hosts   #aunque cachee al reinciar el docker iptables se pierde
    for host in allowed:
        run_in_docker(command=f"iptables -I OUTPUT -d {host} -j ACCEPT", name=docker_name, root=True) 
    run_in_docker(command=f"/scripts/iptables.sh", name=docker_name, root=True) 


    info("Limpiando archivos inecesarios...")


    run_in_docker(command=f"cd /repo && make clean", name=docker_name)      #obviamente no podemos tener ficheros previos a pesar de usar cache 

    if not exists:


        hash_excludes = cfg().hash.exclude
        exclude_args = " ".join(shlex.quote(e) for e in hash_excludes)

        repo_hash_post_setup = run_in_docker(
            command=f"python3 /scripts/hash_util.py /repo {exclude_args}",
            output=True,
            name=docker_name,
            root=True
        )

        repo_hash_pre_setup = repo_hash_pre_setup.strip()
        repo_hash_post_setup = repo_hash_post_setup.strip()

        repo_hash = hashlib.sha256(f"{repo_hash_pre_setup}{repo_hash_post_setup}".encode()).hexdigest()
        run_in_docker(command=f"echo -n {repo_hash} > {HASH_FILE}", name=docker_name, root=True)

    else:
        repo_hash = run_in_docker(
            command=f"cat {HASH_FILE}",
            output=True,
            name=docker_name,
            root=True
        ).strip()


    repo_commit = run_in_docker(
        command=f"git -C /repo rev-parse HEAD",
        output=True,
        name=docker_name
    ).strip()

    section("RUN")

    return cfg(), repo_hash, repo_commit 


def get_container_name(task_id):
    task_bytes = str(task_id).encode("utf-8")
    return f"worker_{hashlib.sha256(task_bytes).hexdigest()[:8]}"


def create_process(task_id, repo_hash, repo_commit, index=None, count=None, value=None):

    if value == None:
        r = requests.post(
            f"{BASE_URL}/task/{task_id}/process",
            params={
                "index": index,
                "count": count,
                "repo_hash": repo_hash,
                "repo_commit": repo_commit
            },
            headers={"token": config.TOKEN}
        )
    else:
        r = requests.post(
            f"{BASE_URL}/task/{task_id}/process",
            params={
                "index": index,
                "count": count,
                "value": value,
                "repo_hash": repo_hash,
                "repo_commit": repo_commit
            },
            headers={"token": config.TOKEN}
        )

    
    if r.status_code == 200:
        return r.json()["process_id"], r.json()["execution_id"]
    else:
        fail(f"Error: {r.text}")


def get_task(task_id):
    r = requests.get(f"{BASE_URL}/task/{task_id}")

    if r.status_code == 200:
        return r.json()
    else:
        try:
            fail("Error:", r.json().get("detail"))
        except:
            fail("Fallo interno del servidor")

def merge_consecutive_ranges(ranges):

    if not ranges:
        return []

    ranges = sorted(ranges, key=lambda x: x['index'])

    merged = []
    current = ranges[0].copy()

    for r in ranges[1:]:
        if r['index'] == current['index'] + current['count']:
            current['count'] = r['index'] + r['count'] - current['index']
        else:
            merged.append(current)
            current = r.copy()

    merged.append(current)
    return merged


def get_continue_information(task_id: str) -> str:
    r = requests.get(
        f"{BASE_URL}/task/{task_id}",
        params={"fields": "status,publisher"}
    )

    if r.status_code == 200:
        user_id = jwt.decode(config.TOKEN, options={"verify_signature": False})['sub']
        if r.json()["status"] not in INACTIVE_STATUSES or int(r.json()["publisher"])  == int(user_id):
            return True
    else:
        return False


def getConfirmationProcessId(task_id: str) -> str:
    r = requests.get(
        f"{BASE_URL}/task/{task_id}/confirm",
        headers={"token": config.TOKEN}
    )
    if r.status_code != 200:
        fail("Error:", r.text)
        return None
    
    data = r.json()
    if data.get("status") == "nothing_to_verify":
        fail("No hay procesos que verificar")
        return None
        
    return data['process_id']


def getProcessByIndex(task_id: str, index: int) -> str:
    r = requests.get(
        f"{BASE_URL}/task/{task_id}/process",
        headers={"token": config.TOKEN},
        params={"index": index}
    )
    
    if r.status_code != 200:
        fail("Error obteniendo proceso:", r.text)
        return None
    
    data = r.json()
    
    if not data.get("result"):  # si la API devuelve lista vacía
        fail(f"No hay proceso que contenga el índice {index}")
        return None
    
    # suponiendo que la API devuelve algo como {"result":[{"id":123,...}]}
    process = data["result"][0]
    return process.get("id")

def sanitize_command(command: str, user: str = "worker") -> str:
    home_map = {
        "worker": "/home/worker",
        "net_user": "/home/net_user",
        "root": "/root"
    }
    home = home_map.get(user, f"/home/{user}")
    
    # Expansión de ~
    command = re.sub(r'~/' , f'{home}/', command)
    command = re.sub(r'^~$', home, command)
    
    # $HOME
    command = command.replace("$HOME", home)
    command = command.replace("${HOME}", home)
    
    # $USER
    command = command.replace("$USER", user)
    command = command.replace("${USER}", user)
    
    # $UID
    uid_map = {"worker": "1001", "net_user": "1000", "root": "0"}
    uid = uid_map.get(user, "1001")
    command = command.replace("$UID", uid)
    command = command.replace("${UID}", uid)

    return command


def get_process(task_id, process_id):
    r = requests.get(f"{BASE_URL}/task/{task_id}/process/{process_id}")
    if r.status_code != 200:
        fail(f"Error obteniendo process: {r.text}")
        return
    return r.json()['result']

def create_execution(task_id, process_id):
    r = requests.post(
        f"{BASE_URL}/task/{task_id}/process/{process_id}/execution",
        headers={"token": config.TOKEN}
    )
    if r.status_code != 200:
        fail(f"Error obteniendo process: {r.text}")
        return

    if r.json().get("error"):
        fail(r.json()["error"])
        return

    return r.json()["execution_id"]