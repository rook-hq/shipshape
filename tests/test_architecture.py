"""Architecture diagrams: Mermaid from detect output, markers, and fail-soft setup."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import KIT_ROOT, SCRIPTS, init_repo, run_script

OVERVIEW = "docs/architecture/overview.md"
ARCH_SCRIPT = ".sdlc/scripts/architecture.py"
DETECT_SCRIPT = ".sdlc/scripts/detect.py"
CI_WORKFLOW = ".github/workflows/architecture-diagrams.yml"
ACCENT = "classDef accent fill:#1c3f94,stroke:#1c3f94,color:#ffffff"
NODE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\[[^\]]*\]", re.MULTILINE)
MERMAID_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
DIAGRAM_COMMIT = "d74d8c2d0c78a9e1efd43137f6a9a51182a8b5f0"


def load_render():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import architecture
    import render

    return architecture, render


def sample_detect(**overrides) -> dict:
    detected = {
        "root": "repo-python",
        "languages": [
            {"name": "python", "confidence": "high", "evidence": ["pyproject.toml"]},
        ],
        "frameworks": ["fastapi"],
        "package_managers": [],
        "test_runners": ["pytest"],
        "git": {"remote": "", "owner_repo": "", "is_repo": False},
        "ci": {"github_actions": False, "workflows": []},
        "existing_sdlc": {"config_present": False, "kit_version": None},
    }
    detected.update(overrides)
    return detected


def mermaid_blocks(text: str) -> list[str]:
    return MERMAID_RE.findall(text)


def flowchart_blocks(text: str) -> list[str]:
    return [block for block in mermaid_blocks(text) if "flowchart " in block]


def node_ids(block: str) -> list[str]:
    return NODE_RE.findall(block)


def test_render_is_deterministic_for_the_same_detect_input():
    architecture, _render = load_render()
    options = {"views": ["system_context", "container", "request_flow"], "max_nodes": 9}
    first = sample_detect(frameworks=["flask", "fastapi", "react"])
    second = sample_detect(frameworks=["react", "fastapi", "flask"])

    rendered = architecture.render_overview(first, options, "0.4.0")
    again = architecture.render_overview(first, options, "0.4.0")
    reordered = architecture.render_overview(second, options, "0.4.0")

    assert rendered == again == reordered
    assert architecture.merge_overview(rendered, rendered) == rendered
    assert rendered.endswith("\n")
    assert "architecture-beta" not in rendered
    assert "C4Context" not in rendered
    assert "C4Container" not in rendered
    for block in mermaid_blocks(rendered):
        assert not block.lstrip().startswith("---")


def test_flowchart_node_labels_are_double_quoted():
    """Mermaid 11 rejects unquoted labels that contain parentheses."""
    architecture, _render = load_render()
    tricky = "end --> core: # & (suite)"
    options = {"views": ["system_context", "container", "request_flow"], "max_nodes": 9}
    rendered = architecture.render_overview(
        sample_detect(root=tricky, test_runners=[tricky], package_managers=[tricky]),
        options,
        "0.4.0",
    )
    node_line = re.compile(r'^  [A-Za-z_][A-Za-z0-9_]*\["[^"]*"\](?::::accent)?$')
    edge_line = re.compile(r"^  [A-Za-z_][A-Za-z0-9_]* --> [A-Za-z_][A-Za-z0-9_]*$")
    seen = {token: False for token in ("(", ")", "#", "&", ":", "-->", "end")}
    charts = flowchart_blocks(rendered)
    assert charts
    for block in charts:
        assert re.search(r"\[[^\"\n]", block) is None
        for line in block.splitlines():
            if line.startswith("flowchart ") or line.startswith("  classDef "):
                continue
            if edge_line.match(line):
                continue
            assert node_line.match(line), line
            label = line.split('["', 1)[1].split('"]', 1)[0]
            for token in seen:
                if token in label:
                    seen[token] = True
    assert seen == dict.fromkeys(seen, True)
    capped = architecture.render_overview(
        sample_detect(frameworks=[f"framework{index}" for index in range(12)], test_runners=[]),
        {"views": ["container"], "max_nodes": 9},
        "0.4.0",
    )
    assert re.search(r'\["Other parts \(\d+\)"\]', capped)
    sequence = next(
        block for block in mermaid_blocks(rendered) if block.startswith("sequenceDiagram")
    )
    assert "  actor Person\n" in sequence
    participant_lines = [
        line for line in sequence.splitlines() if line.strip().startswith("participant ")
    ]
    assert participant_lines
    for line in participant_lines:
        assert '"' not in line
        assert "#" not in line
    cleaned = architecture.sequence_label("end --> core: # & (suite)")
    assert "#" not in cleaned
    for token in ("(", ")", "&", ":", "-->", "end"):
        assert token in cleaned


def test_each_flowchart_uses_one_accent_class_on_the_focal_node_only():
    architecture, _render = load_render()
    options = {"views": ["system_context", "container", "request_flow"], "max_nodes": 9}
    rendered = architecture.render_overview(sample_detect(), options, "0.4.0")
    charts = flowchart_blocks(rendered)

    assert len(charts) == 2
    for block in charts:
        assert block.count(":::accent") == 1
        assert block.count("classDef") == 1
        assert ACCENT in block
    sequence = [block for block in mermaid_blocks(rendered) if "sequenceDiagram" in block]
    assert len(sequence) == 1
    assert "classDef" not in sequence[0]
    assert "participant App as FastAPI" in sequence[0]
    assert '"' not in sequence[0]


def test_node_cap_groups_the_overflow_into_one_node():
    architecture, _render = load_render()
    frameworks = [f"framework{index}" for index in range(15)]
    options = {"views": ["container"], "max_nodes": 9}
    rendered = architecture.render_overview(
        sample_detect(frameworks=frameworks, test_runners=[]),
        options,
        "0.4.0",
    )
    (block,) = flowchart_blocks(rendered)

    assert len(node_ids(block)) <= 9
    assert "Other parts (" in block
    assert block.count(":::accent") == 1


def test_request_flow_is_omitted_without_a_server_framework():
    architecture, _render = load_render()
    options = {"views": ["system_context", "container", "request_flow"], "max_nodes": 9}
    rendered = architecture.render_overview(
        sample_detect(frameworks=["react"], test_runners=["vitest"]),
        options,
        "0.4.0",
    )

    assert "sequenceDiagram" not in rendered
    assert "system_context" in rendered or "System context" in rendered


def test_new_init_defaults_diagrams_on_and_validation_rejects_a_bad_block():
    _architecture, render = load_render()
    config = json.loads((KIT_ROOT / "templates/sdlc/config.json").read_text(encoding="utf-8"))

    assert config["features"]["architecture_diagrams"] is True
    assert config["diagrams"] == {
        "engine": "mermaid",
        "views": ["system_context", "container", "request_flow"],
        "max_nodes": 9,
        "ci_validate": False,
    }
    assert render.validate_config(config) == []

    existing = json.loads(json.dumps(config))
    del existing["features"]["architecture_diagrams"]
    del existing["diagrams"]
    assert render.validate_config(existing) == []

    config["diagrams"]["max_nodes"] = 10
    assert any("max_nodes" in problem for problem in render.validate_config(config))
    config["diagrams"]["max_nodes"] = 9
    config["diagrams"]["engine"] = "d2"
    assert any("engine" in problem for problem in render.validate_config(config))
    config["diagrams"]["engine"] = "mermaid"
    config["diagrams"]["views"] = ["C4Context"]
    assert any("views" in problem for problem in render.validate_config(config))
    config["diagrams"]["views"] = ["system_context"]
    config["diagrams"]["ci_validate"] = "yes"
    assert any("ci_validate" in problem for problem in render.validate_config(config))
    config["diagrams"]["ci_validate"] = True
    config["features"]["architecture_diagrams"] = False
    assert any("architecture_diagrams" in problem for problem in render.validate_config(config))


def test_apply_writes_marked_diagrams_and_reapply_keeps_outside_edits(tmp_path):
    repo = init_repo("repo-python", tmp_path)
    code, first = run_script("render.py", "apply", repo)
    overview = repo / OVERVIEW
    assert code == 0 and first["ok"], first
    assert OVERVIEW in first["written"]
    assert ARCH_SCRIPT in first["written"]
    assert DETECT_SCRIPT in first["written"]
    original = overview.read_text(encoding="utf-8")
    assert "managed-by: shipshape" in original
    assert "<!-- shipshape:architecture:system_context:start -->" in original
    assert "<!-- shipshape:architecture:system_context:end -->" in original
    assert ACCENT in original

    code, second = run_script("render.py", "apply", repo)
    assert code == 0 and second["written"] == [], second
    assert overview.read_bytes() == original.encode("utf-8")

    edited = original.replace("HTTP request", "HTTP request edited", 1) + "User note stays.\n"
    overview.write_text(edited, encoding="utf-8")
    code, third = run_script("render.py", "apply", repo)
    restored = overview.read_text(encoding="utf-8")
    assert code == 0 and third["ok"], third
    assert "User note stays." in restored
    assert "HTTP request edited" not in restored
    assert "HTTP request" in restored
    assert restored.startswith(original.split("<!-- shipshape:architecture:", 1)[0])

    code, fourth = run_script("render.py", "apply", repo)
    assert code == 0 and fourth["written"] == [], fourth
    assert "User note stays." in overview.read_text(encoding="utf-8")


def test_feature_off_skips_diagrams_and_ci_validate_is_opt_in(tmp_path):
    quiet = init_repo(
        "repo-python",
        tmp_path / "quiet",
        overrides=["features.architecture_diagrams=false"],
    )
    code, result = run_script("render.py", "apply", quiet)
    assert code == 0 and result["ok"], result
    assert OVERVIEW not in result["written"]
    assert not (quiet / OVERVIEW).exists()
    assert not (quiet / CI_WORKFLOW).exists()

    checked = init_repo(
        "repo-python",
        tmp_path / "checked",
        overrides=["diagrams.ci_validate=true"],
    )
    code, result = run_script("render.py", "apply", checked)
    assert code == 0 and result["ok"], result
    workflow = (checked / CI_WORKFLOW).read_text(encoding="utf-8")
    assert "beautiful-mermaid@1.1.3" in workflow
    assert "permissions:" in workflow
    assert "architecture-beta" not in workflow
    assert "C4Context" not in workflow

    config_path = checked / ".sdlc/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["diagrams"]["ci_validate"] = False
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    code, removed = run_script("render.py", "apply", checked)
    assert code == 0 and removed["ok"], removed
    assert CI_WORKFLOW in removed["removed"]
    assert not (checked / CI_WORKFLOW).exists()


def test_emitter_failure_does_not_block_the_plan(tmp_path, monkeypatch):
    repo = init_repo("repo-python", tmp_path)
    config = json.loads((repo / ".sdlc/config.json").read_text(encoding="utf-8"))
    source = (repo / ".sdlc/config.json").read_bytes()
    _architecture, render = load_render()

    def boom(*_args, **_kwargs):
        raise RuntimeError("diagram emitter failed")

    monkeypatch.setattr(render, "_attach_architecture_files", boom)
    plan = render.compute_plan(repo, config, source, False)

    assert plan["ok"] is True
    assert plan["status"] != "invalid"
    assert any("diagram emitter failed" in item["warning"] for item in plan["warnings"])
    assert all(item["path"] != OVERVIEW for item in plan["writes"])
    assert any(item["path"] == ".github/workflows/ci.yml" for item in plan["writes"])


def test_doctor_warns_on_drift_or_a_missing_file_and_never_fails(tmp_path):
    repo = init_repo("repo-python", tmp_path)
    code, applied = run_script("render.py", "apply", repo)
    assert code == 0 and applied["ok"], applied
    _prepare_doctor_repo(repo)
    config_path = repo / ".sdlc/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    code, payload = run_script("doctor.py", repo)
    check = _check(payload, "architecture diagrams")
    assert code == 0 and payload["ok"] is True
    assert check["status"] == "PASS"
    assert check["detail"] == "generated diagram blocks match the current scan"

    overview = repo / OVERVIEW
    overview.write_text(
        overview.read_text(encoding="utf-8").replace("HTTP request", "HTTP request edited", 1),
        encoding="utf-8",
    )
    code, payload = run_script("doctor.py", repo)
    check = _check(payload, "architecture diagrams")
    assert code == 0 and payload["ok"] is True
    assert check["status"] == "WARN"
    assert "differ from the current scan" in check["detail"]
    assert check["status"] != "FAIL"
    assert payload["counts"]["FAIL"] == 0

    overview.unlink()
    code, payload = run_script("doctor.py", repo)
    check = _check(payload, "architecture diagrams")
    assert code == 0 and payload["ok"] is True
    assert check["status"] == "WARN"
    assert "missing" in check["detail"]

    config["features"]["architecture_diagrams"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    code, payload = run_script("doctor.py", repo)
    check = _check(payload, "architecture diagrams")
    assert code == 0 and payload["ok"] is True
    assert check == {
        "name": "architecture diagrams",
        "status": "PASS",
        "detail": "architecture diagrams are off",
        "next_action": "",
    }


def test_a_broken_checker_warns_and_does_not_fail_the_rendered_doctor(tmp_path):
    repo = init_repo("repo-python", tmp_path)
    code, applied = run_script("render.py", "apply", repo)
    assert code == 0 and applied["ok"], applied
    _prepare_doctor_repo(repo)
    (repo / ARCH_SCRIPT).write_text("raise SystemExit('checker failed')\n", encoding="utf-8")

    proc_code, payload = _rendered_doctor(repo)
    check = _check(payload, "architecture diagrams")
    assert proc_code == 0 and payload["ok"] is True
    assert check["status"] == "WARN"
    assert payload["counts"]["FAIL"] == 0


def test_foreign_overview_is_left_alone(tmp_path):
    repo = init_repo("repo-python", tmp_path)
    foreign = repo / OVERVIEW
    foreign.parent.mkdir(parents=True)
    foreign.write_text("# Our own architecture\n\nNot generated.\n", encoding="utf-8")

    code, result = run_script("render.py", "apply", repo)
    assert code == 0 and result["ok"], result
    assert OVERVIEW not in result["written"]
    assert foreign.read_text(encoding="utf-8") == "# Our own architecture\n\nNot generated.\n"
    assert any(item["path"] == OVERVIEW for item in result.get("warnings", []))


def test_docs_name_the_real_diagram_design_repo_and_the_impostor():
    skill = (KIT_ROOT / "skills/shipshape-init/SKILL.md").read_text(encoding="utf-8")
    guide = (KIT_ROOT / "docs/sdlc/architecture-diagrams.md").read_text(encoding="utf-8")
    readme = (KIT_ROOT / "README.md").read_text(encoding="utf-8")
    lighthouse = (KIT_ROOT / ".github/workflows/lighthouse.yml").read_text(encoding="utf-8")

    for text in (skill, guide):
        assert "https://github.com/cathrynlavery/diagram-design" in text
        assert DIAGRAM_COMMIT in text
        assert "catherynlavery/diagram-design" in text
        assert "docs/architecture/presentation/" in text
    assert "D2" in guide
    assert "157.0.8103.38" in guide
    assert "PUPPETEER_SKIP_DOWNLOAD" in guide
    assert "157.0.8103.38" in lighthouse
    assert "docs/architecture/overview.md" in readme


def _prepare_doctor_repo(repo: Path) -> None:
    config_path = repo / ".sdlc/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["features"]["branch_protection"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    subprocess.run(["git", "init", "-qb", "main"], cwd=repo, check=True)
    hooks = repo / ".git/hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").symlink_to("../../.sdlc/hooks/secret-guard.sh")


def _check(payload: dict, name: str) -> dict:
    return {item["name"]: item for section in payload["sections"] for item in section["checks"]}[
        name
    ]


def _rendered_doctor(repo: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(repo / ".sdlc/scripts/doctor.py"), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, json.loads(proc.stdout)


@pytest.mark.parametrize(
    "fixture, expects_sequence",
    [("repo-python", True), ("repo-node", True), ("repo-go", False)],
)
def test_fixture_diagrams_follow_the_scan(tmp_path, fixture, expects_sequence):
    repo = init_repo(fixture, tmp_path)
    code, result = run_script("render.py", "apply", repo)
    assert code == 0 and result["ok"], result
    text = (repo / OVERVIEW).read_text(encoding="utf-8")
    assert ("sequenceDiagram" in text) is expects_sequence
    for block in flowchart_blocks(text):
        assert len(node_ids(block)) <= 9
        assert block.count(":::accent") == 1
