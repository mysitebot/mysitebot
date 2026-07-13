#!/usr/bin/env python
import os
import sys
import asyncio
import argparse

# Make the bundled `agent` package importable when the CLI is run directly
# (`python projects/agent/cli.py`), not only via `uv run` / an editable install.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from agent.site_editor import AgentSiteEditor
from agent.providers.git.base import LocalGitProvider

async def main():
    parser = argparse.ArgumentParser(description="mysite.bot CLI: Run website edits locally via an OpenAI-compatible LLM.")
    parser.add_argument("--prompt", required=True, help="Instructions/prompt for updating the website")
    parser.add_argument("--dir", default=".", help="Path to your local Astro site workspace (default: current directory)")
    # Default None: the config fallback wins (LLM_MODEL env var / built-in
    # default) — a hardcoded default here would silently override LLM_MODEL.
    parser.add_argument("--model", default=None,
                        help="LLM model name (default: LLM_MODEL env var, else the config default)")
    args = parser.parse_args()

    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        print("Error: LLM_API_KEY environment variable is required to run this CLI.", file=sys.stderr)
        print("Please set it in your environment: export LLM_API_KEY='your_key'", file=sys.stderr)
        sys.exit(1)

    workspace_dir = os.path.abspath(args.dir)
    print(f"Targeting local workspace: {workspace_dir}")
    
    # If the folder doesn't exist, we'll let LocalGitProvider create the project template.
    if not os.path.exists(workspace_dir):
        print(f"Workspace directory {workspace_dir} does not exist. Creating and provisioning template...")
        parent_dir = os.path.dirname(workspace_dir)
        proj_name = os.path.basename(workspace_dir)
        provider = LocalGitProvider(workspace_root=parent_dir)
        created = await provider.create_project(proj_name, "astro-basic")
        # The provider stays rooted at the parent, so the agent must target the
        # project it just created — using "local_project" here would resolve back
        # to the parent dir and write edits outside the new workspace.
        project_id = created.get("id") or created.get("project_id")
        print(f"Provisioned new site at: {created.get('web_url', workspace_dir)}")
    else:
        provider = LocalGitProvider(workspace_root=workspace_dir)
        project_id = "local_project"

    # Optional image search via wagmi.photos (OpenAI-compatible). BYO key; unset = disabled.
    media_search = None
    wagmi_key = os.environ.get("WAGMI_KEY")
    if wagmi_key:
        from agent.media_search import WagmiMediaSearch
        media_search = WagmiMediaSearch(api_key=wagmi_key)
        print("Image search: wagmi.photos enabled.")

    # Initialize the core site editor with the local git provider
    editor = AgentSiteEditor(
        api_key=api_key,
        git_provider=provider,
        model=args.model,
        session_id="local_cli_session",
        media_search=media_search,
    )

    print("Invoking the agent...")
    try:
        result = await editor.run(args.prompt, project_id)
        print("\n--- mysite.bot Response ---")
        print(result["text"])
        print("--------------------------")
    except Exception as e:
        print(f"Error executing agent: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
