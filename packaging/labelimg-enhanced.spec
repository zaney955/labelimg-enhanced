# PyInstaller onedir contract for the managed Windows distribution.

from pathlib import Path
from importlib.metadata import distribution
from runpy import run_path


repository_root = Path(SPECPATH).parent
package_root = repository_root / "src" / "labelimg"
local_package_modules = run_path(
    str(repository_root / "tools" / "pyinstaller_modules.py")
)["local_package_modules"]


def license_data(distribution_name):
    package = distribution(distribution_name)
    data = []
    for relative in package.files or ():
        name = Path(str(relative)).name.upper()
        if not name.startswith(("LICENSE", "COPYING", "NOTICE")):
            continue
        source = package.locate_file(relative)
        destination = (
            Path("third_party_licenses")
            / distribution_name
            / Path(str(relative)).parent
        )
        data.append((str(source), str(destination)))
    return data


dependency_licenses = []
for dependency in (
    "PyQt5-Qt5",
    "PyQt5-sip",
    "lxml",
    "PyYAML",
    "numpy",
    "opencv-python-headless",
    "Pillow",
    "comtypes",
):
    dependency_licenses.extend(license_data(dependency))

a = Analysis(
    [str(repository_root / "src" / "labelimg" / "__main__.py")],
    pathex=[str(repository_root / "src")],
    binaries=[],
    datas=[
        (
            str(repository_root / "src" / "labelimg" / "data" / "predefined_classes.txt"),
            "labelimg/data",
        ),
        (
            str(repository_root / "src" / "labelimg" / "data" / "app.ico"),
            "labelimg/data",
        ),
    ] + dependency_licenses,
    hiddenimports=local_package_modules(package_root),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabelImgEnhanced",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(repository_root / "resources" / "icons" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LabelImgEnhanced",
)
