#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEV_LABEL_KEY_PATTERNS = [
    re.compile(r"^devcontainer\.", re.IGNORECASE),
    re.compile(r"(?:^|[._-])devcontainer(?:[._-]|$)", re.IGNORECASE),
    re.compile(r"(?:^|[._-])vsch(?:[._-]|$)", re.IGNORECASE),
]
NAME_PATTERNS = [re.compile(r"^vsc-", re.IGNORECASE)]
DEV_ENV_VAR = "DEVCONTAINER=true"

def run_out(cmd: List[str], *, check: bool = True) -> str:
    """Return stdout (str). If check=False, swallow nonzero but return output."""
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True, check=check)
        return (cp.stdout or "").strip()
    except subprocess.CalledProcessError as e:
        if check:
            sys.stderr.write(e.stderr or e.stdout or "")
            raise
        return (e.stdout or e.stderr or "").strip()
    except FileNotFoundError:
        print(f"Error: binary not found on host: {cmd[0]!r}. Is it installed and in PATH?", file=sys.stderr)
        sys.exit(127)

def run_rc(cmd: List[str]) -> Tuple[int, str, str]:
    """Return (rc, stdout, stderr) for a host command."""
    try:
        cp = subprocess.run(cmd, text=True, capture_output=True)
        return cp.returncode, (cp.stdout or ""), (cp.stderr or "")
    except FileNotFoundError:
        return 127, "", f"binary not found on host: {cmd[0]!r}"

def docker_ps_rows() -> List[Tuple[str, str, str]]:
    fmt = "{{.ID}}||{{.Names}}||{{.Image}}"
    out = run_out(["docker", "ps", "--format", fmt], check=False)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("||", 3)
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows

def docker_inspect(id_: str) -> Dict[str, Any]:
    fmt = '{{json .Config.Labels}}||{{json .Config.Env}}'
    out = run_out(["docker", "inspect", "--format", fmt, id_])
    labels_json, env_json = out.split("||", 1)
    labels = json.loads(labels_json) if labels_json.lower() != "null" else {}
    env = json.loads(env_json) if env_json.lower() != "null" else []
    return {"labels": labels or {}, "env": env or []}

def is_devcontainer(labels: Dict[str, Any], name: str, env: List[str]) -> bool:
    if any(p.search(k) for k in labels for p in DEV_LABEL_KEY_PATTERNS):
        return True
    if any("devcontainer" in str(v).lower() for v in labels.values()):
        return True
    if any(p.search(name) for p in NAME_PATTERNS):
        return True
    if any(e.strip().upper() == DEV_ENV_VAR.upper() for e in env):
        return True
    return False

def list_devcontainers(debug: bool = False) -> List[Dict[str, Any]]:
    devs = []
    for cid, name, image in docker_ps_rows():
        info = docker_inspect(cid)
        if is_devcontainer(info["labels"], name, info["env"]):
            devs.append({"id": cid, "name": name, "image": image, "labels": info["labels"]})
        elif debug:
            print(f"[debug] Skipped {name} ({cid[:12]})", file=sys.stderr)
    return devs

def sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"

def container_supports(cmd: str, container_id: str) -> bool:
    rc, _, _ = run_rc(["docker", "exec", container_id, "sh", "-lc", f"command -v {cmd} >/dev/null 2>&1"])
    return rc == 0

def container_home(container_id: str) -> str:
    home = run_out(["docker", "exec", container_id, "sh", "-lc", "printf %s \"$HOME\""])
    return home or "/root"

def resolve_container_path(container_id: str, path_spec: str) -> str:
    if path_spec.startswith("~"):
        return container_home(container_id) + path_spec[1:]
    return path_spec

def container_file_exists(container_id: str, path: str) -> bool:
    rc, _, _ = run_rc(["docker", "exec", container_id, "sh", "-lc", f"[ -f {sh_quote(path)} ]"])
    return rc == 0

def docker_cp_to(container_id: str, src_host: str, dest_in_container: str) -> None:
    parent = run_out(["docker", "exec", container_id, "sh", "-lc", f"dirname {sh_quote(dest_in_container)}"])
    run_rc(["docker", "exec", container_id, "sh", "-lc", f"mkdir -p {sh_quote(parent)}"])
    rc, out, err = run_rc(["docker", "cp", src_host, f"{container_id}:{dest_in_container}"])
    if rc != 0:
        print(f"[post] docker cp failed (rc={rc}).\n{out}{err}", file=sys.stderr)
        raise SystemExit(rc)

def run_post_script_if_needed(container_id: str, host_script: str, marker_spec: str, force: bool = False, verbose: bool = False):
    host_path = Path(os.path.expanduser(host_script))
    if not host_path.is_file():
        return  # No host script; nothing to do

    marker = resolve_container_path(container_id, marker_spec)
    if not force and container_file_exists(container_id, marker):
        print(f"[post] Already set up ({marker}).")
        return

    shell = "bash" if container_supports("bash", container_id) else "sh"
    dest_script = resolve_container_path(container_id, "~/.dc-postcommand.sh")

    print(f"[post] Copying {host_path} -> {dest_script} ...")
    docker_cp_to(container_id, str(host_path), dest_script)

    cmd = ["docker", "exec", "-i", container_id, shell, "-lc",
           f"chmod +x {sh_quote(dest_script)} && {sh_quote(dest_script)}"]
    if verbose:
        print("[post] exec cmd:", " ".join(sh_quote(c) if " " in c else c for c in cmd))
    print(f"[post] Running post script with {shell} ...")
    rc, out, err = run_rc(cmd)
    if rc != 0:
        print(f"[post] Post script failed (rc={rc}).", file=sys.stderr)
        if out.strip():
            print("[post] stdout:\n" + out.strip(), file=sys.stderr)
        if err.strip():
            print("[post] stderr:\n" + err.strip(), file=sys.stderr)
        return

    run_rc(["docker", "exec", container_id, "sh", "-lc", f": > {sh_quote(marker)}"])
    print(f"[post] Setup complete. Marker: {marker}")

def exec_interactive_shell(container_id: str) -> int:
    shell = "bash" if container_supports("bash", container_id) else "sh"
    return subprocess.call(["docker", "exec", "-it", container_id, shell])

def print_list(devcs: List[Dict[str, Any]]) -> None:
    if not devcs:
        print("No running VS Code devcontainers found.")
        return
    print("Running VS Code devcontainers:")
    for i, c in enumerate(devcs, 1):
        print(f"[{i}] {c['name']}  {c['image']}  {c['id'][:12]}")

def main():
    parser = argparse.ArgumentParser(
        description="Enter VS Code devcontainers; optionally run a one-time post-setup script inside the container."
    )
    parser.add_argument("selection", nargs="?", help="Number of devcontainer to enter.")
    parser.add_argument("--debug", action="store_true", help="Debug detection.")
    parser.add_argument("--verbose", action="store_true", help="Verbose post-step command/outputs.")
    parser.add_argument("--postscript", default="~/dc-postcommand.sh",
                        help="Host setup script path (default: ~/dc-postcommand.sh).")
    parser.add_argument("--marker", default="~/.dc-post-setup-done",
                        help="Marker file inside the container (default: ~/.dc-post-setup-done). '~' resolves to container $HOME.")
    parser.add_argument("--skip-post", action="store_true", help="Skip running post script.")
    parser.add_argument("--force-post", action="store_true", help="Force re-run post script even if marker exists.")
    args = parser.parse_args()

    devcs = list_devcontainers(debug=args.debug)

    if args.selection is None and len(devcs) == 1:
        cid = devcs[0]["id"]
        if not args.skip_post:
            run_post_script_if_needed(cid, args.postscript, args.marker, force=args.force_post, verbose=args.verbose)
        sys.exit(exec_interactive_shell(cid))

    if args.selection is None:
        print_list(devcs)
        return

    if not devcs:
        print("No running VS Code devcontainers found.", file=sys.stderr)
        sys.exit(1)

    try:
        idx = int(args.selection)
    except ValueError:
        print("Selection must be a number.", file=sys.stderr)
        sys.exit(2)

    if idx < 1 or idx > len(devcs):
        print("Selection out of range.", file=sys.stderr)
        sys.exit(3)

    cid = devcs[idx - 1]["id"]
    if not args.skip_post:
        run_post_script_if_needed(cid, args.postscript, args.marker, force=args.force_post, verbose=args.verbose)
    sys.exit(exec_interactive_shell(cid))

if __name__ == "__main__":
    main()

