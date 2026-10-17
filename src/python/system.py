#!/usr/bin/env python3
"""ai-leverage/src/python/system.py

What the PC has to spare right now, for the top of manage.sh's menu: free
space on the disk models/ is on, free RAM and swap in use, and each GPU's
load, memory, power and temperature. Sizes count the way df -h and free -h
do, so 1 GB is 1024 MB, like the rest of the menus. It needs no sudo and
goes nowhere online.

Usage: python3 -I system.py
  Prints the readings once.
"""

import os
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS_DIR = os.path.join(BASE_DIR, "models")
GiB = 1024 ** 3
MiB = 1024 ** 2


def human(size):
    """Bytes as "4.8 TB", "66 GB", "7.5 GB", "512 MB" or "40 KB" """
    if size >= 1024 ** 4:
        return f"{size / 1024 ** 4:.1f} TB"
    if size >= 10 * GiB:
        return f"{size / GiB:.0f} GB"
    if size >= GiB:
        return f"{size / GiB:.1f} GB"
    if size >= MiB:
        return f"{size / MiB:.0f} MB"
    return f"{size / 1024:.0f} KB"


def models_path():
    """The folder the models are in, or the repo before the first download. A
    link to another disk is followed, so the numbers are for that disk."""
    return os.path.realpath(MODELS_DIR) if os.path.exists(MODELS_DIR) else BASE_DIR


def disk():
    """(free, total) bytes on the disk the models are on, or None"""
    try:
        st = os.statvfs(models_path())
    except OSError:
        return None
    return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize


def disk_level(free):
    """0 fine, 1 yellow under 200 GB free, 2 red under 50 GB"""
    return 2 if free < 50 * GiB else 1 if free < 200 * GiB else 0


def models_size():
    """Bytes everything in models/ takes, or None"""
    if not os.path.exists(MODELS_DIR):
        return None
    try:
        out = subprocess.run(["du", "-sb", models_path()], capture_output=True, text=True,
                             timeout=20, stdin=subprocess.DEVNULL).stdout
        return int(out.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def memory():
    """(total, available, swap in use) bytes of RAM, as free counts them"""
    values = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return (values.get("MemTotal", 0), values.get("MemAvailable", 0),
            values.get("SwapTotal", 0) - values.get("SwapFree", 0))


def ram_level(available):
    """0 fine, 1 yellow under 8 GB free, 2 red under 3 GB"""
    return 2 if available < 3 * GiB else 1 if available < 8 * GiB else 0


SWAP_WARNING = GiB  # swap in use above this is a sign RAM ran out


def number(text):
    try:
        return float(text)
    except ValueError:
        return None


def gpus():
    """Each NVIDIA GPU as a dict: index, name, load (%), used and total
    (bytes), watts, limit (W), temp (°C), fan (%); a value the driver doesn't
    give is None. None when there's no nvidia-smi, [] when the driver
    doesn't answer."""
    if not shutil.which("nvidia-smi"):
        return None
    query = "index,name,utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu,fan.speed"
    try:
        out = subprocess.run(["nvidia-smi", "--format=csv,noheader,nounits", f"--query-gpu={query}"],
                             capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 9:
            continue
        index, name, load, used, total, watts, limit, temp, fan = parts
        used, total = number(used), number(total)
        found.append({
            "index": index, "name": name, "load": number(load),
            "used": used * MiB if used is not None else None,
            "total": total * MiB if total is not None else None,
            "watts": number(watts), "limit": number(limit), "temp": number(temp), "fan": number(fan),
        })
    return found


def temp_level(temp):
    """0 fine, 1 yellow from 80°C, 2 red from 90°C, where the card starts
    slowing itself down"""
    if temp is None:
        return 0
    return 2 if temp >= 90 else 1 if temp >= 80 else 0


def main():
    found = disk()
    if found:
        size = models_size()
        print(f"Disk  {human(found[0])} free / {human(found[1])}" + (f" · models use {human(size)}" if size else ""))
    found = memory()
    if found:
        print(f"RAM   {human(found[1])} free / {human(found[0])}"
              + (f" · {human(found[2])} swapped" if found[2] > SWAP_WARNING else ""))
    found = gpus()
    if found is None:
        print("GPU   no NVIDIA GPU found (nvidia-smi is missing)")
    for gpu in found or []:
        print(f"GPU {gpu['index']} {gpu['name']}: {gpu['load']:.0f}% busy · VRAM {gpu['used'] / GiB:.1f} GB used"
              f" / {gpu['total'] / GiB:.1f} GB · {gpu['watts']:.0f} W · {gpu['temp']:.0f}°C")


if __name__ == "__main__":
    main()
