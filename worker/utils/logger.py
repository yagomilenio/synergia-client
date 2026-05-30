import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.console import Group
from rich import box
import sys

console = Console()

VERBOSE = os.getenv("SYNERGIA_VERBOSE", "0") == "1"

THEME = {
    "primary": "#7B8CDE",
    "success": "#4EC99B",
    "warning": "#F0A500",
    "error":   "#E05555",
    "muted":   "#555566",
    "dim":     "#3a3a4a",
    "text":    "#C8C8D4",
    "accent":  "#B060D0",
}




def section(title: str):
    console.print()
    console.print(Rule(
        f"[bold {THEME['primary']}]{title}[/]",
        style=THEME["dim"],
        align="left"
    ))
    console.print()




def ok(msg: str):
    console.print(f"  [bold {THEME['success']}]✓[/]  [{THEME['text']}]{msg}[/]")

def fail(msg: str, exit=False):
    console.print(f"  [bold {THEME['error']}]✗[/]  [bold {THEME['error']}]{msg}[/]")
    if exit:
        sys.exit(1)


def warn(msg: str):
    console.print(f"  [bold {THEME['warning']}]![/]  [{THEME['warning']}]{msg}[/]")

def info(msg: str):
    console.print(f"  [dim {THEME['muted']}]·[/]  [{THEME['text']}]{msg}[/]")

def info_inline(msg: str):
    console.print(f"  [dim {THEME['muted']}]·[/]  [{THEME['text']}]{msg}[/]", end="\r")

def run(msg: str):
    console.print(f"  [{THEME['accent']}]▶[/]  [bold {THEME['text']}]{msg}[/]")

def muted(msg: str):
    console.print(f"     [dim {THEME['muted']}]{msg}[/]")

def debug(msg: str):
    """Solo visible con SYNERGIA_VERBOSE=1"""
    if VERBOSE:
        console.print(f"  [dim {THEME['dim']}]vrb[/]  [dim {THEME['muted']}]{msg}[/]")




def container_started(name: str, cpu, ram_mb, gpu):
    t = Table.grid(padding=(0, 2))
    t.add_column(style=f"dim {THEME['muted']}", width=10)
    t.add_column(style=f"{THEME['primary']}", justify="right")
    t.add_row("nombre", name)
    t.add_row("cpu",    f"{cpu} threads")
    t.add_row("ram",    f"{ram_mb} MB")
    t.add_row("gpu",    str(gpu) if gpu is not None else "—")
    console.print(Panel(
        t,
        title=f"[bold {THEME['primary']}]contenedor iniciado[/]",
        border_style=THEME["dim"],
        expand=False,
        padding=(0, 1),
    ))


def commit_info(commit_hash: str, message: str = ""):
    short = commit_hash[:7] if len(commit_hash) > 7 else commit_hash
    msg = f"[bold {THEME['warning']}]HEAD detached[/]  [{THEME['muted']}]→[/]  [{THEME['primary']}]{short}[/]"
    if message:
        msg += f"\n  [dim {THEME['muted']}]{message}[/]"
    console.print(Panel(
        msg,
        border_style=THEME["warning"],
        expand=False,
        padding=(0, 1),
    ))


def result_stats(returncode: int, cpu_cycles: int, cpu_time: float,
                 ram_avg: float, vram_avg: float = None, tdp_w: float = None,
                 stdout_preview: str = None):

    ok_color = THEME["success"] if returncode == 0 else THEME["error"]
    rc_label = "OK" if returncode == 0 else "ERROR"

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style=f"dim {THEME['muted']}", width=14)
    t.add_column(style=f"bold {THEME['text']}", justify="right")
    t.add_column(style=f"dim {THEME['muted']}", width=6)

    t.add_row("returncode", f"[{ok_color}]{returncode}  {rc_label}[/]", "")
    t.add_row("cpu cycles", f"{int(cpu_cycles):,}", "")
    t.add_row("cpu time",   f"{cpu_time:.3f}", "s")
    t.add_row("ram avg",    f"{ram_avg / 1024 / 1024:.1f}", "MB")
    if vram_avg is not None:
        t.add_row("vram avg", f"{vram_avg:.1f}", "MB")
    if tdp_w is not None:
        t.add_row("tdp",      f"{tdp_w:.1f}", "W")

    content = t
    if stdout_preview:
        lines = stdout_preview.strip().splitlines()[:6]
        preview = "\n".join(f"  [dim {THEME['muted']}]{l}[/]" for l in lines)
        content = Group(
            t,
            Text(""),
            Text.from_markup(f"  [dim {THEME['muted']}]stdout preview[/]"),
            Text.from_markup(preview),
        )

    console.print(Panel(
        content,
        title=f"[bold {ok_color}]resultado[/]",
        border_style=ok_color,
        expand=False,
        padding=(0, 1),
    ))


def summary(task_id, process_id, execution_id, status: str = "ok"):
    color = THEME["success"] if status == "ok" else THEME["error"]
    t = Table.grid(padding=(0, 2))
    t.add_column(style=f"dim {THEME['muted']}", width=14)
    t.add_column(style=f"bold {THEME['primary']}")
    t.add_row("task",      str(task_id))
    t.add_row("process",   str(process_id))
    t.add_row("execution", str(execution_id))
    console.print()
    console.print(Panel(
        t,
        title=f"[bold {color}]{'completado' if status == 'ok' else 'fallido'}[/]",
        border_style=color,
        expand=False,
        padding=(0, 1),
    ))
    console.print()