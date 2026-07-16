from pathlib import Path

# Environment variables allowed through to the Astro build subprocess.
# npm/node need the basics; everything else (API secrets, LLM keys!) must not
# reach the build — MDX/plugins execute at build time on (possibly
# prompt-injected) project content, so this is the trust boundary. Owned here
# so the api pipeline and the Sam training verifier share one allowlist.
BUILD_ENV_PASSTHROUGH = ("PATH", "HOME", "USER", "SHELL", "TMPDIR", "LANG", "TZ",
                         "NODE_ENV", "NODE_OPTIONS", "npm_config_cache")


class TemplatesUnavailableError(RuntimeError):
    """The bundled templates directory could not be located — neither next to a
    source checkout nor inside the installed package. Raised loudly instead of
    letting callers operate on an empty section whitelist / missing template."""


def _candidate_roots() -> list:
    # 1. Source checkout: this file lives at projects/agent/src/agent/templates.py,
    #    templates live at projects/agent/templates/ → parents[2] from here.
    candidates = [Path(__file__).resolve().parents[2] / "templates"]
    # 2. Installed package data: the wheel force-includes templates/ as
    #    agent/templates (see pyproject.toml), i.e. right next to this module.
    candidates.append(Path(__file__).resolve().parent / "templates")
    return candidates


_TEMPLATES_ROOT: Path | None = None


def _resolve_templates_root() -> Path:
    global _TEMPLATES_ROOT
    # Lazy-init global, now reachable from multiple worker threads at once
    # (F13: LocalGitProvider's FS methods run via asyncio.to_thread). Racing
    # here is benign: _candidate_roots() is a pure/deterministic computation
    # and every racing thread would resolve and assign the same Path value,
    # so no lock is needed — worst case is a few redundant candidate scans.
    if _TEMPLATES_ROOT is None:
        for candidate in _candidate_roots():
            if candidate.is_dir():
                _TEMPLATES_ROOT = candidate
                break
        else:
            raise TemplatesUnavailableError(
                "Bundled agent templates not found (looked for a source checkout at "
                f"{_candidate_roots()[0]} and package data at {_candidate_roots()[1]}). "
                "The 'agent' package must be installed from a wheel that includes its "
                "templates/ tree, or run from a full source checkout."
            )
    return _TEMPLATES_ROOT


def template_path(*parts: str) -> str:
    """Absolute path into the bundled agent templates dir (astro-basic, layouts, SECTIONS.md).
    Raises TemplatesUnavailableError when no templates tree can be located."""
    return str(_resolve_templates_root().joinpath(*parts))


def templates_root() -> str:
    return str(_resolve_templates_root())
