#!/usr/bin/env python3
"""ai-leverage/src/python/stack.py

What's in the stack and how each part of it is doing, for manage.sh's menu:
the groups in stack/ and their folders, the desktop apps in apps/, and for
each one its status, version, addresses and what the last update check
found. Everything comes from the folders themselves (compose files and their
labels, scripts, READMEs, app.conf), so a new folder shows up on its own.

Nothing here goes online. Docker's state needs sudo, and sudo -n never asks
for the password: manage.sh asks for it before the menu opens. Whether an
engine or service is ready is asked of the engine itself, at the address its
ai-leverage.ready label names on this PC, which needs no sudo. Versions come
from service.sh and app.sh, the scripts that also update them, and the update
hints from what the last update check left in cache/updates.

Usage: python3 -I stack.py
  Prints what it finds, to check it without the menu.
"""

import calendar
import http.client
import os
import re
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STACK_DIR = os.path.join(BASE_DIR, "stack")
APPS_DIR = os.path.join(BASE_DIR, "apps")
SCRIPT_DIR = os.path.join(BASE_DIR, "src", "bash")
UPDATE_CACHE_DIR = os.path.join(BASE_DIR, "cache", "updates")

# The groups in stack/, in menu order, each with the line shown next to its
# heading. A folder in stack/ that isn't listed here still shows up, after these.
STACK_GROUPS = [
    ("downloaders", "get models onto this PC"),
    ("engines", "run the models"),
    ("services", "what you use"),
]
APPS_ABOUT = "programs on this PC, outside Docker"

# Between the fields of docker ps's lines: a character no label holds
SEP = "\x1f"


def run(command, timeout=60):
    """A command's output and whether it worked. It never reads the keyboard,
    so a script that would ask for something fails instead of waiting."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return "", False
    return done.stdout, done.returncode == 0


def show_version(version):
    """A version as the menus show it: a number gets a v (v2.1.287), anything
    else stays as it is (b11580, "new build", where another install came from)"""
    return f"v{version}" if version[:1].isdigit() else version


def split_note(text):
    """'http://localhost:8080 (chat page; apps use /v1)' as the address and the
    note in brackets after it"""
    match = re.match(r"^(\S+)\s*\((.*)\)\s*$", text)
    return (match.group(1), match.group(2)) if match else (text.strip(), "")


@dataclass
class Item:
    """A folder the menu lists: an engine or service (it has a compose file),
    a folder with scripts only, such as a downloader, or a desktop app"""

    path: str
    group: str
    compose: str = ""
    scripts: list = field(default_factory=list)
    console: set = field(default_factory=set)  # the scripts the menu runs in its console (runs_in_console)

    # From Docker, for engines and services: running, restarting, stopped,
    # "" when it has no container yet, or "?" when Docker couldn't be asked
    docker: str = "?"
    url: str = ""       # where to open it, while it runs
    url_note: str = ""
    info: str = ""      # its ai-leverage.info line, while it runs
    ports: list = field(default_factory=list)
    ready_url: str = ""  # where it says whether it's ready (ai-leverage.ready), while it runs
    started: float = 0.0  # when its container started, while it runs (seconds since 1970)

    # From service.sh or app.sh
    loaded: bool = False
    version: str = ""
    held: bool = False
    previous: str = ""  # the version Revert goes back to
    backup: str = ""    # the copy of its data Revert puts back, if Update made one
    downloaded: bool = True
    app_state: str = ""  # installed, missing, or other (installed another way)
    app_name: str = ""
    source: str = ""
    about: str = ""
    method: str = ""     # how an app is installed: apt, flatpak or script (its app.conf)

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def kind(self):
        if self.group == "apps":
            return "app"
        return "service" if self.compose else "scripts"

    @property
    def project(self):
        """Compose's name for the folder's project, which its containers are
        labelled with: the folder name in lowercase, keeping letters, digits,
        - and _"""
        return re.sub(r"[^a-z0-9_-]", "", self.name.lower())

    @property
    def key(self):
        """Its name in the update check's results: stack/engines/ollama is
        stack-engines-ollama"""
        return os.path.relpath(self.path, BASE_DIR).replace(os.sep, "-")

    @property
    def crumb(self):
        return f"{self.group} › {self.name}"

    def connect(self):
        """The address other containers, such as Open WebUI, reach it at, and
        where that goes: its ai-leverage.connect label, read from the compose
        file, so it shows whether it runs or not"""
        try:
            with open(self.compose) as f:
                match = re.search(r'^ *ai-leverage\.connect: *"(.*)" *$', f.read(), re.M)
        except OSError:
            return "", ""
        return split_note(match.group(1)) if match else ("", "")

    def readme(self):
        path = os.path.join(self.path, "README.md")
        return path if os.path.isfile(path) else ""


# --- What's there ---

def compose_file(path):
    for name in ("compose.yaml", "docker-compose.yml"):
        file = os.path.join(path, name)
        if os.path.isfile(file):
            return file
    return ""


def list_scripts(path):
    """The executable *.sh files in a folder, by name: each one is a menu entry"""
    try:
        entries = list(os.scandir(path))
    except OSError:
        return []
    return sorted(e.name for e in entries
                  if e.name.endswith(".sh") and e.is_file(follow_symlinks=False)
                  and os.access(e.path, os.X_OK))


# The line in a script's top comment that lets the menu show what it prints
# in the pane under the log: it only prints, and never asks anything
CONSOLE_MARK = re.compile(r"#\s*menu:\s*console\b")


def head(path, lines=40):
    """The first lines of a file, or none"""
    try:
        with open(path, errors="replace") as f:
            return [next(f, "") for _ in range(lines)]
    except OSError:
        return []


def runs_in_console(path):
    """Whether a script says the menu can show what it prints in the pane
    under the log, with a line "# menu: console" in the comment at its top. Without it, the menu steps
    aside and runs it in the plain terminal, where it can ask things."""
    for line in head(path)[1:]:
        if not line.startswith("#"):
            return False
        if CONSOLE_MARK.match(line):
            return True
    return False


def uses_sudo(path):
    """Whether a script runs sudo, itself or through a script beside it that
    it names, such as one it loads"""
    def text_of(file):
        try:
            with open(file, errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    text = text_of(path)
    if re.search(r"\bsudo\b", text):
        return True
    try:
        others = [e for e in os.scandir(os.path.dirname(path)) if e.name.endswith(".sh") and e.path != path]
    except OSError:
        return False
    return any(e.name in text and re.search(r"\bsudo\b", text_of(e.path)) for e in others)


def with_console(item):
    """An item with the scripts the menu runs in its pane marked"""
    item.console = {script for script in item.scripts if runs_in_console(os.path.join(item.path, script))}
    return item


def folders(path):
    try:
        return sorted(e.path for e in os.scandir(path) if e.is_dir() and not e.name.startswith("."))
    except OSError:
        return []


def app_method(path):
    """How an app is installed, from the METHOD line in its app.conf"""
    for line in head(os.path.join(path, "app.conf"), 200):
        match = re.match(r"\s*METHOD=[\"']?(\w+)", line)
        if match:
            return match.group(1)
    return ""


def discover():
    """The groups in menu order, as (name, description, items): the ones in
    STACK_GROUPS first, then any other folder in stack/, then the apps. A
    folder counts when it has a compose file or scripts to run, an app when
    it has an app.conf."""
    known = [name for name, _ in STACK_GROUPS]
    groups = list(STACK_GROUPS) + [(os.path.basename(p), "") for p in folders(STACK_DIR)
                                   if os.path.basename(p) not in known]
    found = []
    for group, about in groups:
        items = []
        for path in folders(os.path.join(STACK_DIR, group)):
            compose, scripts = compose_file(path), list_scripts(path)
            if compose or scripts:
                items.append(with_console(Item(path, group, compose, scripts)))
        if items:
            found.append((group, about, items))
    apps = [with_console(Item(path, "apps", scripts=list_scripts(path), method=app_method(path)))
            for path in folders(APPS_DIR) if os.path.isfile(os.path.join(path, "app.conf"))]
    if apps:
        found.append(("apps", APPS_ABOUT, apps))
    return found


# --- How it's doing ---

def sudo_ready():
    """Whether sudo works without asking for the password right now. It also
    keeps it open for sudo's next few minutes, like any use of sudo."""
    return run(["sudo", "-n", "-v"], timeout=10)[1]


@dataclass
class Found:
    """What Docker says about one project's containers"""

    state: str = ""     # running, restarting or stopped
    url: str = ""       # its ai-leverage.url label, or else the first port it publishes on this PC
    info: str = ""      # its ai-leverage.info label
    ports: list = field(default_factory=list)  # (port on this PC, port inside)
    ready: str = ""     # its ai-leverage.ready label
    started: float = 0.0  # when its container started, while it runs


def docker_states():
    """What runs, from one look at Docker: {project: Found}, or None when
    Docker couldn't be asked. url is the ai-leverage.url label (set in
    compose.yaml when the address needs more than a port), or else the first
    port it publishes on this PC; info is its ai-leverage.info label, and
    ready its ai-leverage.ready label."""
    fields = ['{{.Label "com.docker.compose.project"}}', "{{.State}}", '{{.Label "ai-leverage.url"}}',
              '{{.Label "ai-leverage.info"}}', '{{.Label "ai-leverage.ready"}}', "{{.Ports}}", "{{.ID}}"]
    out, ok = run(["sudo", "-n", "docker", "ps", "--all", "--format", SEP.join(fields)], timeout=20)
    if not ok:
        return None
    states, asks = {}, {}
    for line in out.splitlines():
        parts = line.split(SEP)
        if len(parts) != 7 or not parts[0]:
            continue
        project, state, url, info, ready, ports, container = parts
        found = states.setdefault(project, Found())
        # (port on this PC, port inside), once each: Docker lists IPv4 and IPv6 apart
        published = []
        for pair in re.findall(r"(?:^|, )(?:\[[^\]]*\]|[0-9.]+):(\d+)->(\d+)/", ports):
            if pair not in published and pair not in found.ports:
                published.append(pair)
        if state == "running":
            if not url and published:
                url = f"http://localhost:{published[0][0]}"
            found.state = "running"
            found.url, found.info, found.ready = found.url or url, found.info or info, found.ready or ready
            found.ports += published
            if ready:
                asks[container] = project
        elif state == "restarting":
            if found.state != "running":
                found.state = "restarting"
        elif not found.state:
            found.state = "stopped"
    for project, started in started_at(asks).items():
        states[project].started = max(states[project].started, started)
    return states


def started_at(containers):
    """When each of these running containers started, from one more look at
    Docker: {project: seconds since 1970}. containers maps a container's ID
    to its project."""
    if not containers:
        return {}
    out, ok = run(["sudo", "-n", "docker", "inspect", "--format", "{{.Id}}" + SEP + "{{.State.StartedAt}}",
                   *containers], timeout=20)
    started = {}
    for line in out.splitlines() if ok else []:
        container, _, stamp = line.partition(SEP)
        project = next((p for c, p in containers.items() if container.startswith(c)), None)
        # 2026-10-16T08:12:33.123456789Z: in UTC, to the nanosecond
        match = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z$", stamp.strip())
        if project and match:
            seconds = calendar.timegm(time.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S"))
            started[project] = max(started.get(project, 0.0), seconds + float(match.group(2) or 0))
    return started


def apply_docker(items, states):
    """Sets each engine's and service's Docker state, from docker_states()"""
    for item in items:
        if item.kind != "service":
            continue
        found = states.get(item.project, Found()) if states is not None else Found(state="?")
        item.docker, item.info, item.ports = found.state, found.info, found.ports
        item.url, item.url_note = split_note(found.url) if found.url else ("", "")
        item.ready_url, item.started = found.ready, found.started


# Asked directly, never through a proxy someone set for the internet
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def answers(url, timeout=2.0):
    """Whether an engine or service says it's ready, at the address its
    ai-leverage.ready label names: True once it answers there with success.
    While its model loads, an engine doesn't listen yet, answers 503 (busy),
    or keeps the question waiting until it's done; all of that is False."""
    try:
        with DIRECT.open(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, ValueError, http.client.HTTPException):
        return False


def load_status(item):
    """Reads an item's version and update state from service.sh or app.sh,
    without going online. service.sh needs sudo, so only call it after
    sudo_ready()."""
    if item.kind == "service":
        out, _ = run([os.path.join(SCRIPT_DIR, "service.sh"), item.path, "status"])
        state, version, held, previous, item.backup = (out.strip().split("|") + [""] * 5)[:5]
        item.downloaded = state != "missing"
    elif item.kind == "app":
        out, _ = run([os.path.join(SCRIPT_DIR, "app.sh"), item.path, "status"])
        fields = (out.strip().split("|", 6) + [""] * 7)[:7]
        state, version, held, previous, item.app_name, item.source, item.about = fields
        item.app_state = state or "missing"
        item.app_name = item.app_name or item.name
    else:
        item.loaded = True
        return item
    item.version = show_version(version) if version else ""
    item.held = held == "held"
    item.previous = show_version(previous) if previous else ""
    item.loaded = True
    return item


def load_statuses(items, each=None, workers=8):
    """Reads every item's status at the same time. each(item) is called as
    soon as one is done, from the thread that read it."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for item in pool.map(load_status, items):
            if each:
                each(item)


# --- What the last update check found ---

def update_found(item):
    """(result, installed, newest, note) from the last update check, without
    going online, or None when it hasn't checked this one. result is
    current, newer, held, missing or failed (see update-common.sh)."""
    try:
        with open(os.path.join(UPDATE_CACHE_DIR, item.key)) as f:
            fields = f.readline().rstrip("\n").split("|")
    except OSError:
        return None
    return tuple((fields + [""] * 4)[:4])


def last_check():
    """(minutes since the last update check, how many updates it found that
    aren't installed yet), or None when it never ran"""
    try:
        checked = os.path.getmtime(os.path.join(UPDATE_CACHE_DIR, ".checked"))
    except OSError:
        return None
    count = 0
    for entry in os.scandir(UPDATE_CACHE_DIR):
        if entry.is_file() and not entry.name.startswith("."):
            try:
                with open(entry.path) as f:
                    count += f.readline().startswith("newer|")
            except OSError:
                pass
    return int((time.time() - checked) // 60), count


def last_tools():
    """What the last update check found about the tools ai-leverage relies
    on, as (name, version, newest, note), or [] when it never ran"""
    try:
        with open(os.path.join(UPDATE_CACHE_DIR, ".tools")) as f:
            return [tuple((line.rstrip("\n").split("|") + [""] * 4)[:4]) for line in f if line.strip()]
    except OSError:
        return []


def age_text(minutes):
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 2880:
        return f"{minutes // 60} h ago"
    return f"{minutes // 1440} days ago"


# --- What things say about themselves ---

def sentences(text):
    """Text that doesn't end on a colon, as a list that follows it would:
    cut back to the last full sentence"""
    text = text.strip()
    if text.endswith(":") and ". " in text:
        text = text[:text.rindex(". ") + 1]
    elif text.endswith(":"):
        text = text[:-1] + "."
    return text


def readme_intro(path):
    """The first paragraph of a folder's README.md after its title, as Markdown"""
    try:
        with open(os.path.join(path, "README.md")) as f:
            lines = f.read().splitlines()
    except OSError:
        return ""
    paragraph = []
    for line in lines:
        text = line.strip()
        if not paragraph:
            if not text or text.startswith("#"):
                continue
            if text.startswith(("```", "|", "<", "!", ">", "- ", "* ", "1.")):
                return ""
        elif not text:
            break
        paragraph.append(text)
    return sentences(" ".join(paragraph))


def script_intro(path):
    """What a script says it does: the comment at its top, after the line with
    its path, up to a blank comment line, its usage or an example"""
    paragraph = []
    for line in head(path)[1:]:
        if not line.startswith("#"):
            break
        if CONSOLE_MARK.match(line):
            continue
        body = line[1:].rstrip("\n")
        text = body.strip()
        if not paragraph and (not text or text.startswith("ai-leverage/") or set(text) <= set("=-#")
                              or text.isupper()):
            continue
        if not text or text.lower().startswith("usage") or body.startswith("   "):
            break
        paragraph.append(text)
    return sentences(" ".join(paragraph))


def stack_version():
    """Which ai-leverage this is: its release tag, or else its commit, and the
    branch when it isn't main. Empty when it isn't a git checkout."""
    version, ok = run(["git", "-C", BASE_DIR, "describe", "--tags", "--always"], timeout=5)
    if not ok:
        return ""
    branch, _ = run(["git", "-C", BASE_DIR, "branch", "--show-current"], timeout=5)
    version, branch = version.strip(), branch.strip()
    return f"{version} on {branch}" if branch and branch != "main" else version


def main():
    groups = discover()
    items = [item for _, _, members in groups for item in members]
    ready = sudo_ready()
    apply_docker(items, docker_states() if ready else None)
    load_statuses([i for i in items if ready or i.kind != "service"])
    print(f"ai-leverage {stack_version()}" + ("" if ready else "  (no sudo: Docker not read)"))
    for group, about, members in groups:
        print(f"\n{group.upper():<13} {about}")
        for item in members:
            found = update_found(item)
            hint = f"  ↑ {show_version(found[2])}" if found and found[0] == "newer" else ""
            state = item.app_state if item.kind == "app" else item.docker if item.kind == "service" else ""
            if state == "running" and item.ready_url and not answers(item.ready_url):
                state = "loading"
            print(f"  {item.name:<15} {state or '-':<11} {item.version:<11} {item.url}{hint}")
            if item.info:
                print(f"  {'':<15} └ {item.info}")
    found = last_check()
    if found:
        print(f"\nLast update check {age_text(found[0])}: {found[1]} update(s)")


if __name__ == "__main__":
    main()
