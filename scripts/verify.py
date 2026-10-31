#!/usr/bin/env python3
"""
Unified verification script for FastMirror.

Runs all linting, formatting, type checking, test suites, privacy checks,
and version/changelog validations identically both locally and in CI.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

# Ensure robust UTF-8 console output across Windows cp1252 and Linux/macOS
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ANSI Color Codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
BOLD = '\033[1m'
RESET = '\033[0m'


def log_header(title: str) -> None:
    print(f'\n{BOLD}{CYAN}=== {title} ==={RESET}')


def log_step(name: str) -> None:
    print(f'[*] {BOLD}{name}{RESET}...', flush=True)


def log_success(msg: str) -> None:
    print(f'{GREEN}[+] {msg}{RESET}')


def log_error(msg: str) -> None:
    print(f'{RED}[-] {msg}{RESET}', file=sys.stderr)


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cmd(cmd: list[str], desc: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    log_step(desc)
    start = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    duration = time.perf_counter() - start

    if res.returncode == 0:
        log_success(f'{desc} passed ({duration:.2f}s)')
        return res

    log_error(f'{desc} failed with exit code {res.returncode} ({duration:.2f}s)')
    if res.stdout.strip():
        print(f'\n{res.stdout.strip()}')
    if res.stderr.strip():
        print(f'\n{res.stderr.strip()}', file=sys.stderr)

    if check:
        sys.exit(res.returncode)
    return res


def check_formatting(fix: bool) -> None:
    cmd = ['uv', 'run', 'ruff', 'format']
    if not fix:
        cmd.append('--check')
    cmd.append('.')
    desc = 'Auto-formatting code (Ruff)' if fix else 'Checking code formatting (Ruff)'
    run_cmd(cmd, desc)


def check_linter(fix: bool) -> None:
    cmd = ['uv', 'run', 'ruff', 'check']
    if fix:
        cmd.append('--fix')
    cmd.append('.')
    desc = 'Fixing lint issues (Ruff)' if fix else 'Running static linter (Ruff)'
    run_cmd(cmd, desc)


def check_types() -> None:
    run_cmd(['uv', 'run', 'python', '-m', 'mypy', 'src'], 'Running type checker (Mypy)')


def check_privacy_and_paths() -> None:
    log_step('Checking privacy hygiene & local path prevention')
    start = time.perf_counter()
    forbidden_patterns = [
        ('Windows User Profile Path', re.compile(r'[a-zA-Z]:[/\\]+Users[/\\]+(?!Username[/\\])', re.IGNORECASE)),
        (
            'Windows Personal Folder Path',
            re.compile(r'[a-zA-Z]:[/\\]+Rafael[/\\]+', re.IGNORECASE),
        ),
        (
            'AI Assistant Brain/Artifact Path',
            re.compile(
                r'(?:\.gemini[/\\]+antigravity|antigravity[/\\]+brain|brain[/\\]+[0-9a-fA-F-]{36})',
                re.IGNORECASE,
            ),
        ),
        (
            'Private Local Subnet (non-example)',
            re.compile(r'192\.168\.178\.\d+', re.IGNORECASE),
        ),
    ]
    excluded_files = {'scripts/verify.py'}

    try:
        res = subprocess.run(
            ['git', 'ls-files'],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )
        tracked = [REPO_ROOT / f.strip() for f in res.stdout.splitlines() if f.strip()]
    except Exception:
        ignored_dirs = {'.git', '.venv', '__pycache__', 'dist', 'build', 'data', 'scratch'}
        tracked = [p for p in REPO_ROOT.rglob('*') if p.is_file() and not any(part in ignored_dirs for part in p.parts)]

    violations: list[str] = []
    for file_path in tracked:
        rel = str(file_path.relative_to(REPO_ROOT)).replace('\\', '/')
        if rel in excluded_files:
            continue
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        for line_no, line in enumerate(content.splitlines(), 1):
            for rule_name, pattern in forbidden_patterns:
                if pattern.search(line):
                    violations.append(f'  [{rule_name}] {rel}:{line_no} -> {line.strip()[:100]}')

    duration = time.perf_counter() - start
    if violations:
        log_error(f'Privacy check failed: {len(violations)} hardcoded local path(s) detected ({duration:.2f}s):')
        for v in violations:
            print(v, file=sys.stderr)
        print(
            '\nPlease remove personal usernames, user directories, or artifact paths.\n',
            file=sys.stderr,
        )
        sys.exit(1)

    log_success(f'Privacy hygiene check passed ({duration:.2f}s)')


def run_tests(pytest_args: list[str] | None = None) -> None:
    cmd = ['uv', 'run', 'pytest']
    if pytest_args:
        cmd.extend(pytest_args)
    run_cmd(cmd, 'Running test suite (Pytest)')


def validate_version_and_changelog() -> None:
    log_step('Validating version & CHANGELOG.md consistency')

    pyproject_path = REPO_ROOT / 'pyproject.toml'
    if not pyproject_path.exists():
        log_error('pyproject.toml not found!')
        sys.exit(1)

    import tomllib

    with pyproject_path.open('rb') as f:
        version_str = tomllib.load(f)['project']['version']

    # Validate version format
    if not re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', version_str):
        log_error(f"Version '{version_str}' does not follow strict MAJOR.MINOR.PATCH format (e.g. 0.1.0).")
        sys.exit(1)

    changelog_path = REPO_ROOT / 'CHANGELOG.md'
    if not changelog_path.exists():
        log_error('CHANGELOG.md not found!')
        sys.exit(1)

    changelog_content = changelog_path.read_text(encoding='utf-8')
    header_pattern = rf'##\s*\[?v?{re.escape(version_str)}\]?'
    if not re.search(header_pattern, changelog_content):
        log_error(
            f"Version '{version_str}' from pyproject.toml was not found in CHANGELOG.md!\n"
            f"Please document release changes under '## [{version_str}] - YYYY-MM-DD' in CHANGELOG.md."
        )
        sys.exit(1)

    notes_pattern = rf'##\s*\[?v?{re.escape(version_str)}\]?[^\n]*\n(.*?)(?=\n##\s*\[|\Z)'
    notes_match = re.search(notes_pattern, changelog_content, re.DOTALL)
    if not notes_match or not notes_match.group(1).strip():
        log_error(f"Release section for '[{version_str}]' in CHANGELOG.md is empty!")
        sys.exit(1)

    log_success(f'Version {version_str} and CHANGELOG.md entry verified!')


def main() -> None:
    parser = argparse.ArgumentParser(description='FastMirror verification suite.')
    parser.add_argument('--fix', action='store_true', help='Automatically apply safe format and lint fixes')
    parser.add_argument(
        '--check-version', action='store_true', help='Enforce pyproject.toml version & CHANGELOG.md check'
    )
    parser.add_argument('--ci', action='store_true', help='Run full strict CI validation mode')
    parser.add_argument('--skip-tests', action='store_true', help='Skip test suite execution')
    args = parser.parse_args()

    log_header('FastMirror Codebase Verification')
    start_time = time.perf_counter()

    check_formatting(fix=args.fix)
    check_linter(fix=args.fix)
    check_types()
    check_privacy_and_paths()

    if args.ci or args.check_version:
        validate_version_and_changelog()

    if not args.skip_tests:
        run_tests()

    total_time = time.perf_counter() - start_time
    log_header(f'All Checks Passed Successfully ({total_time:.2f}s)')


if __name__ == '__main__':
    main()
