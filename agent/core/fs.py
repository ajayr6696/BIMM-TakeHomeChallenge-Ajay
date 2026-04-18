from __future__ import annotations

import shutil
import time
from pathlib import Path


class FileSystem:
    """File operations for copying the input project and writing generated files."""

    _REFRESH_PATHS: tuple[str, ...] = (
        "public",
        "src",
        ".env.example",
        ".gitignore",
        "index.html",
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "vite-env.d.ts",
        "vite.config.ts",
        "vitest.config.ts",
    )

    def copy_input_to_output(self, input_dir: Path, output_dir: Path) -> None:
        """
        Workflow 4: Refresh the generated app from the boilerplate before writing files.

        Requirement: use shutil.copytree(..., dirs_exist_ok=True).
        """
        # Ensure we don't keep stale files from previous generations.
        # copytree(dirs_exist_ok=True) merges, so we remove the output dir first.
        if output_dir.exists():
            last_err: Exception | None = None
            for _ in range(5):
                try:
                    shutil.rmtree(output_dir)
                    last_err = None
                    break
                except PermissionError as e:
                    last_err = e
                    time.sleep(0.4)
            if last_err is not None:
                self._refresh_output_without_deleting_locked_runtime(input_dir, output_dir)
                return
        shutil.copytree(input_dir, output_dir, dirs_exist_ok=True)

    def write_text(self, path: Path, content: str) -> None:
        """Workflow 5: Write one generated file into the output project."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _refresh_output_without_deleting_locked_runtime(
        self, input_dir: Path, output_dir: Path
    ) -> None:
        """
        Workflow 4A: Refresh source files while preserving locked runtime artifacts.

        This keeps node_modules intact so reruns still work when Windows keeps
        executables like esbuild.exe locked after a dev server or test run.
        """
        for relative_path in self._REFRESH_PATHS:
            target = output_dir / relative_path
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=False)
            elif target.exists():
                target.unlink()

        for relative_path in self._REFRESH_PATHS:
            source = input_dir / relative_path
            target = output_dir / relative_path
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

