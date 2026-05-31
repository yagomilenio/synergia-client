# synergia-client

Cliente CLI de [Synergia](https://github.com/yagomilenio/synergia-server), una plataforma de computación distribuida P2P que permite publicar y ejecutar tareas de forma descentralizada entre nodos heterogéneos.

---

## Requisitos

- Python >= 3.10 (probado con Python 3.14.4)
- Docker instalado y en el PATH
- `perf` instalado con nivel de paranoia <= 2 (ver [Configuración del sistema](#configuración-del-sistema))
- Acceso a una instancia del servidor Synergia (REST API + WS API)

---

## Instalación

```bash
git clone https://github.com/yagomilenio/synergia-client.git
cd synergia-client
pip install -e .
```

Esto instala el comando `synergia` en el sistema junto con todas las dependencias declaradas en `pyproject.toml`.

---

## Configuración del sistema


### perf

El cliente usa `perf` para medir ciclos de CPU consumidos por cada tarea. Por defecto el kernel restringe su uso a root. Es necesario bajar el nivel de paranoia a 2 o menos:

```bash
# Temporal (hasta el próximo reinicio)
sudo sysctl kernel.perf_event_paranoid=2

# Permanente
echo 'kernel.perf_event_paranoid=2' | sudo tee /etc/sysctl.d/99-perf.conf
sudo sysctl -p /etc/sysctl.d/99-perf.conf
```

Niveles de `perf_event_paranoid`:


Instalar `perf`:

| Distro | Comando |
|--------|---------|
| Debian/Ubuntu | `apt install linux-perf` |
| Fedora/RHEL | `dnf install perf` |
| Arch | `pacman -S perf` |

---

## Configuración del cliente

### `worker/container/config.ini`

Contiene las URLs de conexión al servidor Synergia. Debe modificarse para apuntar a la instancia del servidor que se quiera usar (ngrok, dominio propio, IP pública, etc.):

```ini
[rest]
base_url = https://tu-servidor.ngrok-free.app
base_port = 443

[ws]
base_url = wss://tu-servidor-ws.ngrok-free.app
base_port = 443
```

Este fichero se monta como volumen dentro del contenedor Docker del worker, por lo que puede modificarse en caliente sin reconstruir la imagen. No es necesario reiniciar el contenedor si ya estaba corriendo — el cambio se aplica en la siguiente ejecución.

### Perfil de usuario (`~/.cn_profile.json`)

Se genera automáticamente al hacer login. Contiene el token JWT de sesión activa. No es necesario editarlo manualmente.

### Configuración del dispositivo (`~/.cn_device.json`)

Se genera con `configure-device`. Contiene los recursos hardware que el nodo ofrece a la red:

```json
{
    "cpu_threads": 8,
    "gpu_device": 0,
    "ram": 16384
}
```

---

## Comandos

### Autenticación

| Comando | Descripción |
|---------|-------------|
| `synergia sign-up-user --username <u> --email <e> --passwd <p>` | Registra un nuevo usuario |
| `synergia login-user --username <u> --passwd <p>` | Login con credenciales locales |
| `synergia login-user --email <e> --passwd <p>` | Login con email |
| `synergia login-google` | Login vía Google OAuth2 |
| `synergia login-github` | Login vía GitHub OAuth2 |
| `synergia logout-user` | Cierra la sesión actual |
| `synergia get-user-details --username <u>` | Consulta info y balance de un usuario |

### Dispositivo

| Comando | Descripción |
|---------|-------------|
| `synergia configure-device` | Detecta y guarda los recursos del dispositivo automáticamente |
| `synergia configure-device --cpu-threads <n> --gpu-device <id> --ram <mb>` | Configura los recursos manualmente |

### Tareas (publisher)

| Comando | Descripción |
|---------|-------------|
| `synergia create-task --name <n> --github-url <url>` | Crea una nueva tarea a partir de un repositorio GitHub |
| `synergia find-task` | Lista todas las tareas disponibles en la red |
| `synergia find-task --name <n> --status ACTIVE` | Filtra tareas por nombre y/o estado (`ACTIVE`, `PAUSED`, `CANCELLED`, `COMPLETED`) |
| `synergia find-task --subscribed` | Muestra solo las tareas a las que estás suscrito |
| `synergia task-info --task-id <id>` | Muestra información detallada de una tarea |
| `synergia add-inputs --task-id <id> --file <fichero>` | Añade inputs a una tarea dinámica desde fichero |
| `synergia add-inputs --task-id <id> --text <texto>` | Añade inputs a una tarea dinámica desde texto |
| `synergia output-task --task-id <id>` | Consulta los outputs de una tarea |
| `synergia output-task --task-id <id> --download` | Descarga los outputs como ZIP |
| `synergia output-task --task-id <id> --canonical-only` | Solo outputs canónicos (resultado verificado) |
| `synergia output-task --task-id <id> --process-id <pid>` | Output de un proceso concreto |
| `synergia sync-task --task-id <id>` | Sincroniza el hash del repositorio con la versión actual |
| `synergia pause-task --task-id <id>` | Pausa una tarea activa |
| `synergia active-task --task-id <id>` | Reactiva una tarea pausada |
| `synergia cancel-task --task-id <id>` | Cancela una tarea permanentemente |
| `synergia close-task --task-id <id>` | Cierra una tarea dinámica como completada |

### Tareas (worker)

| Comando | Descripción |
|---------|-------------|
| `synergia subscribe-task --task-id <id>` | Suscribe el nodo a una tarea y comienza a ejecutarla |
| `synergia subscribe-task --task-id <id> --no-cache` | Fuerza recreación del contenedor Docker |
| `synergia subscribe-task --task-id <id> --yes` | Acepta automáticamente sin confirmación interactiva |
| `synergia unsubscribe-task --task-id <id>` | Cancela la suscripción a una tarea |
| `synergia confirm-process --task-id <id> --process-id <id>` | Confirma manualmente un proceso ejecutado por otro nodo |
| `synergia confirm-process --task-id <id> --process-id <id> --no-cache` | Confirma forzando recreación del contenedor |
| `synergia process-info --task-id <id> --process-id <id>` | Muestra detalle de un proceso y sus ejecuciones |

### Scheduler

El scheduler ejecuta automáticamente todas las tareas activas a las que el nodo está suscrito, sin intervención manual.

| Comando | Descripción |
|---------|-------------|
| `synergia start-scheduler --mode round-robin` | Ejecuta las tareas en turnos, una a la vez |
| `synergia start-scheduler --mode split` | Divide los núcleos CPU entre todas las tareas y las ejecuta en paralelo |
| `synergia start-scheduler --mode round-robin --rotation <n>` | Chunks dedicados a cada tarea antes de rotar (por defecto: 5) |
| `synergia start-scheduler --mode round-robin --on-idle` | Solo consume CPU no utilizada por el resto del sistema |

### Testing

| Comando | Descripción |
|---------|-------------|
| `synergia test-task --github-url <url> --word <input>` | Prueba una tarea localmente con un input concreto |
| `synergia test-task --github-url <url> --range <start> <end>` | Prueba una tarea localmente con un rango de índices |

---

## Estructura del proyecto

```
synergia-client/
├── client/
│   ├── client.py                  # CLI principal, definición de todos los comandos
│   ├── config.py                  # Carga de sesión, dispositivo y config.ini
│   └── scheduler.py               # Scheduler automático (round-robin / split)
├── worker/
│   ├── worker.py                  # Lógica de suscripción y ejecución de tareas
│   ├── docker_util.py             # Gestión del contenedor Docker del worker
│   ├── Dockerfile                 # Imagen del contenedor de ejecución
│   ├── container/
│   │   ├── config.ini             # URLs del servidor (montado como volumen)
│   │   ├── upload_results.py      # Script de subida de resultados al servidor
│   │   ├── hash_util.py           # Utilidades de hashing SHA256
│   │   ├── iptables.sh            # Reglas de red del contenedor (bloqueo salida)
│   │   ├── curl_wrapper.c         # Wrapper de curl con registro de descargas
│   │   └── wget_wrapper.c         # Wrapper de wget con registro de descargas
│   └── utils/
│       ├── configuration_interpreter.py   # Intérprete del synergia.yml del repo
│       ├── github_util.py                 # Utilidades para repos GitHub
│       └── logger.py                      # Logger con Rich
├── tests/
│   ├── test.sh                    # Test de integración del sistema de consenso
│   ├── create_tasks.sh            # Script de creación de tareas de prueba
│   └── tasks.txt                  # Lista de tareas de prueba
├── pyproject.toml
└── requirements.txt
```

---

## Flujo de uso típico

**Como publisher** (publicar una tarea):

```bash
synergia login-user --username miusuario --passwd mipassword
synergia create-task --name "Mi tarea" --github-url https://github.com/user/repo
synergia task-info --task-id 1
synergia output-task --task-id 1 --download
```

**Como worker** (ejecutar tareas de otros y ganar créditos):

```bash
synergia login-user --username miusuario --passwd mipassword
synergia configure-device
synergia find-task --status ACTIVE
synergia subscribe-task --task-id 1
```

**Modo automático con scheduler**:

```bash
# Ejecutar todas las tareas suscritas en round-robin
synergia start-scheduler --mode round-robin

# Ejecutar en paralelo usando todos los núcleos disponibles
synergia start-scheduler --mode split

# Solo usar CPU que el sistema no esté usando
synergia start-scheduler --mode round-robin --on-idle
```

---

## Licencia

GPL-3.0 — ver [LICENSE](LICENSE)
