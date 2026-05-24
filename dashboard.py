#!/usr/bin/env python3
"""
============================================================
  Linux System Health Dashboard
  Author : Tumelo Mareletse
  Module : ITLSA1-T22 — Linux-based Operating System
           Eduvos | BSc IT: Software Engineering
  GitHub : github.com/tumelomareletse/linux-health-dashboard
============================================================
  Description:
    A command-line tool that inspects the current state of
    a Linux system and prints a formatted health report
    covering CPU, memory, disk, uptime, top processes,
    and network interfaces.

  Usage:
    python3 dashboard.py           # print to terminal
    python3 dashboard.py --save    # also save report to file
    python3 dashboard.py --watch   # refresh every 5 seconds
============================================================
"""

import os
import sys
import time
import datetime
import platform
import subprocess
import argparse


# ── helpers ──────────────────────────────────────────────

def separator(char="─", width=54):
    return "  " + char * width

def progress_bar(pct, width=24):
    """Return a unicode progress bar string for a percentage."""
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:.1f}%"

def status_label(pct, warn=75, critical=90):
    """Return a coloured status string based on thresholds."""
    if pct >= critical:
        return "⚠  CRITICAL"
    elif pct >= warn:
        return "~  WARNING"
    else:
        return "✓  OK"


# ── data collectors ───────────────────────────────────────

def get_cpu_usage():
    """
    Read two snapshots of /proc/stat 0.25 s apart and
    calculate the CPU usage percentage from the delta.
    /proc/stat columns: user nice system idle iowait irq softirq ...
    """
    def read_stat():
        with open("/proc/stat") as f:
            line = f.readline()
        values = list(map(int, line.split()[1:]))
        idle  = values[3] + values[4]   # idle + iowait
        total = sum(values)
        return idle, total

    try:
        idle1, total1 = read_stat()
        time.sleep(0.25)
        idle2, total2 = read_stat()
        delta_idle  = idle2  - idle1
        delta_total = total2 - total1
        usage = 100.0 * (1 - delta_idle / delta_total)
        return round(usage, 1)
    except Exception:
        return None


def get_memory():
    """
    Parse /proc/meminfo for total and available memory.
    Returns (total_mb, used_mb, used_pct) or (None, None, None).
    """
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":")[0], line.split()[1]
                mem[key] = int(val)
        total_mb     = mem["MemTotal"]     // 1024
        available_mb = mem["MemAvailable"] // 1024
        used_mb      = total_mb - available_mb
        used_pct     = 100.0 * used_mb / total_mb
        return total_mb, used_mb, round(used_pct, 1)
    except Exception:
        return None, None, None


def get_swap():
    """
    Parse /proc/meminfo for swap usage.
    Returns (total_mb, used_mb, used_pct) or (None, None, None).
    """
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":")[0], line.split()[1]
                mem[key] = int(val)
        total_mb = mem.get("SwapTotal", 0) // 1024
        free_mb  = mem.get("SwapFree",  0) // 1024
        if total_mb == 0:
            return 0, 0, 0.0
        used_mb  = total_mb - free_mb
        used_pct = 100.0 * used_mb / total_mb
        return total_mb, used_mb, round(used_pct, 1)
    except Exception:
        return None, None, None


def get_disk(path="/"):
    """
    Use os.statvfs to get disk usage for a given mount point.
    Returns (total_gb, used_gb, used_pct).
    """
    try:
        st       = os.statvfs(path)
        total    = st.f_blocks * st.f_frsize
        free     = st.f_bfree  * st.f_frsize
        used     = total - free
        used_pct = 100.0 * used / total
        return (
            round(total / 1024**3, 1),
            round(used  / 1024**3, 1),
            round(used_pct, 1)
        )
    except Exception:
        return None, None, None


def get_uptime():
    """
    Read uptime in seconds from /proc/uptime and convert
    to a human-readable days/hours/minutes string.
    """
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        days  = int(secs // 86400)
        hours = int((secs % 86400) // 3600)
        mins  = int((secs % 3600)  // 60)
        return f"{days}d {hours}h {mins}m"
    except Exception:
        return "Unknown"


def get_load_average():
    """
    Read 1/5/15-minute load averages from /proc/loadavg.
    """
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        return parts[0], parts[1], parts[2]
    except Exception:
        return "?", "?", "?"


def get_top_processes(n=5):
    """
    Call `ps aux --sort=-%cpu` and return the top n rows
    as a list of dicts: {user, pid, cpu, mem, command}.
    """
    try:
        result = subprocess.run(
            ["ps", "aux", "--sort=-%cpu"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().splitlines()
        procs = []
        for line in lines[1 : n + 1]:      # skip header
            p = line.split(None, 10)
            if len(p) >= 11:
                procs.append({
                    "user":    p[0][:12],
                    "pid":     p[1],
                    "cpu":     p[2],
                    "mem":     p[3],
                    "command": p[10][:30]
                })
        return procs
    except Exception:
        return []


def get_network_interfaces():
    """
    Use `ip -br addr` to list interfaces with their state
    and IP addresses. Falls back to `ifconfig` if needed.
    """
    try:
        result = subprocess.run(
            ["ip", "-br", "addr"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["ifconfig", "-a"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip().splitlines()[:20]
    except Exception:
        return ["  Network info unavailable"]


# ── report renderer ───────────────────────────────────────

def build_report():
    """Collect all metrics and return the full report as a string."""
    lines = []
    now      = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    hostname = platform.node()
    os_name  = f"{platform.system()} {platform.release()}"
    arch     = platform.machine()
    python_v = platform.python_version()

    def add(text=""):
        lines.append(text)

    # ── header ────────────────────────────────────────────
    add(separator("═"))
    add("   🖥   LINUX SYSTEM HEALTH DASHBOARD")
    add(f"   {now}   │   {hostname}")
    add(separator("═"))

    # ── system info ───────────────────────────────────────
    add()
    add("  ─── SYSTEM INFO " + "─" * 37)
    add(f"  OS       :  {os_name}")
    add(f"  Arch     :  {arch}")
    add(f"  Uptime   :  {get_uptime()}")
    add(f"  Python   :  {python_v}")
    load1, load5, load15 = get_load_average()
    add(f"  Load avg :  {load1}  (1m)   {load5}  (5m)   {load15}  (15m)")

    # ── cpu ───────────────────────────────────────────────
    add()
    add("  ─── CPU " + "─" * 46)
    cpu = get_cpu_usage()
    if cpu is not None:
        add(f"  Usage    :  {progress_bar(cpu)}")
        add(f"  Status   :  {status_label(cpu)}")
    else:
        add("  Could not read CPU data  (requires /proc/stat)")

    # ── memory ────────────────────────────────────────────
    add()
    add("  ─── MEMORY (RAM) " + "─" * 36)
    total_mb, used_mb, mem_pct = get_memory()
    if total_mb is not None:
        add(f"  Usage    :  {progress_bar(mem_pct)}")
        add(f"  Used     :  {used_mb:,} MB  /  {total_mb:,} MB")
        add(f"  Status   :  {status_label(mem_pct)}")
    else:
        add("  Could not read memory data")

    # ── swap ──────────────────────────────────────────────
    swap_total, swap_used, swap_pct = get_swap()
    if swap_total is not None and swap_total > 0:
        add()
        add("  ─── SWAP " + "─" * 45)
        add(f"  Usage    :  {progress_bar(swap_pct)}")
        add(f"  Used     :  {swap_used:,} MB  /  {swap_total:,} MB")
        add(f"  Status   :  {status_label(swap_pct)}")

    # ── disk ──────────────────────────────────────────────
    add()
    add("  ─── DISK  [ / ] " + "─" * 37)
    total_gb, used_gb, disk_pct = get_disk("/")
    if total_gb is not None:
        add(f"  Usage    :  {progress_bar(disk_pct)}")
        add(f"  Used     :  {used_gb} GB  /  {total_gb} GB")
        add(f"  Status   :  {status_label(disk_pct, warn=70, critical=85)}")
    else:
        add("  Could not read disk data")

    # ── top processes ─────────────────────────────────────
    add()
    add("  ─── TOP 5 PROCESSES  (by CPU%) " + "─" * 22)
    procs = get_top_processes(5)
    if procs:
        add(f"  {'COMMAND':<31} {'CPU%':>5}  {'MEM%':>5}  {'PID':>7}  USER")
        add("  " + "─" * 52)
        for p in procs:
            add(f"  {p['command']:<31} {p['cpu']:>5}  {p['mem']:>5}  {p['pid']:>7}  {p['user']}")
    else:
        add("  Could not retrieve process list")

    # ── network interfaces ────────────────────────────────
    add()
    add("  ─── NETWORK INTERFACES " + "─" * 30)
    for iface in get_network_interfaces():
        add(f"  {iface}")

    # ── footer ────────────────────────────────────────────
    add()
    add(separator("═"))
    add(f"   Report generated  {now}")
    add(f"   Script: dashboard.py  │  github.com/YOUR_USERNAME/linux-health-dashboard")
    add(separator("═"))

    return "\n".join(lines)


# ── entry point ───────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Linux System Health Dashboard"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the report to a timestamped .txt file"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Refresh the dashboard every 5 seconds (Ctrl+C to stop)"
    )
    args = parser.parse_args()

    if platform.system() != "Linux":
        print("⚠  This script targets Linux systems.")
        print("   Run it inside your VirtualBox Ubuntu VM.")
        sys.exit(1)

    if args.watch:
        try:
            while True:
                os.system("clear")
                report = build_report()
                print(report)
                print("\n  [watching — press Ctrl+C to exit]")
                time.sleep(5)
        except KeyboardInterrupt:
            print("\n  Dashboard stopped.")
    else:
        report = build_report()
        print(report)

        if args.save:
            ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"health_report_{ts}.txt"
            with open(filename, "w") as f:
                f.write(report)
            print(f"\n  ✓  Report saved to  {filename}")


if __name__ == "__main__":
    main()
