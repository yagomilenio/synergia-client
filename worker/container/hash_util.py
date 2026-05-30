import hashlib
import os
import sys

def hash_directory(path: str, excludes: list[str] = []) -> str:
    sha256 = hashlib.sha256()
    exclude_abs = {os.path.abspath(os.path.join(path, e)) for e in excludes}
    for root, dirs, files in os.walk(path):
        dirs[:] = [
            d for d in dirs
            if d != ".git" and os.path.abspath(os.path.join(root, d)) not in exclude_abs
        ]  #evitar tener en cuenta el .git que es cambiante y archivos compilados
        dirs.sort()
        for filename in sorted(files):
            filepath = os.path.join(root, filename)
            
            if os.path.abspath(filepath) in exclude_abs:
                continue
            relative_path = os.path.relpath(filepath, path)
            sha256.update(relative_path.encode('utf-8'))
            with open(filepath, 'rb') as f:
                while chunk := f.read(8192):
                    sha256.update(chunk)
    return sha256.hexdigest()

def hash_external_deps(log_path: str) -> str:
    if not os.path.exists(log_path):
        return "no-external-deps"
    with open(log_path, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]
    lines.sort()  # sort por hash (primera columna), determinista
    sha256 = hashlib.sha256()
    for line in lines:
        sha256.update(line.encode('utf-8'))
    return sha256.hexdigest()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python hash_util.py <path> [exclude1 exclude2 ...]")
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.isdir(path):
        print(f"Error: '{path}' no es un directorio válido")
        sys.exit(1)
    excludes = sys.argv[2:]

    repo_hash = hash_directory(path, excludes)
    deps_hash = hash_external_deps("/home/net_user/external_deps.log")

    combined = hashlib.sha256(f"{repo_hash}{deps_hash}".encode()).hexdigest()
    print(combined)