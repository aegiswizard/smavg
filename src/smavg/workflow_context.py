"""Named workflow context capsules for repetitive agent work."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .context import ContextError, build_context_report_from_file_map


@dataclass(frozen=True)
class WorkflowProfile:
    name: str
    description: str
    files: Tuple[Tuple[str, Path], ...]


def available_workflow_profiles() -> List[Dict[str, object]]:
    return [
        {
            "name": profile.name,
            "description": profile.description,
            "files": len(profile.files),
        }
        for profile in _profiles().values()
    ]


def build_workflow_context_report(name: str, budget_tokens: int | None = None) -> Dict[str, object]:
    profiles = _profiles()
    if name not in profiles:
        known = ", ".join(sorted(profiles))
        raise ContextError(f"Unknown workflow profile: {name}. Known profiles: {known}")
    profile = profiles[name]
    file_map = {relative: path for relative, path in profile.files}
    report = build_context_report_from_file_map(
        file_map=file_map,
        source_label=f"workflow:{profile.name}",
        budget_tokens=budget_tokens,
        source_kind="workflow",
        rebuild_command=f"smavg workflow-context {profile.name}",
    )
    report["workflow"] = {
        "name": profile.name,
        "description": profile.description,
        "requested_files": len(profile.files),
        "available_files": report["file_count"],
        "missing_files": report.get("missing_source_count", 0),
    }
    return report


def _profiles() -> Dict[str, WorkflowProfile]:
    home = Path.home()
    codex_skills = home / ".codex" / "skills"
    kimi_skills = home / ".kimi" / "skills"
    memories = home / ".codex" / "memories"
    common = (
        ("memories/medium-term/workflows_and_runbooks.md", memories / "medium-term" / "workflows_and_runbooks.md"),
        ("memories/short-term/current_focus.md", memories / "short-term" / "current_focus.md"),
        ("memories/short-term/session_handoff.md", memories / "short-term" / "session_handoff.md"),
        (
            "memories/long-term/collaboration_preferences.md",
            memories / "long-term" / "collaboration_preferences.md",
        ),
    )
    return {
        "x-browsermcp": WorkflowProfile(
            name="x-browsermcp",
            description="X / x.com BrowserMCP posting and operating workflow.",
            files=(
                ("skills/codex/x-browser-automation/SKILL.md", codex_skills / "x-browser-automation" / "SKILL.md"),
                (
                    "memories/medium-term/x_browser_automation_workflow.md",
                    memories / "medium-term" / "x_browser_automation_workflow.md",
                ),
                *common,
            ),
        ),
        "reddit-browsermcp": _browsermcp_profile(
            "reddit-browsermcp",
            "Reddit BrowserMCP workflow.",
            "reddit-browsermcp",
            "reddit_browsermcp_workflow.md",
            codex_skills,
            kimi_skills,
            memories,
            common,
        ),
        "linkedin-browsermcp": _browsermcp_profile(
            "linkedin-browsermcp",
            "LinkedIn BrowserMCP workflow.",
            "linkedin-browsermcp",
            "linkedin_browsermcp_workflow.md",
            codex_skills,
            kimi_skills,
            memories,
            common,
        ),
        "producthunt-browsermcp": _browsermcp_profile(
            "producthunt-browsermcp",
            "Product Hunt BrowserMCP workflow.",
            "producthunt-browsermcp",
            "producthunt_browsermcp_workflow.md",
            codex_skills,
            kimi_skills,
            memories,
            common,
        ),
        "hackernews-browsermcp": _browsermcp_profile(
            "hackernews-browsermcp",
            "Hacker News BrowserMCP workflow.",
            "hackernews-browsermcp",
            "hackernews_browsermcp_workflow.md",
            codex_skills,
            kimi_skills,
            memories,
            common,
        ),
        "threads-browsermcp": _browsermcp_profile(
            "threads-browsermcp",
            "Threads BrowserMCP workflow.",
            "threads-browsermcp",
            "threads_browsermcp_workflow.md",
            codex_skills,
            kimi_skills,
            memories,
            common,
        ),
    }


def _browsermcp_profile(
    name: str,
    description: str,
    skill_dir: str,
    memory_file: str,
    codex_skills: Path,
    kimi_skills: Path,
    memories: Path,
    common: Iterable[Tuple[str, Path]],
) -> WorkflowProfile:
    files = (
        (f"skills/codex/{skill_dir}/SKILL.md", codex_skills / skill_dir / "SKILL.md"),
        (f"skills/kimi/{skill_dir}/SKILL.md", kimi_skills / skill_dir / "SKILL.md"),
        (f"memories/medium-term/{memory_file}", memories / "medium-term" / memory_file),
        *tuple(common),
    )
    return WorkflowProfile(name=name, description=description, files=files)
