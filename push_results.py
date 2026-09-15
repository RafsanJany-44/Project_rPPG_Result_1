#!/usr/bin/env python3

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

RESULTS_PARENT = Path(
    "/media/data/rPPG/Code/GitHub/Project_rPPG_Result"
)

REPOSITORY_URL = (
    "https://github.com/RafsanJany-44/Project_rPPG_Result_1.git"
)

BRANCH = "main"

FOLDER_PREFIX = "Result_Lab_"


# ============================================================
# BATCH SETTINGS
# ============================================================

# Maximum raw local data placed in one Git commit/push.
#
# GitHub limit = 2 GiB per push.
# We deliberately stay far below that limit.
BATCH_MAX_MB = 400

BATCH_MAX_BYTES = (
    BATCH_MAX_MB
    * 1024
    * 1024
)

# Also prevent a batch from containing too many tiny files.
BATCH_MAX_FILES = 1000

# Retry temporary network failures.
MAX_PUSH_RETRIES = 3

# Local result folders are NEVER deleted.
DELETE_LOCAL_RESULTS = False


# ============================================================
# DISPLAY HELPERS
# ============================================================

def human_size(value: int | float) -> str:

    value = float(value)

    for unit in [
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    ]:

        if value < 1024:
            return f"{value:.2f} {unit}"

        value /= 1024

    return f"{value:.2f} PB"


def format_time(seconds: float) -> str:

    if (
        seconds < 0
        or seconds == float("inf")
    ):
        return "--:--"

    seconds = int(seconds)

    hours, remainder = divmod(
        seconds,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    if hours:

        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{seconds:02d}"
        )

    return (
        f"{minutes:02d}:"
        f"{seconds:02d}"
    )


def make_bar(
    percent: float,
    width: int = 30,
) -> str:

    percent = max(
        0,
        min(
            percent,
            100,
        ),
    )

    filled = int(
        width
        * percent
        / 100
    )

    return (
        "█" * filled
        + "-"
        * (
            width
            - filled
        )
    )


# ============================================================
# BASIC GIT COMMAND
# ============================================================

def run_git(
    arguments: list[str],
    cwd: Path | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess:

    command = [
        "git",
        *arguments,
    ]

    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        check=True,
        capture_output=capture_output,
    )


def check_git() -> None:

    result = subprocess.run(
        [
            "git",
            "--version",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    print(
        result.stdout.strip()
    )


# ============================================================
# FIND RESULT FOLDERS
# ============================================================

def find_result_folders() -> list[Path]:

    if not RESULTS_PARENT.exists():

        raise FileNotFoundError(
            f"Folder does not exist:\n"
            f"{RESULTS_PARENT}"
        )

    folders = sorted(
        folder
        for folder
        in RESULTS_PARENT.iterdir()
        if (
            folder.is_dir()
            and folder.name.startswith(
                FOLDER_PREFIX
            )
        )
    )

    return folders


# ============================================================
# FIND ALL FILES
# ============================================================

def get_files(
    folder: Path,
) -> list[tuple[Path, int]]:

    files = []

    for root, dirs, names in os.walk(
        folder
    ):

        # Do not upload nested Git metadata.
        dirs[:] = [
            d
            for d in dirs
            if d != ".git"
        ]

        root_path = Path(root)

        for name in names:

            path = (
                root_path
                / name
            )

            try:

                size = (
                    path.lstat()
                    .st_size
                )

            except OSError:

                size = 0

            files.append(
                (
                    path,
                    size,
                )
            )

    return files


# ============================================================
# SPLIT FILES INTO SAFE BATCHES
# ============================================================

def create_batches(
    files: list[
        tuple[
            Path,
            int,
        ]
    ],
) -> list[
    list[
        tuple[
            Path,
            int,
        ]
    ]
]:

    batches = []

    current = []
    current_size = 0

    for path, size in files:

        need_new_batch = False

        if current:

            if (
                current_size + size
                > BATCH_MAX_BYTES
            ):
                need_new_batch = True

            if (
                len(current)
                >= BATCH_MAX_FILES
            ):
                need_new_batch = True

        if need_new_batch:

            batches.append(
                current
            )

            current = []
            current_size = 0

        current.append(
            (
                path,
                size,
            )
        )

        current_size += size

    if current:

        batches.append(
            current
        )

    return batches


# ============================================================
# LIGHTWEIGHT CLONE
# ============================================================

def clone_repository(
    destination: Path,
) -> None:

    print(
        "\nConnecting to GitHub..."
    )

    subprocess.run(
        [
            "git",
            "clone",
            "--progress",
            "--filter=blob:none",
            "--no-checkout",
            "--single-branch",
            "--branch",
            BRANCH,
            REPOSITORY_URL,
            str(destination),
        ],
        text=True,
        check=True,
    )

    run_git(
        [
            "sparse-checkout",
            "init",
            "--cone",
        ],
        cwd=destination,
    )

    run_git(
        [
            "sparse-checkout",
            "set",
            "__upload_placeholder__",
        ],
        cwd=destination,
    )

    run_git(
        [
            "checkout",
            BRANCH,
        ],
        cwd=destination,
    )


# ============================================================
# COPY ONE BATCH
# ============================================================

def copy_batch(
    batch: list[
        tuple[
            Path,
            int,
        ]
    ],
    source_folder: Path,
    repository: Path,
) -> list[str]:

    paths_for_git = []

    batch_total = sum(
        size
        for _, size
        in batch
    )

    copied = 0
    start = time.time()

    for index, (
        source_file,
        size,
    ) in enumerate(
        batch,
        start=1,
    ):

        relative_inside_folder = (
            source_file.relative_to(
                source_folder
            )
        )

        repository_relative = (
            Path(source_folder.name)
            / relative_inside_folder
        )

        destination = (
            repository
            / repository_relative
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if source_file.is_symlink():

            if (
                destination.exists()
                or destination.is_symlink()
            ):
                destination.unlink()

            target = os.readlink(
                source_file
            )

            os.symlink(
                target,
                destination,
            )

        else:

            shutil.copy2(
                source_file,
                destination,
            )

        copied += size

        paths_for_git.append(
            str(
                repository_relative
            )
        )

        elapsed = max(
            time.time() - start,
            0.001,
        )

        if batch_total > 0:

            percent = (
                copied
                / batch_total
                * 100
            )

        else:

            percent = (
                index
                / len(batch)
                * 100
            )

        speed = (
            copied
            / elapsed
        )

        if percent > 0:

            estimated_total = (
                elapsed
                / (
                    percent
                    / 100
                )
            )

            eta = max(
                0,
                estimated_total
                - elapsed,
            )

        else:

            eta = float("inf")

        bar = make_bar(
            percent
        )

        print(
            "\r"
            f"COPY [{bar}] "
            f"{percent:6.2f}% | "
            f"{index:,}/{len(batch):,} files | "
            f"{human_size(copied)}"
            f"/{human_size(batch_total)} | "
            f"{human_size(speed)}/s | "
            f"ETA {format_time(eta)}",
            end="",
            flush=True,
        )

    print()

    return paths_for_git


# ============================================================
# STAGE FILES
# ============================================================

def stage_paths(
    repository: Path,
    paths: list[str],
) -> None:

    # Split git-add command further to avoid
    # operating-system command-length limits.

    stage_chunk_size = 200

    for start in range(
        0,
        len(paths),
        stage_chunk_size,
    ):

        chunk = paths[
            start:
            start + stage_chunk_size
        ]

        run_git(
            [
                "add",
                "--sparse",
                "--ignore-removal",
                "--",
                *chunk,
            ],
            cwd=repository,
        )


# ============================================================
# CHECK STAGED CHANGES
# ============================================================

def has_staged_changes(
    repository: Path,
) -> bool:

    result = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ],
        cwd=repository,
    )

    if result.returncode == 0:
        return False

    if result.returncode == 1:
        return True

    raise RuntimeError(
        "Unable to check Git changes."
    )


# ============================================================
# PUSH PROGRESS
# ============================================================

def push_with_progress(
    repository: Path,
) -> None:

    command = [
        "git",
        "push",
        "--progress",
        "origin",
        f"{BRANCH}:{BRANCH}",
    ]

    process = subprocess.Popen(
        command,
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    start = time.time()

    output_lines = []
    current = ""

    while True:

        if process.stderr is None:
            break

        char = process.stderr.read(1)

        if (
            char == ""
            and process.poll()
            is not None
        ):

            if current.strip():

                output_lines.append(
                    current.strip()
                )

            break

        if not char:
            continue

        if char not in (
            "\r",
            "\n",
        ):

            current += char
            continue

        line = current.strip()

        current = ""

        if not line:
            continue

        output_lines.append(
            line
        )

        elapsed = (
            time.time()
            - start
        )

        # ------------------------------------------
        # COUNT
        # ------------------------------------------

        match = re.search(
            r"Counting objects:\s+"
            r"(\d+)%"
            r"\s+\((\d+)/(\d+)\)",
            line,
        )

        if match:

            percent = int(
                match.group(1)
            )

            bar = make_bar(
                percent
            )

            print(
                "\r"
                f"COUNT    [{bar}] "
                f"{percent:3d}%",
                end="",
                flush=True,
            )

            if percent == 100:
                print()

            continue

        # ------------------------------------------
        # COMPRESS
        # ------------------------------------------

        match = re.search(
            r"Compressing objects:\s+"
            r"(\d+)%"
            r"\s+\((\d+)/(\d+)\)",
            line,
        )

        if match:

            percent = int(
                match.group(1)
            )

            done = int(
                match.group(2)
            )

            total = int(
                match.group(3)
            )

            bar = make_bar(
                percent
            )

            print(
                "\r"
                f"COMPRESS [{bar}] "
                f"{percent:3d}% | "
                f"{done:,}/{total:,}",
                end="",
                flush=True,
            )

            if percent == 100:
                print()

            continue

        # ------------------------------------------
        # UPLOAD
        # ------------------------------------------

        match = re.search(
            r"Writing objects:\s+"
            r"(\d+)%"
            r"\s+\((\d+)/(\d+)\)"
            r"(?:,\s+([^|]+))?"
            r"(?:\|\s+(.+?))?$",
            line,
        )

        if match:

            percent = int(
                match.group(1)
            )

            done = int(
                match.group(2)
            )

            total = int(
                match.group(3)
            )

            amount = ""

            if match.group(4):

                amount = (
                    match.group(4)
                    .strip()
                )

            speed = ""

            if match.group(5):

                speed = (
                    match.group(5)
                    .strip()
                )

            if percent > 0:

                estimated_total = (
                    elapsed
                    / (
                        percent
                        / 100
                    )
                )

                eta = max(
                    0,
                    estimated_total
                    - elapsed,
                )

            else:

                eta = float("inf")

            bar = make_bar(
                percent
            )

            text = (
                "\r"
                f"PUSH     [{bar}] "
                f"{percent:3d}% | "
                f"{done:,}/{total:,}"
            )

            if amount:

                text += (
                    f" | {amount}"
                )

            if speed:

                text += (
                    f" | {speed}"
                )

            text += (
                f" | Elapsed "
                f"{format_time(elapsed)}"
                f" | ETA "
                f"{format_time(eta)}"
            )

            print(
                text,
                end="",
                flush=True,
            )

            if percent == 100:
                print()

            continue

        lower = line.lower()

        if (
            "fatal:" in lower
            or "error:" in lower
            or "rejected" in lower
            or line.startswith("remote:")
            or line.startswith("To ")
        ):

            print()
            print(line)

    return_code = (
        process.wait()
    )

    if return_code != 0:

        print()
        print(
            "=" * 70
        )

        print(
            "GIT PUSH ERROR"
        )

        print(
            "=" * 70
        )

        for line in output_lines:

            print(line)

        raise subprocess.CalledProcessError(
            return_code,
            command,
        )

    print()


# ============================================================
# VERIFY REMOTE HEAD
# ============================================================

def remote_has_commit(
    repository: Path,
) -> bool:

    local_commit = (
        subprocess.run(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=repository,
            text=True,
            capture_output=True,
            check=True,
        )
        .stdout
        .strip()
    )

    result = subprocess.run(
        [
            "git",
            "ls-remote",
            "origin",
            f"refs/heads/{BRANCH}",
        ],
        cwd=repository,
        text=True,
        capture_output=True,
        check=True,
    )

    remote_output = (
        result.stdout
        .strip()
    )

    if not remote_output:
        return False

    remote_commit = (
        remote_output
        .split()[0]
    )

    return (
        local_commit
        == remote_commit
    )


# ============================================================
# PUSH WITH RETRY
# ============================================================

def push_with_retry(
    repository: Path,
) -> None:

    for attempt in range(
        1,
        MAX_PUSH_RETRIES + 1,
    ):

        print(
            f"\nPush attempt "
            f"{attempt}/"
            f"{MAX_PUSH_RETRIES}"
        )

        try:

            push_with_progress(
                repository
            )

            if remote_has_commit(
                repository
            ):

                print(
                    "✓ REMOTE VERIFY PASSED"
                )

                print(
                    "✓ Batch is safely on GitHub"
                )

                return

            raise RuntimeError(
                "Push finished but remote "
                "verification failed."
            )

        except Exception as error:

            # Sometimes Git reports a network
            # error after GitHub already accepted
            # the commit. Check before retrying.

            try:

                if remote_has_commit(
                    repository
                ):

                    print()
                    print(
                        "✓ Git reported an error,"
                    )

                    print(
                        "  but remote verification "
                        "shows the commit is already "
                        "on GitHub."
                    )

                    print(
                        "✓ Batch is safe."
                    )

                    return

            except Exception:

                pass

            if (
                attempt
                >= MAX_PUSH_RETRIES
            ):

                raise error

            print()
            print(
                "Push failed."
            )

            print(
                "Retrying in 5 seconds..."
            )

            time.sleep(5)


# ============================================================
# CLEAN TEMP COPIED FILES
# ============================================================

def remove_temp_batch_files(
    repository: Path,
    paths: list[str],
) -> None:

    for path_string in paths:

        path = (
            repository
            / path_string
        )

        try:

            if path.is_symlink():
                path.unlink()

            elif path.is_file():
                path.unlink()

        except OSError:

            pass


# ============================================================
# PROCESS ONE RESULT FOLDER
# ============================================================

def process_folder(
    source_folder: Path,
    folder_number: int,
    folder_total: int,
) -> None:

    print()
    print(
        "=" * 70
    )

    print(
        f"FOLDER "
        f"{folder_number}/"
        f"{folder_total}"
    )

    print(
        source_folder.name
    )

    print(
        "=" * 70
    )

    files = get_files(
        source_folder
    )

    total_size = sum(
        size
        for _, size
        in files
    )

    print(
        f"\nFiles : "
        f"{len(files):,}"
    )

    print(
        f"Size  : "
        f"{human_size(total_size)}"
    )

    if not files:

        print(
            "Empty folder - skipped."
        )

        return

    batches = create_batches(
        files
    )

    print(
        f"Batches: "
        f"{len(batches)}"
    )

    print(
        f"Maximum batch size: "
        f"{BATCH_MAX_MB} MB"
    )

    with tempfile.TemporaryDirectory(
        prefix="rppg_git_batch_"
    ) as temporary_directory:

        repository = (
            Path(temporary_directory)
            / "repository"
        )

        clone_repository(
            repository
        )

        folder_start = (
            time.time()
        )

        processed_bytes = 0

        for batch_number, batch in enumerate(
            batches,
            start=1,
        ):

            batch_size = sum(
                size
                for _, size
                in batch
            )

            print()
            print(
                "-" * 70
            )

            print(
                f"BATCH "
                f"{batch_number}/"
                f"{len(batches)}"
            )

            print(
                f"Files: "
                f"{len(batch):,}"
            )

            print(
                f"Raw size: "
                f"{human_size(batch_size)}"
            )

            print(
                "-" * 70
            )

            paths = copy_batch(
                batch=batch,
                source_folder=source_folder,
                repository=repository,
            )

            print(
                "\nChecking changes..."
            )

            stage_paths(
                repository,
                paths,
            )

            if not has_staged_changes(
                repository
            ):

                print(
                    "✓ No changes in this batch."
                )

                print(
                    "✓ Skipped."
                )

                remove_temp_batch_files(
                    repository,
                    paths,
                )

                processed_bytes += (
                    batch_size
                )

                continue

            timestamp = (
                datetime.now()
                .strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )

            commit_message = (
                f"Update "
                f"{source_folder.name} "
                f"batch "
                f"{batch_number}/"
                f"{len(batches)} "
                f"({timestamp})"
            )

            run_git(
                [
                    "commit",
                    "-m",
                    commit_message,
                ],
                cwd=repository,
            )

            print(
                "\nUploading batch..."
            )

            push_with_retry(
                repository
            )

            processed_bytes += (
                batch_size
            )

            elapsed = (
                time.time()
                - folder_start
            )

            if total_size > 0:

                overall_percent = (
                    processed_bytes
                    / total_size
                    * 100
                )

            else:

                overall_percent = 100

            if overall_percent > 0:

                estimated_total = (
                    elapsed
                    / (
                        overall_percent
                        / 100
                    )
                )

                overall_eta = max(
                    0,
                    estimated_total
                    - elapsed,
                )

            else:

                overall_eta = (
                    float("inf")
                )

            bar = make_bar(
                overall_percent
            )

            print()
            print(
                f"OVERALL "
                f"[{bar}] "
                f"{overall_percent:6.2f}%"
            )

            print(
                f"Processed: "
                f"{human_size(processed_bytes)}"
                f"/{human_size(total_size)}"
            )

            print(
                f"Elapsed: "
                f"{format_time(elapsed)}"
            )

            print(
                f"Estimated remaining: "
                f"{format_time(overall_eta)}"
            )

            # Remove only TEMPORARY copy.
            # Original result is untouched.
            remove_temp_batch_files(
                repository,
                paths,
            )

        print()
        print(
            "=" * 70
        )

        print(
            f"✓ COMPLETED:"
        )

        print(
            source_folder.name
        )

        print(
            "=" * 70
        )


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    print()
    print(
        "=" * 70
    )

    print(
        "rPPG RESULT → GITHUB"
    )

    print(
        "SAFE BATCH UPLOADER"
    )

    print(
        "=" * 70
    )

    print(
        f"\nSource:"
        f"\n{RESULTS_PARENT}"
    )

    print(
        f"\nGitHub:"
        f"\n{REPOSITORY_URL}"
    )

    print(
        f"\nBatch maximum:"
        f"\n{BATCH_MAX_MB} MB"
    )

    print(
        "\nLocal result deletion: NEVER"
    )

    print(
        "\nExisting GitHub folders: UPDATE"
    )

    print(
        "\nUnchanged files: SKIP"
    )

    print(
        "\nMissing local files: "
        "DO NOT DELETE FROM GITHUB"
    )

    check_git()

    folders = (
        find_result_folders()
    )

    if not folders:

        print(
            "\nNo result folders found."
        )

        return 0

    print()
    print(
        f"Found "
        f"{len(folders)} "
        f"result folder(s):"
    )

    for folder in folders:

        files = get_files(
            folder
        )

        size = sum(
            value
            for _, value
            in files
        )

        print(
            f"  - {folder.name}"
            f"  [{human_size(size)}]"
        )

    for number, folder in enumerate(
        folders,
        start=1,
    ):

        try:

            process_folder(
                source_folder=folder,
                folder_number=number,
                folder_total=len(folders),
            )

        except Exception:

            print()
            print(
                "=" * 70
            )

            print(
                "UPLOAD STOPPED"
            )

            print(
                "=" * 70
            )

            print(
                f"Problem folder:"
                f"\n{folder.name}"
            )

            print(
                "\nPrevious successful "
                "batches remain on GitHub."
            )

            print(
                "\nOriginal local results "
                "remain untouched."
            )

            raise

    print()
    print(
        "=" * 70
    )

    print(
        "✓ ALL RESULT FOLDERS FINISHED"
    )

    print(
        "=" * 70
    )

    print(
        "\n✓ Local results were NOT deleted."
    )

    print(
        "✓ Every successful batch was "
        "verified against GitHub."
    )

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        raise SystemExit(
            main()
        )

    except subprocess.CalledProcessError as error:

        print()
        print(
            "=" * 70,
            file=sys.stderr,
        )

        print(
            "UPLOAD FAILED",
            file=sys.stderr,
        )

        print(
            "=" * 70,
            file=sys.stderr,
        )

        print(
            f"Git exit code: "
            f"{error.returncode}",
            file=sys.stderr,
        )

        print(
            "\nNO ORIGINAL RESULT "
            "WAS DELETED.",
            file=sys.stderr,
        )

        raise SystemExit(1)

    except KeyboardInterrupt:

        print(
            "\n\nSTOPPED BY USER",
            file=sys.stderr,
        )

        print(
            "Original results are safe.",
            file=sys.stderr,
        )

        raise SystemExit(130)

    except Exception as error:

        print()
        print(
            "=" * 70,
            file=sys.stderr,
        )

        print(
            "UPLOAD FAILED",
            file=sys.stderr,
        )

        print(
            "=" * 70,
            file=sys.stderr,
        )

        print(
            str(error),
            file=sys.stderr,
        )

        print(
            "\nNO ORIGINAL RESULT "
            "WAS DELETED.",
            file=sys.stderr,
        )

        raise SystemExit(1)