#!/usr/bin/env python3
"""Prepare/apply one reviewed FPC exporter relay and Prometheus observation.

Run on deployment as root. No credentials are read or printed; all private
preimages stay in the root-only state directory. Existing host targets, users,
SSH settings and history are preserved. No application container is recreated.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile

import yaml

USER = "monitoring-fpc"
USER_HOME = Path("/var/lib/rabbit-fpc-metrics")
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFDuH2ck08Weax2uvggFF6M5vy5naWYkPIDihtZYECP9 rabbit-fpc-monitoring"
PROMETHEUS = Path("/etc/rabbit-monitoring/prometheus/prometheus.yml")
TARGETS = Path("/etc/rabbit-monitoring/prometheus/file_sd/windows_targets.yml")
SSH_FRAGMENT = Path("/etc/ssh/sshd_config.d/62-home-fpc.conf")
DASHBOARD = Path("/etc/rabbit-monitoring/grafana/provisioning/dashboards/managed-windows-host.json")
SSH_TEXT = """# Rabbit home FPC metrics: outbound exporter relay, no sessions.
Match User monitoring-fpc
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTTY no
    AllowTcpForwarding remote
    GatewayPorts clientspecified
    PermitOpen none
    PermitListen 172.23.0.1:19132
    MaxSessions 0
    ForceCommand /usr/sbin/nologin
Match all
"""
AUTHORIZED_KEY = 'restrict,port-forwarding,permitlisten="172.23.0.1:19132",permitopen="none",command="/usr/sbin/nologin" ' + KEY + "\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("expected ordinary file: " + str(path))
    return path.read_bytes()


def command(argv, input=None):
    result = subprocess.run(argv, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError("bounded command failed: " + " ".join(argv[:3]))
    return result.stdout


def candidates(prom_raw, targets_raw, dashboard_raw):
    prom = yaml.safe_load(prom_raw)
    targets = yaml.safe_load(targets_raw)
    dashboard = json.loads(dashboard_raw)
    if dashboard.get("uid") != "managed-windows-host" or not isinstance(targets, list):
        raise RuntimeError("candidate dashboard or target shape differs")
    jobs = [j for j in prom.get("scrape_configs", []) if j.get("job_name") == "windows_exporter_clients"]
    if len(jobs) != 1:
        raise RuntimeError("exact existing Windows scrape job required")
    job = jobs[0]
    paths = [p for group in job.get("file_sd_configs", []) for p in group.get("files", [])]
    if "/etc/prometheus/file_sd/windows_targets.yml" not in paths:
        raise RuntimeError("Windows target mount differs")
    if any(g.get("labels", {}).get("alias") == "fpc" for g in targets):
        raise RuntimeError("FPC target already exists; inspect the previous enrollment")
    rules = job.setdefault("relabel_configs", [])
    if not rules or rules[0] != {"source_labels": ["__address__"], "target_label": "instance"}:
        raise RuntimeError("expected existing scrape identity preservation rule")
    if any("19132" in str(r) or "windows-exporter-fpc" in str(r) for r in rules):
        raise RuntimeError("FPC transport already exists")
    rules.append({"source_labels": ["__address__"], "regex": r"windows\-exporter\-fpc:9182", "target_label": "__address__", "replacement": "172.23.0.1:19132"})
    targets.append({"targets": ["windows-exporter-fpc:9182"], "labels": {"alias": "fpc", "company": "my own", "role": "development"}})
    return {
        str(PROMETHEUS): yaml.safe_dump(prom, sort_keys=False).encode(),
        str(TARGETS): yaml.safe_dump(targets, sort_keys=False).encode(),
        str(SSH_FRAGMENT): SSH_TEXT.encode(),
        str(DASHBOARD): dashboard_raw,
    }


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def prepare(args):
    state = args.state
    if state.exists():
        raise RuntimeError("state directory already exists; inspect it instead of replacing preimages")
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        raise RuntimeError("destination identity already exists")
    if USER_HOME.exists() or SSH_FRAGMENT.exists() or DASHBOARD.exists():
        raise RuntimeError("one of the FPC destination paths already exists")
    files = candidates(regular(PROMETHEUS), regular(TARGETS), regular(args.dashboard))
    command(["/usr/sbin/sshd", "-t"])
    command(["docker", "exec", "-i", args.prometheus_container, "promtool", "check", "config", "/dev/stdin"], files[str(PROMETHEUS)])
    state.mkdir(mode=0o700, parents=False)
    records = []
    for index, (path_text, data) in enumerate(files.items()):
        path = Path(path_text)
        old = regular(path) if path.exists() else None
        if old is not None:
            write_private(state / f"{index}.before", old)
        write_private(state / f"{index}.candidate", data)
        records.append({"path": path_text, "before_sha256": digest(old) if old is not None else None,
                        "candidate_sha256": digest(data), "index": index,
                        "mode": path.stat().st_mode & 0o777 if old is not None else 0o644,
                        "uid": path.stat().st_uid if old is not None else 0,
                        "gid": path.stat().st_gid if old is not None else 0})
    plan = {"version": 1, "user": USER, "public_key_sha256": digest(KEY.encode()),
            "prometheus_container": args.prometheus_container, "files": records,
            "scope": "one private FPC exporter relay; Windows target; admin dashboard; no application restart"}
    raw = (json.dumps(plan, sort_keys=True, indent=2) + "\n").encode()
    write_private(state / "plan.json", raw)
    # Validate the candidate SSH fragment without installing it into live Include.
    config = regular(Path("/etc/ssh/sshd_config")) + f"\nMatch all\nInclude {state / '2.candidate'}\n".encode()
    write_private(state / "sshd-candidate.conf", config)
    command(["/usr/sbin/sshd", "-t", "-f", str(state / "sshd-candidate.conf")])
    print(json.dumps({"phase": "prepared", "plan_sha256": digest(raw), "files": [r["path"] for r in records], "private_preimages": str(state)}))


def atomic_replace(path, data, mode, uid, gid):
    fd, tmp = tempfile.mkstemp(prefix=".home-fpc-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply(args):
    state = args.state
    raw = regular(state / "plan.json")
    if not args.plan_sha256 or digest(raw) != args.plan_sha256:
        raise RuntimeError("exact reviewed plan SHA256 required")
    plan = json.loads(raw)
    if (state / "apply-started.json").exists():
        raise RuntimeError("apply already started; reconcile its receipt before any retry")
    if plan["public_key_sha256"] != digest(KEY.encode()) or plan["user"] != USER:
        raise RuntimeError("plan identity differs")
    for record in plan["files"]:
        path = Path(record["path"])
        old = regular(path) if path.exists() else None
        if (digest(old) if old is not None else None) != record["before_sha256"]:
            raise RuntimeError("live preimage drift: " + str(path))
        if digest(regular(state / f"{record['index']}.candidate")) != record["candidate_sha256"]:
            raise RuntimeError("prepared candidate drift")
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        raise RuntimeError("destination identity changed after prepare")
    if USER_HOME.exists():
        raise RuntimeError("destination home changed after prepare")
    command(["/usr/sbin/sshd", "-t", "-f", str(state / "sshd-candidate.conf")])
    command(["docker", "exec", "-i", plan["prometheus_container"], "promtool", "check", "config", "/dev/stdin"], regular(state / "0.candidate"))
    write_private(state / "apply-started.json", json.dumps({"plan_sha256": args.plan_sha256}).encode())
    command(["useradd", "--system", "--user-group", "--home-dir", str(USER_HOME), "--create-home", "--shell", "/usr/sbin/nologin", USER])
    identity = pwd.getpwnam(USER)
    os.chmod(USER_HOME, 0o700)
    keydir = USER_HOME / ".ssh"
    keydir.mkdir(mode=0o700)
    os.chown(keydir, identity.pw_uid, identity.pw_gid)
    write_private(keydir / "authorized_keys", AUTHORIZED_KEY.encode())
    os.chown(keydir / "authorized_keys", identity.pw_uid, identity.pw_gid)
    changed = []
    try:
        for record in plan["files"]:
            path = Path(record["path"])
            atomic_replace(path, regular(state / f"{record['index']}.candidate"), record["mode"], record["uid"], record["gid"])
            changed.append(record)
        command(["/usr/sbin/sshd", "-t"])
        command(["docker", "exec", plan["prometheus_container"], "promtool", "check", "config", "/etc/prometheus/prometheus.yml"])
        command(["systemctl", "reload", "ssh"])
        command(["docker", "kill", "--signal=HUP", plan["prometheus_container"]])
    except Exception:
        # Restore only exact candidates written by this invocation. A changed
        # file is deliberately left for operator reconciliation, never clobbered.
        for record in reversed(changed):
            path = Path(record["path"])
            if digest(regular(path)) != record["candidate_sha256"]:
                continue
            if record["before_sha256"] is None:
                path.unlink()
            else:
                atomic_replace(path, regular(state / f"{record['index']}.before"), record["mode"], record["uid"], record["gid"])
        # Disable only this new key. Preserve the inert user and private receipts.
        atomic_replace(keydir / "authorized_keys", b"", 0o600, identity.pw_uid, identity.pw_gid)
        command(["/usr/sbin/sshd", "-t"])
        command(["systemctl", "reload", "ssh"])
        raise
    receipt = {"phase": "applied", "plan_sha256": args.plan_sha256, "user": USER,
               "listener": "172.23.0.1:19132", "exporter_status": "awaiting_source_relay", "history_deleted": False}
    write_private(state / "receipt.json", (json.dumps(receipt, sort_keys=True) + "\n").encode())
    print(json.dumps(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "apply"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dashboard", type=Path)
    parser.add_argument("--prometheus-container")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if os.geteuid() != 0 or not args.state.is_absolute() or args.state.is_symlink():
        raise RuntimeError("root and a private absolute non-symlink state directory required")
    if args.phase == "prepare":
        if not args.dashboard or not args.prometheus_container:
            parser.error("prepare needs exact dashboard source and existing Prometheus container")
        prepare(args)
    else:
        apply(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Deliberately exclude subprocess output / private config contents.
        print("FPC monitoring enrollment stopped: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
