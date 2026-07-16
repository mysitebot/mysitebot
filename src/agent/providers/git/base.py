import asyncio
import os
import re
import shutil
from abc import ABC, abstractmethod
from typing import Dict, Any, List
import logging

from agent.config import settings
from agent.content_safety import is_safe_content_path, check_content_for_cookies
from agent.templates import template_path

logger = logging.getLogger(__name__)


def sanitize_project_name(name: str) -> str:
    """Reduce a caller-supplied project name/id to a single safe, lowercase
    slug — the ONE sanitizer shared by the availability answer and the created
    folder, so the name a user is told is available always matches the folder
    (and id) actually created. Strips any local_ prefix and path components
    and blocks traversal/hidden names, so an LLM-supplied name like '../../etc'
    or 'local_../secret' cannot escape the workspace."""
    base = name[6:] if name.startswith("local_") else name
    base = base.replace("\\", "/").split("/")[-1]  # drop any path components
    slug = re.sub(r"[^a-z0-9._-]", "-", base.lower())
    slug = re.sub(r"\.+", ".", slug)               # collapse .. so no traversal survives
    slug = re.sub(r"-+", "-", slug).strip(".-")    # no leading/trailing dot or dash
    return slug or "mysite"


class GitProvider(ABC):
    @abstractmethod
    async def create_project(self, name: str, template: str) -> Dict[str, Any]:
        """Creates a new project/repository."""
        pass

    @abstractmethod
    async def create_branch(self, project_id: str, branch_name: str) -> Dict[str, Any]:
        """Creates a new branch in the specified project."""
        pass

    @abstractmethod
    async def commit_file(self, project_id: str, branch_name: str, file_path: str, content: str, message: str) -> Dict[str, Any]:
        """Commits a file to a specific branch."""
        pass

    @abstractmethod
    async def create_merge_request(self, project_id: str, source_branch: str, target_branch: str, title: str) -> Dict[str, Any]:
        """Creates a merge request."""
        pass

    @abstractmethod
    async def merge_merge_request(self, project_id: str, mr_iid: int) -> Dict[str, Any]:
        """Accepts (merges) a merge request, publishing the draft to main."""
        pass

    @abstractmethod
    async def delete_file(self, project_id: str, branch_name: str, file_path: str, message: str) -> Dict[str, Any]:
        """Deletes a single repository file on the given branch (content/ only)."""
        pass

    @abstractmethod
    async def read_file(self, project_id: str, file_path: str, ref: str = "main") -> str:
        """Reads the raw content of a repository file."""
        pass

    @abstractmethod
    async def list_files(self, project_id: str, path: str = "content", ref: str = "main") -> List[str]:
        """Lists file paths under the given directory."""
        pass

    @abstractmethod
    async def delete_project(self, project_id: str) -> bool:
        """Deletes a project/repository."""
        pass

    async def check_project_availability(self, name: str) -> Dict[str, Any]:
        """Checks whether a desired project name is available and returns the
        cleaned name to use. Default: local sanitization only (always
        available) — providers backed by a remote namespace (GitLab) override
        this with a real duplicate check."""
        return {"available": True, "name": sanitize_project_name(name)}

    async def get_pages_url(self, project_id: str) -> str | None:
        """The authoritative published-site URL, when the provider can resolve
        one after deployment. None means the caller's stored URL stands."""
        return None

class LocalGitProvider(GitProvider):
    def __init__(self, workspace_root: str = None):
        if workspace_root is None:
            workspace_root = os.environ.get("LOCAL_WORKSPACE_ROOT", "local_workspace")
        self.workspace_root = os.path.abspath(workspace_root)
        os.makedirs(self.workspace_root, exist_ok=True)

    def _safe_folder_name(self, name: str) -> str:
        """The on-disk folder for a caller-supplied project name/id — the
        shared sanitizer, so create/read/write/delete and the availability
        answer all agree on one safe location."""
        return sanitize_project_name(name)

    def _contained_dir(self, folder_name: str) -> str:
        """Join a sanitized folder name onto the workspace root and assert the
        result stays within it (defense in depth against symlink/edge escapes)."""
        full = os.path.join(self.workspace_root, folder_name)
        real_root = os.path.realpath(self.workspace_root)
        real_full = os.path.realpath(full)
        if real_full != real_root and not real_full.startswith(real_root + os.sep):
            raise ValueError("Resolved project path escapes the workspace root.")
        return full

    def _delete_project_sync(self, project_id: str) -> bool:
        project_dir = self._contained_dir(self._safe_folder_name(project_id))
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
        # Absent counts as deleted — callers fail closed on False (F03), and a
        # never-materialized or already-removed workspace must not brick them.
        return True

    async def delete_project(self, project_id: str) -> bool:
        return await asyncio.to_thread(self._delete_project_sync, project_id)

    def _get_path(self, project_id: str, path: str) -> str:
        if not project_id or project_id == "local_project":
            base = self.workspace_root
        else:
            base = self.project_dir(project_id)
        full = os.path.join(base, path)
        # Mirror _contained_dir: os.path.join silently DISCARDS `base` for an
        # absolute `path`, and '..' segments climb out of it — assert containment
        # so no read/write/delete can ever resolve outside the project workspace.
        real_base = os.path.realpath(base)
        real_full = os.path.realpath(full)
        if real_full != real_base and not real_full.startswith(real_base + os.sep):
            raise ValueError("Resolved file path escapes the project workspace.")
        return full

    def project_dir(self, project_id: str) -> str:
        """Resolves the (contained) workspace directory for a project id, with or
        without the local_ prefix. The folder name is always sanitized so the
        create/read/write/delete paths agree on one safe location."""
        return self._contained_dir(self._safe_folder_name(project_id))

    def _create_project_sync(self, name: str, template: str) -> Dict[str, Any]:
        folder_name = self._safe_folder_name(name)
        project_id = f"local_{folder_name}"
        project_dir = self._contained_dir(folder_name)
        if os.path.exists(project_dir):
            # Never silently wipe an existing site. The caller must delete it
            # explicitly (delete_project) or pick a different name.
            raise ValueError(
                f"A project directory '{folder_name}' already exists. Delete it "
                f"first or choose a different name; refusing to overwrite it."
            )

        # Determine the base Astro template path
        base_template = template_path("astro-basic")

        shutil.copytree(base_template, project_dir, ignore=shutil.ignore_patterns("node_modules", ".astro", "dist"))

        # Link node_modules from the template so local preview builds work without npm install
        template_modules = os.path.join(base_template, "node_modules")
        project_modules = os.path.join(project_dir, "node_modules")
        if os.path.isdir(template_modules) and not os.path.exists(project_modules):
            try:
                os.symlink(template_modules, project_modules)
            except OSError as e:
                logger.error(f"[Local Git Provider] Could not link node_modules: {e}")

        # Overlay layout content if template layout maps to layout content
        layout_content_dir = template_path("layouts", template, "content")

        if os.path.exists(layout_content_dir) and os.path.isdir(layout_content_dir):
            dest_content_dir = os.path.join(project_dir, "content")
            if os.path.exists(dest_content_dir):
                shutil.rmtree(dest_content_dir)
            shutil.copytree(layout_content_dir, dest_content_dir)

        # Absolute preview URL: the path is served by the backend after a local
        # build, and the link must be clickable from any chat channel.
        preview_url = f"{settings.preview_base_url.rstrip('/')}/preview/{project_id}/"

        return {
            "id": project_id,
            "project_id": project_id,
            "name": name,
            "status": "created_locally",
            "web_url": f"local://{project_dir}",
            "pages_url": preview_url
        }

    async def create_project(self, name: str, template: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._create_project_sync, name, template)

    async def create_branch(self, project_id: str, branch_name: str) -> Dict[str, Any]:
        return {"status": "branch_created_locally", "branch": branch_name}

    def _commit_file_sync(self, project_id: str, branch_name: str, file_path: str, content: str, message: str) -> Dict[str, Any]:
        if not is_safe_content_path(file_path):
            raise ValueError("MYSITEBOT agents can only modify files in the content/ directory.")

        cookie_error = check_content_for_cookies(content, file_path)
        if cookie_error:
            raise ValueError(f"Privacy Constraint Violated: {cookie_error}")

        full_path = self._get_path(project_id, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w") as f:
            f.write(content)

        logger.info(f"[Local Git Provider] Committed to {file_path} in {project_id} (Branch: {branch_name})")
        return {"status": "committed_locally", "file": file_path}

    async def commit_file(self, project_id: str, branch_name: str, file_path: str, content: str, message: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._commit_file_sync, project_id, branch_name, file_path, content, message)

    def _delete_file_sync(self, project_id: str, branch_name: str, file_path: str, message: str) -> Dict[str, Any]:
        if not is_safe_content_path(file_path):
            raise ValueError("MYSITEBOT agents can only delete files in the content/ directory.")

        full_path = self._get_path(project_id, file_path)
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"'{file_path}' does not exist.")
        os.remove(full_path)

        logger.info(f"[Local Git Provider] Deleted {file_path} in {project_id} (Branch: {branch_name})")
        return {"status": "deleted_locally", "file": file_path}

    async def delete_file(self, project_id: str, branch_name: str, file_path: str, message: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._delete_file_sync, project_id, branch_name, file_path, message)

    async def create_merge_request(self, project_id: str, source_branch: str, target_branch: str, title: str) -> Dict[str, Any]:
        return {"status": "mr_created_locally", "id": 123, "iid": 123}

    async def merge_merge_request(self, project_id: str, mr_iid: int) -> Dict[str, Any]:
        return {"status": "merged_locally", "iid": mr_iid}

    def _read_file_sync(self, project_id: str, file_path: str, ref: str = "main") -> str:
        full_path = self._get_path(project_id, file_path)
        with open(full_path, "r") as f:
            return f.read()

    async def read_file(self, project_id: str, file_path: str, ref: str = "main") -> str:
        return await asyncio.to_thread(self._read_file_sync, project_id, file_path, ref)

    def _list_files_sync(self, project_id: str, path: str = "content", ref: str = "main") -> List[str]:
        base_dir = self._get_path(project_id, path)
        results: List[str] = []
        if not os.path.isdir(base_dir):
            return results
        for root, _, files in os.walk(base_dir):
            for file in files:
                full = os.path.join(root, file)
                rel = os.path.relpath(full, self._get_path(project_id, ""))
                results.append(rel.replace(os.path.sep, "/"))
        return sorted(results)

    async def list_files(self, project_id: str, path: str = "content", ref: str = "main") -> List[str]:
        return await asyncio.to_thread(self._list_files_sync, project_id, path, ref)
