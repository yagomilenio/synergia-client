import subprocess
import os
import re
from . utils.logger import section, ok, fail, warn, info, debug, container_started, commit_info
from rich.console import Console
from rich.text import Text
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

"""
PARA USAR ESTA UTILIDAD HAY QUE INSTALAR Y TENER EN EL PATH DOCKER
"""

CONFIG_PATH = Path("~/.config/synergia/config.ini").expanduser()

_console = Console()

def _run_streaming(cmd: list, label: str = ""):
    """Ejecuta un comando mostrando cada línea de output con prefijo Rich en tiempo real."""
    import sys
    _console.print(f"  [dim #555566]┌─[/] [bold #7B8CDE]{label}[/]") if label else None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        # Colorear según contenido
        if any(w in line for w in ("error", "Error", "ERROR", "failed", "Failed")):
            _console.print(f"  [dim #555566]│[/]  [#E05555]{line}[/]")
        elif any(w in line for w in ("warning", "Warning", "WARNING", "WARN")):
            _console.print(f"  [dim #555566]│[/]  [#F0A500]{line}[/]")
        elif any(w in line for w in ("✓", "OK", "done", "Done", "complete", "Complete", "exitosamente", "instalad")):
            _console.print(f"  [dim #555566]│[/]  [#4EC99B]{line}[/]")
        else:
            _console.print(f"  [dim #555566]│[/]  [dim #888899]{line}[/]")
    proc.wait()
    _console.print(f"  [dim #555566]└─[/]") if label else None
    return proc.returncode




def start_docker(image="task-worker:latest", name="worker", cpu_threads=None, ram_mb=None, gpu_id=None, cache=True):

    result = subprocess.run(["docker", "images", "-q", image], capture_output=True, text=True)
    if not result.stdout.strip():
        info(f"Imagen {image} no encontrada. Construyendo...")
        build_image(tag=image)
    else:
        info(f"Imagen {image} encontrada, usando existente.")



    if not cache:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) #eliminamos docker si es que previamente ya se habia creado 

    if docker_exists(name):
        if docker_is_running(name):
            warn(f"Contenedor {name} ya está corriendo, por favor espere a que la tarea que está ejecutando finalice. En caso contrario puede pararlo de forma forzosa con el siguiente comando:\ndocker rm -f {name}")
            exit() 
        else:
            info(f"Contenedor {name} existe pero está parado -> arrancando")
            subprocess.run(["docker", "start", name], check=True)
            container_started(name, cpu=cpu_threads, ram_mb=ram_mb, gpu=gpu_id)
            return
    
    #cmd = ["docker", "run", "-dit", "--name", name]
    cmd = [
    "docker", "run", "-dit",
    "--cap-add=PERFMON",
    "--cap-add=NET_ADMIN",
    "--add-host=host.docker.internal:host-gateway",
    "--name", name
    ]       #modificada para permitir conexion docker host, esto es solo para desarrollo

    if cpu_threads:
        cmd += ["--cpuset-cpus", f"0-{int(cpu_threads)-1}"]      #si solo se usa --cpus docker asigna tiempo en cpu... no aisla nucleos, y es problema para programas que usan todos los hilos
    if ram_mb:
        cmd += ["--memory", f"{ram_mb}m"]
    if gpu_id is not None:
        cmd += ["--gpus", f"device={gpu_id}"]

    cmd += ["-v", f"{CONFIG_PATH.resolve()}:/scripts/config.ini:ro"]
    cmd.append(image)
    cmd.append("bash")  # ejecuta bash en background

    subprocess.run(cmd, check=True)
    container_started(name, cpu=cpu_threads, ram_mb=ram_mb, gpu=gpu_id)




def docker_exists(name):
    result = subprocess.run(
        ["docker", "ps", "-a", "-q", "-f", f"name=^{name}$"],
        capture_output=True,
        text=True
    )
    return bool(result.stdout.strip())

def docker_is_running(name):
    result = subprocess.run(
        ["docker", "ps", "-q", "-f", f"name=^{name}$"],
        capture_output=True,
        text=True
    )
    return bool(result.stdout.strip())


def run_in_docker(command, name="worker", stats=False, root=False, output=False, stdin=None, gpu=None, network=False):
    cpu_cycles = 0
    time_elapsed = 0


    if stats:
        command_escaped = command.replace("'", "'\\''")

        if gpu is not None:

            cmd = (
                # Obtener TDP una sola vez
                f"TDP=$(nvidia-smi --query-gpu=power.max_limit --format=csv,noheader,nounits | tr -d ' ') ; "
                
                # Bucle de muestreo cada 1s
                f"while true; do "
                f"  CONTAINER_PIDS=$(ls /proc | grep -E '^[0-9]+$' | tr '\\n' ',') ; "  # PIDs del contenedor
                f"  nvidia-smi --query-compute-apps=pid,used_gpu_memory --format=csv,noheader,nounits 2>/dev/null"
                f"  | awk -F',' -v pids=\"$CONTAINER_PIDS\" 'BEGIN{{split(pids,p,\",\")}} "
                f"    {{for(i in p) if(p[i]==$1) sum+=$2}} END{{print sum+0}}' >> /tmp/vram_{name}.txt ; "
                f"  sleep 1 ; "
                f"done & "
                f"VRAM_MON_PID=$! ; "

                f"while true; do "
                f"  ps -eo rss= | awk '{{sum+=$1}} END {{print sum*1024}}' 2>/dev/null >> /tmp/ram_{name}.txt;"  # PIDs del contenedor
                f"  sleep 1;"
                f"done & "
                f"RAM_MON_PID=$! ; "
                
                # Comando principal
                f"perf stat -o /tmp/perf_{name}.txt bash -c '{command_escaped}' 2>/dev/null ; "
                
                # Parar monitor
                f"kill $VRAM_MON_PID 2>/dev/null ; wait $VRAM_MON_PID 2>/dev/null ; "
                f"kill $RAM_MON_PID 2>/dev/null ; wait $RAM_MON_PID 2>/dev/null ; "
                f"echo $TDP > /tmp/tdp_{name}.txt"
            )
        else: 

            cmd = f"perf stat -o /tmp/perf_{name}.txt bash -c '{command_escaped}' 2>/dev/null"
        
        proc = subprocess.run(
            ["docker", "exec", "-i", "--user", "worker", name, "bash", "-c", cmd], capture_output=True, text=True
        )


        if proc.returncode != 0:

            fail(f"La ejecución del comando falló con el codigó {proc.returncode}")
            debug(command)
            debug(f"stderr: {proc.stderr.strip()}")
            run = input("¿Desea ejecutarlo como usuario privilegiado? [S/N] ")
            if run.lower() == "s":
                subprocess.run(
                ["docker", "exec", "-i", "--user", "root", name, "bash", "-c", cmd]
                )
            else:
                info("Abortando...")
                end_docker(name)
                return
        

        perf_out = subprocess.run(
            ["docker", "exec", "-i", "--user", "worker", name, "bash", "-c", f"cat /tmp/perf_{name}.txt"],
            capture_output=True, text=True
        ).stdout

        stdout=proc.stdout

        cycles_match = re.search(r'(\d+)\s+cycles', perf_out)
        time_match = re.search(r'([\d.]+)\s+seconds time elapsed', perf_out)


        cpu_cycles = int(cycles_match.group(1).replace(',', '')) if cycles_match else 0
        time_elapsed = float(time_match.group(1)) if time_match else 0


        ram_out = subprocess.run(
                ["docker", "exec", "-i", "--user", "worker", name, "bash", "-c", f"cat /tmp/ram_{name}.txt"],
                capture_output=True, text=True
            ).stdout

        ram_samples = []
        for line in ram_out.strip().splitlines():
            try:
                ram_samples.append(float(line.strip()))
            except ValueError:
                pass

        ram_avg  = sum(ram_samples) / len(ram_samples) if ram_samples else 0


        if gpu is not None:
            vram_out = subprocess.run(
                ["docker", "exec", "-i", "--user", "worker", name, "bash", "-c", f"cat /tmp/vram_{name}.txt"],
                capture_output=True, text=True
            ).stdout

            vram_samples = []
            for line in vram_out.strip().splitlines():
                try:
                    vram_samples.append(float(line.strip()))
                except ValueError:
                    pass

            vram_avg  = sum(vram_samples) / len(vram_samples) if vram_samples else 0

            
            

            tdp_out = subprocess.run(
                ["docker", "exec", "-i", "--user", "worker", name, "bash", "-c", f"cat /tmp/tdp_{name}.txt"],
                capture_output=True, text=True
            ).stdout
            tdp_w = float(tdp_out.strip()) if tdp_out.strip() else 0

            debug(f"VRAM avg: {vram_avg:.1f} MB | TDP: {tdp_w:.1f} W")

            return (stdout, cpu_cycles, time_elapsed, ram_avg, vram_avg, tdp_w) if output else (cpu_cycles, time_elapsed, ram_avg, vram_avg, tdp_w)

        return (stdout, cpu_cycles, time_elapsed, ram_avg) if output else (cpu_cycles, time_elapsed, ram_avg)


    elif root:
        if not output:
            label = command[:60] + ("..." if len(command) > 60 else "")
            _run_streaming(["docker", "exec", "-i", "--user", "root", name, "bash", "-c", command], label=label)
            return None
        result = subprocess.run(["docker", "exec", "-i", "--user", "root", name, "bash", "-c", command], capture_output=output, text=output, input=stdin.encode() if isinstance(stdin, str) else stdin)
        stdout = result.stdout
        return stdout if output else None


            
    else:

        if network:
            user = "net_user"
        else:
            user = "worker"



        if not output:
            label = command[:60] + ("..." if len(command) > 60 else "")
            rc = _run_streaming(
                ["docker", "exec", "-i", "--user", user, name, "bash", "-c", command],
                label=label
            )
            if rc != 0:
                fail(f"La ejecucion del comando fallo con codigo {rc}")
                run_as_root = input("Desea ejecutarlo como usuario privilegiado? [S/N] ")
                if run_as_root.lower() == "s":
                    _run_streaming(
                        ["docker", "exec", "-i", "--user", "root", name, "bash", "-c", command],
                        label=label
                    )
                else:
                    info("Abortando...")
                    end_docker(name)
            return None

        result = subprocess.run(["docker", "exec", "-i", "--user", user, name, "bash", "-c", command], capture_output=output, text=output, input=stdin.encode() if isinstance(stdin, str) else stdin)
        
        if result.returncode != 0:
            fail(f"La ejecución del comando falló con el codigó {result.returncode}")
            debug(command)
            debug(f"stderr: {result.stderr.strip()}")
            run = input("¿Desea ejecutarlo como usuario privilegiado? [S/N] ")
            if run.lower() == "s":
                result = subprocess.run(["docker", "exec", "-i", "--user", "root", name, "bash", "-c", command], capture_output=output, text=output)
            else:
                info("Abortando...")
                end_docker(name)
                return
                
        stdout = result.stdout
        return stdout if output else None
            





def end_docker(name="worker", delete=False):
    if(delete):
        result = subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL 
        )
        if result.returncode == 0:
            info(f"Contenedor {name} detenido y eliminado")
        

    else:
        result = subprocess.run(
            ["docker", "stop", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL 
        )
        if result.returncode == 0:
            info(f"Contenedor {name} detenido")
        

def build_image(dockerfile_dir=BASE_DIR, tag=None):
    if tag is None:
        tag = "task-worker:1.0.0"

    info(f"Construyendo imagen Docker: {tag}")
    dockerfile_dir = str(BASE_DIR / "worker")
    result = subprocess.run(["docker", "build", "--no-cache", "-t", tag, dockerfile_dir], capture_output=True, text=True)

    if result.returncode == 0:
        ok("Imagen construida correctamente!")
        debug(result.stdout)
        return tag
    else:
        fail("Error al construir la imagen:")
        fail(result.stderr)
        raise RuntimeError("Error construyendo la imagen Docker")


