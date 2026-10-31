"""
Build script for FastMirror.

Automates:
1. PyInstaller standalone compilation (`packaging/fastmirror.spec`).
2. Packaging portable ZIP archive (`dist/FastMirror-v<version>-Windows-Portable.zip`).
3. Compiling Inno Setup installer wizard if `iscc` is available (`dist/FastMirror-v<version>-Windows-Setup.exe`).
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DIST_DIR = os.path.join(ROOT_DIR, 'dist')
BUILD_DIR = os.path.join(ROOT_DIR, 'build')
SPEC_FILE = os.path.join(ROOT_DIR, 'packaging', 'fastmirror.spec')
ISS_FILE = os.path.join(ROOT_DIR, 'packaging', 'installer.iss')


def get_version() -> str:
    pyproject = os.path.join(ROOT_DIR, 'pyproject.toml')
    with open(pyproject, encoding='utf-8') as f:
        for line in f:
            if line.strip().startswith('version'):
                match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', line)
                if match:
                    return match.group(1)
    return '1.0.0'


def find_iscc() -> str | None:
    # Check PATH first
    iscc = shutil.which('iscc') or shutil.which('ISCC.exe')
    if iscc:
        return iscc
    # Check default Inno Setup installation paths on Windows
    common_paths = [
        r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        r'C:\Program Files\Inno Setup 6\ISCC.exe',
        r'C:\Program Files (x86)\Inno Setup 5\ISCC.exe',
        r'C:\Program Files\Inno Setup 5\ISCC.exe',
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path
    return None


def main() -> None:
    version = get_version()
    print(f'=== Building FastMirror v{version} ===')

    # 1. Run PyInstaller
    print('\n[1/3] Running PyInstaller...')
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', SPEC_FILE]
    subprocess.run(cmd, cwd=ROOT_DIR, check=True)

    target_dist_dir = os.path.join(DIST_DIR, 'FastMirror')
    if not os.path.isdir(target_dist_dir):
        print(f'Error: Expected build folder not found at {target_dist_dir}', file=sys.stderr)
        sys.exit(1)

    # 2. Add portable marker & copy example config into dist folder
    portable_marker = os.path.join(target_dist_dir, 'portable.txt')
    with open(portable_marker, 'w', encoding='utf-8') as f:
        f.write('FastMirror Portable Mode\n')

    # Create Portable ZIP archive
    print('\n[2/3] Creating Portable ZIP archive...')
    zip_filename = f'FastMirror-v{version}-Windows-Portable.zip'
    zip_path = os.path.join(DIST_DIR, zip_filename)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(target_dist_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, DIST_DIR)
                zf.write(full_path, rel_path)
    print(f'Portable archive ready: {zip_path}')

    # Remove portable marker from dist directory before building setup installer
    if os.path.isfile(portable_marker):
        os.remove(portable_marker)

    # 3. Compile Inno Setup installer if iscc is found
    print('\n[3/3] Checking for Inno Setup compiler (ISCC)...')
    iscc_path = find_iscc()
    if iscc_path and os.path.isfile(ISS_FILE):
        print(f'Found Inno Setup at: {iscc_path}')
        print('Compiling Windows Setup Wizard...')
        subprocess.run(
            [iscc_path, f'/DAppVersion={version}', ISS_FILE],
            cwd=ROOT_DIR,
            check=True,
        )
        print('Installer Wizard built successfully!')
    else:
        print('Inno Setup compiler (ISCC.exe) not found on host. (Skipping local setup installer build).')
        print('Note: The GitHub Actions CI/CD pipeline will automatically build the installer using ISCC.')

    print(f'\n=== Build Completed Successfully for v{version} ===')


if __name__ == '__main__':
    main()
