#!/usr/bin/env python3
"""ai-leverage/src/python/hardware.py

What this PC has for running models: its NVIDIA GPUs (memory, generation,
driver), RAM, CPU threads, and the free disk where models/ is. It reads them
on this PC, without going online and without sudo.

Usage: python3 -I hardware.py [--json]
  A short summary, or the same as JSON with --json.

model_fit.py uses it as a module. Sizes are in bytes. The summary counts the
way manage.sh's status lines do, so 1 GB is 1024 MB.
"""

import json
import os
import re
import shutil
import subprocess
import sys

GiB = 1024 ** 3
MiB = 1024 ** 2

# What each NVIDIA generation runs natively, by compute capability, newest
# first. FP4 (NVFP4, MXFP4) needs Blackwell, FP8 needs Ada or newer, and BF16
# needs Ampere or newer. Older cards still run 4-bit AWQ/GPTQ and GGUF files,
# and an engine may load an FP4 or FP8 file on them through a slower fallback,
# depending on the engine and its version.
GENERATIONS = [
    (12.0, "Blackwell (RTX 50)", {"fp4", "fp8", "bf16", "int4"}),
    (10.0, "Blackwell (data center)", {"fp4", "fp8", "bf16", "int4"}),
    (9.0, "Hopper", {"fp8", "bf16", "int4"}),
    (8.9, "Ada (RTX 40)", {"fp8", "bf16", "int4"}),
    (8.0, "Ampere (RTX 30)", {"bf16", "int4"}),
    (7.5, "Turing (RTX 20)", {"int4"}),
    (0.0, "older than Turing", set()),
]


def generation(compute_cap):
    """(name, the formats it runs natively) for a compute capability"""
    for cap, name, native in GENERATIONS:
        if compute_cap >= cap:
            return name, native
    return GENERATIONS[-1][1], set()


def run(*command):
    """A command's output, or "" when it's missing, fails or hangs"""
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# How the engines' processes name themselves on the GPU: vLLM's and SGLang's
# workers rename themselves (VLLM::EngineCore, sglang::scheduler), llama.cpp
# runs llama-server, and Ollama an "ollama runner" per model
ENGINE_PROCESSES = ("vllm", "sglang", "llama-server", "ollama")


def is_engine(pid):
    """True when a process on the GPU is one of the stack's engines"""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            command = f.read().replace(b"\0", b" ").decode(errors="replace").lower()
    except OSError:
        return False
    return any(name in command for name in ENGINE_PROCESSES)


def gpus():
    """One dict per NVIDIA GPU, or [] when there is none or its driver doesn't
    answer. "others" is the memory everything but the engines uses: the
    desktop, other programs and the stack's services, such as Docling. An
    engine has to share the GPU with them, while engines take turns, so one
    that runs now counts as stopped."""
    out = run("nvidia-smi", "--format=csv,noheader,nounits",
              "--query-gpu=index,uuid,name,memory.total,memory.used,compute_cap,driver_version")
    found = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 7:
            continue
        index, uuid, name, total, used, cap, driver = parts
        try:
            found.append({
                "index": int(index), "uuid": uuid, "name": name,
                "total": int(float(total)) * MiB, "used": int(float(used)) * MiB,
                "compute_cap": float(cap), "driver": driver,
            })
        except ValueError:
            continue
    if not found:
        return []

    # Memory per GPU that engines use
    engines = {}
    apps = run("nvidia-smi", "--format=csv,noheader,nounits",
               "--query-compute-apps=gpu_uuid,pid,used_memory")
    for line in apps.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit() and is_engine(parts[1]):
            try:
                engines[parts[0]] = engines.get(parts[0], 0) + int(float(parts[2])) * MiB
            except ValueError:
                pass

    cuda = re.search(r"CUDA Version:\s*([0-9.]+)", run("nvidia-smi"))
    for gpu in found:
        gpu["engines"] = engines.get(gpu["uuid"], 0)
        gpu["others"] = max(0, gpu["used"] - gpu["engines"])
        gpu["cuda"] = cuda[1] if cuda else ""
        gpu["generation"], native = generation(gpu["compute_cap"])
        gpu["native"] = sorted(native)
        # Not needed by anything, and better not shown around
        del gpu["uuid"]
    return found


def ram():
    """(total, available) in bytes, as free counts them"""
    values = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return values.get("MemTotal", 0), values.get("MemAvailable", 0)


def disk_free(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def models_folder():
    """The repo's models/ folder, or the repo itself before the first download"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    models = os.path.join(base, "models")
    return os.path.realpath(models) if os.path.exists(models) else base


def detect():
    total, available = ram()
    return {
        "gpus": gpus(),
        "ram_total": total,
        "ram_available": available,
        "cpu_threads": os.cpu_count() or 0,
        "disk_free": disk_free(models_folder()),
    }


def gb(size):
    """Bytes in, "31.8 GB" or "4.7 TB" out (1 GB = 1024 MB, as in manage.sh)"""
    if size >= 1024 * GiB:
        return f"{size / 1024 / GiB:.1f} TB"
    return f"{size / GiB:.1f} GB"


def native_text(native):
    if "fp4" in native:
        return "runs FP4 and FP8 files natively"
    if "fp8" in native:
        return "runs FP8 files natively, FP4 ones not"
    return "runs neither FP4 nor FP8 files natively"


def summary(found):
    lines = []
    if not found["gpus"]:
        lines.append("GPU    no NVIDIA GPU found. The stack's engines need one, except Ollama and")
        lines.append("       llama.cpp, which would run on the CPU, slowly. They're set up for NVIDIA.")
    for gpu in found["gpus"]:
        prefix = f"GPU {gpu['index']}  " if len(found["gpus"]) > 1 else "GPU    "
        lines.append(f"{prefix}{gpu['name']} · {gb(gpu['total'])} · {gpu['generation']}: "
                     f"{native_text(set(gpu['native']))}")
        detail = f"driver {gpu['driver']}"
        if gpu["cuda"]:
            detail += f" · CUDA {gpu['cuda']}"
        detail += f" · {gb(gpu['others'])} in use besides the engines"
        lines.append("       " + detail)
    lines.append(f"RAM    {gb(found['ram_total'])} · {gb(found['ram_available'])} free")
    lines.append(f"CPU    {found['cpu_threads']} threads")
    lines.append(f"Disk   {gb(found['disk_free'])} free where models/ is")
    return lines


def main():
    found = detect()
    if sys.argv[1:] == ["--json"]:
        print(json.dumps(found, indent=2))
    elif sys.argv[1:]:
        print(__doc__.split("\n\n")[2], file=sys.stderr)
        sys.exit(1)
    else:
        print("\n".join(summary(found)))


if __name__ == "__main__":
    main()
