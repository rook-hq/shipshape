#!/usr/bin/env python3
"""Mermaid architecture diagrams from detect.py output (ADR 0002: stdlib only).

The emitter writes C4-style views with plain flowchart and sequenceDiagram
syntax. It does not use Mermaid frontmatter, architecture-beta, or C4Context.
A problem here is a warning for the caller to skip, never a failed setup.
"""

import json
import re
import stat
import subprocess
import sys
from pathlib import Path

VIEWS = ("system_context", "container", "request_flow")
OVERVIEW_REL = Path("docs/architecture/overview.md")
ACCENT_CLASS = "classDef accent fill:#1c3f94,stroke:#1c3f94,color:#ffffff"
WEB_FRAMEWORKS = frozenset({"django", "express", "fastapi", "flask", "next"})
LANGUAGE_LABELS = {
    "python": "Python",
    "node": "Node",
    "go": "Go",
    "rust": "Rust",
    "ruby": "Ruby",
    "java": "Java",
    "csharp": "C#",
}
FRAMEWORK_LABELS = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "express": "Express",
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "svelte": "Svelte",
    "vite": "Vite",
}
REGISTRY_LABELS = {
    "npm": "npm",
    "yarn": "npm",
    "pnpm": "npm",
    "bun": "npm",
    "uv": "PyPI",
    "poetry": "PyPI",
    "pipenv": "PyPI",
    "pip": "PyPI",
    "cargo": "crates.io",
    "bundler": "RubyGems",
    "go modules": "Go modules",
}
RUNNER_LABELS = {
    "pytest": "pytest",
    "jest": "Jest",
    "vitest": "Vitest",
    "mocha": "Mocha",
    "ava": "Ava",
    "tap": "tap",
    "uvu": "uvu",
    "go test": "go test",
    "node --test": "node --test",
    "tsx --test": "tsx --test",
    "bun test": "bun test",
}
SCRIPT_PURPOSES = {
    "architecture.py": (
        "the diagram checker for this repository. The health check runs it to "
        "compare generated diagrams with a fresh scan."
    ),
    "detect.py": (
        "a copy of the shipshape scanner so the health check can redraw "
        "architecture diagrams. It does not change project setup."
    ),
}
# Quoted labels keep parentheses, arrows, and the word "end". Only characters
# that would close the ["..."] delimiters, or break the line, are removed.
_UNSAFE_LABEL = re.compile(r"[\r\n\t\[\]\{\}<|`\";]")
_BLOCK_RE = {
    view: re.compile(
        rf"<!-- shipshape:architecture:{re.escape(view)}:start -->\n"
        rf".*?"
        rf"<!-- shipshape:architecture:{re.escape(view)}:end -->",
        re.DOTALL,
    )
    for view in VIEWS
}


class DiagramError(Exception):
    """The scan or the diagram file could not be read."""


class DiagramSkipped(Exception):
    """An existing overview has no generated blocks, so it is left alone."""


class Node:
    def __init__(self, node_id: str, label: str) -> None:
        self.id = node_id
        self.label = label


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"n_{cleaned}" if cleaned else "n"
    return cleaned[:40]


def safe_label(value: str, fallback: str) -> str:
    text = _UNSAFE_LABEL.sub(" ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80] or fallback


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _languages(detected: dict) -> list[dict]:
    languages = detected.get("languages")
    if not isinstance(languages, list):
        return []
    kept = []
    for item in languages:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name and item.get("confidence") in ("high", "medium"):
            kept.append(item)
    return kept


def language_label(name: str) -> str:
    return LANGUAGE_LABELS.get(name, safe_label(name.replace("_", " ").title(), "Language"))


def framework_label(name: str) -> str:
    if name in FRAMEWORK_LABELS:
        return FRAMEWORK_LABELS[name]
    words = re.sub(r"[^A-Za-z0-9]+", " ", name).strip()
    return safe_label(words.title(), "Framework")


def runner_label(name: str) -> str:
    return RUNNER_LABELS.get(name, safe_label(name, "test"))


def project_label(detected: dict) -> str:
    root = detected.get("root")
    if not isinstance(root, str):
        root = ""
    return safe_label(root, "This project")


def unique_id(base: str, used: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def cap_nodes(focal: Node, others: list[Node], max_nodes: int) -> list[Node]:
    limit = max_nodes if type(max_nodes) is int else 9
    limit = min(9, max(1, limit))
    if limit == 1 or not others:
        return [focal]
    if len(others) <= limit - 1:
        return [focal, *others]
    keep = max(0, limit - 2)
    elided = len(others) - keep
    return [*([focal, *others[:keep]]), Node("other", f"Other parts ({elided})")]


def options_from_config(config: dict) -> dict:
    diagrams = config.get("diagrams")
    if not isinstance(diagrams, dict):
        diagrams = {}
    views = diagrams.get("views", list(VIEWS))
    cleaned: list[str] = []
    if isinstance(views, list):
        for view in views:
            if view in VIEWS and view not in cleaned:
                cleaned.append(view)
    max_nodes = diagrams.get("max_nodes", 9)
    if type(max_nodes) is not int:
        max_nodes = 9
    return {"views": cleaned, "max_nodes": min(9, max(1, max_nodes))}


def _registries(detected: dict) -> list[str]:
    labels = {
        REGISTRY_LABELS.get(name, safe_label(name, "registry"))
        for name in _strings(detected.get("package_managers"))
    }
    return sorted(labels)


def _remote(detected: dict) -> str:
    git_info = detected.get("git")
    if not isinstance(git_info, dict):
        return ""
    remote = git_info.get("remote")
    return remote if isinstance(remote, str) else ""


def system_context_nodes(detected: dict, max_nodes: int) -> list[Node]:
    others = [Node("person", "Person")]
    remote = _remote(detected)
    if remote == "github":
        others.append(Node("github", "GitHub"))
    elif remote == "other":
        others.append(Node("git_remote", "Git remote"))
    registries = _registries(detected)
    if len(registries) == 1:
        others.append(Node("registry", registries[0]))
    elif registries:
        others.append(Node("registry", "Package registries"))
    return cap_nodes(Node("system", project_label(detected)), others, max_nodes)


def context_edges(nodes: list[Node]) -> list[tuple[str, str]]:
    present = {node.id for node in nodes}
    linked = []
    if "person" in present and "system" in present:
        linked.append(("person", "system"))
    for node in nodes:
        if node.id not in {"person", "system"} and "system" in present:
            linked.append(("system", node.id))
    return linked


def container_nodes(detected: dict, max_nodes: int) -> list[Node]:
    languages = _languages(detected)
    used: set[str] = set()
    if languages:
        primary = languages[0]
        focal = Node(
            unique_id(f"lang_{slug(str(primary['name']))}", used),
            language_label(str(primary["name"])),
        )
        rest = languages[1:]
    else:
        focal = Node("system", project_label(detected))
        used.add(focal.id)
        rest = []
    others = [
        Node(
            unique_id(f"lang_{slug(str(item['name']))}", used),
            language_label(str(item["name"])),
        )
        for item in rest
    ]
    frameworks = sorted(
        _strings(detected.get("frameworks")),
        key=lambda name: (framework_label(name), name),
    )
    others.extend(
        Node(unique_id(f"fw_{slug(name)}", used), framework_label(name)) for name in frameworks
    )
    runners = sorted(_strings(detected.get("test_runners")))
    if runners:
        label = "Tests (" + ", ".join(runner_label(name) for name in runners) + ")"
        others.append(Node(unique_id("tests", used), safe_label(label, "Tests")))
    others.sort(key=lambda node: (node.label, node.id))
    return cap_nodes(focal, others, max_nodes)


def quoted_label(label: str) -> str:
    """Mermaid 11 parses id["text"] and rejects unquoted parentheses."""
    return '"' + label.replace('"', "") + '"'


def flowchart(direction: str, nodes: list[Node], linked: list[tuple[str, str]]) -> str:
    focal_id = nodes[0].id
    lines = [f"flowchart {direction}"]
    for node in nodes:
        suffix = ":::accent" if node.id == focal_id else ""
        lines.append(f"  {node.id}[{quoted_label(node.label)}]{suffix}")
    for source, target in linked:
        lines.append(f"  {source} --> {target}")
    lines.append(f"  {ACCENT_CLASS}")
    return "\n".join(lines)


def container_edges(nodes: list[Node]) -> list[tuple[str, str]]:
    if len(nodes) < 2:
        return []
    focal = nodes[0].id
    return [(focal, node.id) for node in nodes[1:]]


def request_flow(detected: dict) -> str | None:
    found = sorted(name for name in _strings(detected.get("frameworks")) if name in WEB_FRAMEWORKS)
    if not found:
        return None
    label = framework_label(found[0])
    return "\n".join(
        [
            "sequenceDiagram",
            f"  actor Person as {quoted_label('Person')}",
            f"  participant App as {quoted_label(label)}",
            "  Person->>App: HTTP request",
            "  App-->>Person: HTTP response",
        ]
    )


def _section(title: str, diagram: str) -> str:
    return f"## {title}\n\n```mermaid\n{diagram}\n```"


def render_sections(detected: dict, options: dict) -> list[tuple[str, str]]:
    views = options.get("views", list(VIEWS))
    max_nodes = options.get("max_nodes", 9)
    sections = []
    if "system_context" in views:
        nodes = system_context_nodes(detected, max_nodes)
        diagram = flowchart("LR", nodes, context_edges(nodes))
        sections.append(("system_context", _section("System context", diagram)))
    if "container" in views:
        nodes = container_nodes(detected, max_nodes)
        sections.append(
            (
                "container",
                _section("Container view", flowchart("TB", nodes, container_edges(nodes))),
            )
        )
    if "request_flow" in views:
        diagram = request_flow(detected)
        if diagram is not None:
            sections.append(("request_flow", _section("Request flow", diagram)))
    return sections


def _header(kit_version: str) -> str:
    return (
        "<!--\n"
        "  What this is: architecture diagrams generated from a scan of this repository.\n"
        "  Safe to edit: yes, outside the generated blocks. Shipshape replaces only the\n"
        "  blocks between its markers.\n"
        f"  managed-by: shipshape v{kit_version}\n"
        "-->\n"
        "\n"
        "# Architecture\n"
        "\n"
        "These diagrams are drawn from a scan of this repository. Text outside the\n"
        "generated blocks is kept when shipshape runs again.\n"
    )


def wrap_block(view: str, inner: str) -> str:
    return (
        f"<!-- shipshape:architecture:{view}:start -->\n"
        f"{inner.rstrip()}\n"
        f"<!-- shipshape:architecture:{view}:end -->"
    )


def render_overview(detected: dict, options: dict, kit_version: str) -> str:
    parts = [_header(kit_version).rstrip(), ""]
    for view, inner in render_sections(detected, options):
        parts.append(wrap_block(view, inner))
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def extract_blocks(text: str) -> dict[str, str]:
    found = {}
    for view, pattern in _BLOCK_RE.items():
        match = pattern.search(text)
        if match:
            found[view] = match.group(0)
    return found


def merge_overview(existing: str | None, fresh: str) -> str:
    """Replace generated blocks. Keep every byte outside them."""
    if existing is None:
        return fresh
    if "<!-- shipshape:architecture:" not in existing:
        raise DiagramSkipped("docs/architecture/overview.md exists without generated blocks")
    text = existing
    fresh_blocks = extract_blocks(fresh)
    for view, block in fresh_blocks.items():
        pattern = _BLOCK_RE[view]
        if pattern.search(text):
            text = pattern.sub(lambda _match, replacement=block: replacement, text, count=1)
        else:
            if not text.endswith("\n"):
                text += "\n"
            text += "\n" + block + "\n"
    for view in VIEWS:
        if view not in fresh_blocks:
            text = _BLOCK_RE[view].sub("", text, count=1)
    if not text.endswith("\n"):
        text += "\n"
    return text


def run_detect(repo: Path) -> dict:
    script = Path(__file__).resolve().parent / "detect.py"
    if not script.is_file():
        raise DiagramError("detect.py is not available")
    try:
        completed = subprocess.run(
            [sys.executable, str(script), str(repo), "--no-network"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DiagramError("detect.py did not return a scan") from error
    if completed.returncode != 0:
        raise DiagramError("detect.py did not return a scan")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DiagramError("detect.py did not return a scan") from error
    if not isinstance(payload, dict) or payload.get("error"):
        raise DiagramError("detect.py did not return a scan")
    return payload


def bundled_script(name: str, kit_version: str) -> str:
    source = (Path(__file__).resolve().parent / name).read_text(encoding="utf-8")
    header = (
        f"# What this is: {SCRIPT_PURPOSES[name]}\n"
        "# Safe to edit: yes — shipshape will ask before overwriting your edits.\n"
        f"# managed-by: shipshape v{kit_version}\n"
    )
    if source.startswith("#!"):
        first, _, rest = source.partition("\n")
        body = first + "\n" + header + rest
    else:
        body = header + source
    if not body.endswith("\n"):
        body += "\n"
    return body


def _skip(detail: str) -> dict:
    return {
        "status": "WARN",
        "detail": detail,
        "next_action": "Re-run /shipshape-doctor. Diagrams are not required for setup.",
    }


def assess(repo: Path) -> dict:
    config_path = repo / ".sdlc" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _skip("architecture diagram check was skipped because the scan did not finish")
    features = config.get("features") if isinstance(config, dict) else None
    if not isinstance(features, dict) or features.get("architecture_diagrams") is not True:
        return {
            "status": "PASS",
            "detail": "architecture diagrams are off",
            "next_action": "",
        }
    overview = repo / OVERVIEW_REL
    try:
        info = overview.lstat()
    except FileNotFoundError:
        return {
            "status": "WARN",
            "detail": "architecture diagrams are on, but docs/architecture/overview.md is missing",
            "next_action": "Re-run /shipshape-init to refresh docs/architecture/overview.md.",
        }
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return _skip(
            "architecture diagram check was skipped because the diagram file is not a regular file"
        )
    try:
        current = overview.read_text(encoding="utf-8")
        detected = run_detect(repo)
        fresh = render_overview(detected, options_from_config(config), "0")
    except (OSError, UnicodeError, DiagramError):
        return _skip("architecture diagram check was skipped because the scan did not finish")
    expected = extract_blocks(fresh)
    actual = extract_blocks(current)
    drifted = sorted(
        view for view in set(expected) | set(actual) if expected.get(view) != actual.get(view)
    )
    if drifted:
        return {
            "status": "WARN",
            "detail": (
                "generated diagram blocks differ from the current scan: " + ", ".join(drifted)
            ),
            "next_action": "Re-run /shipshape-init to refresh docs/architecture/overview.md.",
        }
    return {
        "status": "PASS",
        "detail": "generated diagram blocks match the current scan",
        "next_action": "",
    }


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "check":
        try:
            result = assess(Path(sys.argv[2]))
        except Exception:
            result = _skip("architecture diagram check was skipped because the scan did not finish")
        print(json.dumps(result))
        return 0
    print(json.dumps({"ok": False, "error": "usage: architecture.py check <repo>"}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
