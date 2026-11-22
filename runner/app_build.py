"""app_build — the runner side of `iphone app`: the Alpha iPhone app source arrives as a job through the desk tunnel,
is built for the booted simulator, installed and launched, and its screen shot. The build log stays in the job's out/
(sent back to the desk only, never printed into the public GitHub log). Writes the same results.json as a spec."""

import io
import os
import subprocess
import tarfile
import time
from pathlib import Path

PROJECT = "alpha_ios/Alpha.xcodeproj"
SCHEME = "Alpha"
BUNDLE_ID = "il.co.alpha"
APP_NAME = "Alpha.app"
BUILD_LIMIT_S = 1500
STEP_LIMIT_S = 120
SETTLE_AFTER_LAUNCH_S = 15
LOG_TAIL_LINES = 60
UNSIGNED_SIMULATOR = ["CODE_SIGN_IDENTITY=-", "CODE_SIGNING_REQUIRED=NO", "CODE_SIGN_STYLE=Manual", "DEVELOPMENT_TEAM="]


def _unpacked(payload: bytes, into: Path) -> Path:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        tar.extractall(into, filter="data")
    return into / PROJECT


def build_command(project: Path, *, job_dir: Path) -> list:
    return ["xcodebuild", "-project", str(project), "-scheme", SCHEME, "-configuration", "Debug",
            "-destination", f"id={os.environ['UDID']}", "-derivedDataPath", str(job_dir / "derived"),
            f"CONFIGURATION_BUILD_DIR={job_dir / 'built'}", *UNSIGNED_SIMULATOR, "build"]


def _step(step: dict, *, log: Path) -> dict:
    started, limit_s = time.monotonic(), step.get("limit_s", STEP_LIMIT_S)
    with log.open("a") as sink:
        sink.write(f"\n$ {' '.join(step['command'])}\n")
        sink.flush()
        try:
            code = subprocess.run(step["command"], stdout=sink, stderr=subprocess.STDOUT, timeout=limit_s).returncode
        except subprocess.TimeoutExpired:
            code = f"timed out after {limit_s}s"
    return {"name": step["name"], "ok": code == 0, "detail": f"exit {code} in {round(time.monotonic() - started)}s"}


def _log_tail(log: Path) -> str:
    return "\n".join(log.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:])


def _simctl(*args) -> list:
    return ["xcrun", "simctl", *args]


def _steps(project: Path, *, job_dir: Path) -> list:
    udid, shot = os.environ["UDID"], job_dir / "out" / "shots" / "01_app_launched.png"
    return [{"name": "app built for the simulator", "command": build_command(project, job_dir=job_dir),
             "limit_s": BUILD_LIMIT_S},
            {"name": "installed", "command": _simctl("install", udid, str(job_dir / "built" / APP_NAME))},
            {"name": "launched", "command": _simctl("launch", udid, BUNDLE_ID)},
            {"name": "screen shot", "command": ["sh", "-c", f"sleep {SETTLE_AFTER_LAUNCH_S} && "
                                                            f"xcrun simctl io {udid} screenshot {shot}"]}]


def built_and_launched(payload: bytes, *, job: dict) -> dict:
    job_dir = Path(job["job_dir"])
    log = job_dir / "out" / "build.log"
    results = {"spec": job["spec_name"], "preflight": {"ok": True}, "expects": [], "shots": [], "error": None}
    for step in _steps(_unpacked(payload, job_dir / "src"), job_dir=job_dir):
        done = _step(step, log=log)
        results["expects"].append(done)
        if not done["ok"]:
            results["error"] = f"{done['name']} failed — last lines of build.log:\n{_log_tail(log)}"
            return results
    results["shots"].append("01_app_launched.png")
    return results
