"""
JAN (Joint Autonomous Neural Agent) — PyInstaller Build Script
Packages JAN as a standalone Windows EXE.

Usage:
    python build_exe.py
"""

import subprocess
import sys
import os


def build():
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--name', 'JAN',
        '--console',
        '--add-data', 'config.yaml;.',
        '--add-data', 'modules;modules',
    ]

    # Include generated modules subdir if it exists
    if os.path.isdir('modules/generated'):
        cmd.extend(['--add-data', 'modules/generated;modules/generated'])

    # Set icon if available
    if os.path.exists('assets/jan_icon.ico'):
        cmd.extend(['--icon', 'assets/jan_icon.ico'])

    # Hidden imports — packages that PyInstaller can't detect statically
    hidden_imports = [
        'edge_tts',
        'chromadb',
        'face_recognition',
        'easyocr',
        'resemblyzer',
        'psutil',
        'websockets',
        'playwright',
        'cv2',
        'numpy',
        'PIL',
        'yaml',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'starlette',
        'pydantic',
        'requests',
        'httpx',
        'anyio',
        'sniffio',
    ]
    for h in hidden_imports:
        cmd.extend(['--hidden-import', h])

    # Version info resource
    _write_version_file()
    if os.path.exists('version_info.txt'):
        cmd.extend(['--version-file', 'version_info.txt'])

    # Entry point
    cmd.append('main.py')

    print("=" * 50)
    print("  Building JAN.exe ...")
    print("=" * 50)
    print(f"Command: {' '.join(cmd)}\n")

    subprocess.run(cmd, check=True)

    print()
    print("=" * 50)
    print("  Build complete!  Output: dist/JAN.exe")
    print("=" * 50)

    # Clean up version file
    if os.path.exists('version_info.txt'):
        os.remove('version_info.txt')


def _write_version_file():
    """Generate a Windows version-info resource file for PyInstaller."""
    version_info = r"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'JAN Project'),
            StringStruct(u'FileDescription', u'JAN - Joint Autonomous Neural Agent'),
            StringStruct(u'FileVersion', u'1.0.0.0'),
            StringStruct(u'InternalName', u'JAN'),
            StringStruct(u'OriginalFilename', u'JAN.exe'),
            StringStruct(u'ProductName', u'JAN'),
            StringStruct(u'ProductVersion', u'1.0.0.0'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    with open('version_info.txt', 'w', encoding='utf-8') as f:
        f.write(version_info)


if __name__ == '__main__':
    build()
