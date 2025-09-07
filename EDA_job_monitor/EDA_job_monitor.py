import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

UTC = dt.timezone.utc

def which_runtime() -> str:
    for rt in ("docker", "podman"):
        if shutil.which(rt):
            return rt
    print("ERROR: neither docker nor podman found in PATH", file=sys.stderr)
    sys.exit(2)

def run(cmd: List[str]) -> Tuple[int, str, str]:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err

def parse_time(s: Optional[str]) -> Optional[dt.datetime]:
    """Parse Docker/Podman RFC3339Nano like '2025-07-01T01:01:00.123456789Z' or '2025-07-01T01:01:00Z'."""
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
        tz = UTC
    else:
        tz = None
    # cut off subseconds if present (handle 9 ns digits, etc.)
    if "." in s:
        s = s.split(".", 1)[0]
    try:
        dt_obj = dt.datetime.fromisoformat(s)
        if tz is not None:
            dt_obj = dt_obj.replace(tzinfo=tz)
        elif dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=UTC)
        return dt_obj.astimezone(UTC)
    except Exception:
        return None

def now_utc() -> dt.datetime:
    return dt.datetime.now(tz=UTC)

def list_containers(runtime: str) -> List[Dict]:
    """
    Returns a list of container summary dicts using --format '{{json .}}'
    Fields include: ID, Names/Name, Image, CreatedAt, RunningFor, Status, ...
    """
    # Docker uses .Names, Podman uses .Names or .Names? Both accept json . (with Name/Names).
    code, out, err = run([runtime, "ps", "-a", "--format", "{{json .}}"])
    if code != 0:
        print(f"ERROR: failed to list containers with {runtime}: {err.strip()}", file=sys.stderr)
        sys.exit(3)
    containers = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            # ignore unparsable lines
            continue
    return containers

def inspect_container(runtime: str, cid: str) -> Dict:
    code, out, err = run([runtime, "inspect", cid])
    if code != 0:
        return {}
    try:
        data = json.loads(out)
        return data[0] if isinstance(data, list) and data else {}
    except json.JSONDecodeError:
        return {}

def container_last_event_ts(info: Dict) -> Optional[dt.datetime]:
    """
    Determine the most relevant timestamp for 'last seen/executed':
    prefer State.FinishedAt if valid; else State.StartedAt; else Created.
    """
    state = info.get("State", {}) or {}
    finished = parse_time(state.get("FinishedAt"))
    started = parse_time(state.get("StartedAt"))
    created = parse_time(info.get("Created"))
    candidates = [t for t in (finished, started, created) if t is not None]
    if not candidates:
        return None
    return max(candidates)

def get_ansible_version() -> Optional[str]:
    # Try to run `ansible --version` locally (host). Fall back to env ANSIBLE_VERSION.
    ansible_bin = shutil.which("ansible")
    if ansible_bin:
        code, out, err = run([ansible_bin, "--version"])
        if code == 0 and out:
            first_line = out.splitlines()[0]
            # Expected: "ansible [core 2.15.0]" or "ansible 2.15.0"
            for token in first_line.replace("[", " ").replace("]", " ").split():
                if token[0].isdigit():
                    return token
    return os.environ.get("ANSIBLE_VERSION")

def get_ansible_user() -> str:
    # Priority: env ANSIBLE_USER, else current OS user
    return os.environ.get("ANSIBLE_USER") or os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"

def main():
    parser = argparse.ArgumentParser(
        description="Monitor EDA Ansible job containers and report last execution health."
    )
    parser.add_argument("--prefix", default="ansible", help="Container name prefix to filter (default: ansible-job-)")
    parser.add_argument("--hours", type=float, default=24.0, help="Look-back window in hours (default: 24)")
    parser.add_argument("--runtime", choices=["auto", "docker", "podman"], default="auto", help="Container runtime (default: auto)")
    parser.add_argument("--host", default=socket.gethostname(), help="Host name override")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    runtime = which_runtime() if args.runtime == "auto" else args.runtime
    containers = list_containers(runtime)

    # Filter by prefix against .Names (docker) or .Names/.Name (podman format variants)
    target = []
    for c in containers:
        name = c.get("Names") or c.get("Name") or ""
        # Some runtimes may return a list of names; normalize.
        if isinstance(name, list):
            name = name[0] if name else ""
        if isinstance(name, str) and name.startswith(args.prefix):
            target.append((name, c.get("ID") or c.get("Id") or ""))

    jobs: Dict[str, str] = {}
    unhealthy = False
    window = dt.timedelta(hours=args.hours)
    now = now_utc()

    for name, cid in target:
        info = inspect_container(runtime, cid)
        last_ts = container_last_event_ts(info)
        if not last_ts:
            # no timestamps available — mark as unseen
            jobs[name] = "last_seen: unknown"
            unhealthy = True
            continue

        if (now - last_ts) <= window:
            jobs[name] = f"executed_at: {last_ts.replace(tzinfo=UTC).isoformat().replace('+00:00', 'Z')}"
        else:
            jobs[name] = f"last_seen: {last_ts.replace(tzinfo=UTC).isoformat().replace('+00:00', 'Z')}"
            unhealthy = True

    # If no jobs matched, decide status: usually that's unhealthy for monitoring;
    # change here to your preference. We'll mark healthy with empty set.
    status = "healthy" if not unhealthy else "unhealthy"

    payload = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "host": args.host,
        "ansible_version": get_ansible_version() or "unknown",
        "ansible_user": get_ansible_user(),
        "message": {
            "status": status,
            "jobs": jobs or {}
        }
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))

if __name__ == "__main__":
    main()