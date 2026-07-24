#!/usr/bin/env python3
import importlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path


REALESRGAN_RUNTIME_DEPS = [
    "basicsr>=1.4.2",
    "numpy<2",
    "opencv-python<4.11",
    "Pillow",
    "torch>=1.7",
    "torchvision",
    "tqdm",
]


def get_realesrgan_dir(base_dir: Path) -> Path:
    return Path(base_dir) / "tools" / "Real-ESRGAN"


def get_realesrgan_inference_script(base_dir: Path) -> Path:
    return get_realesrgan_dir(base_dir) / "inference_realesrgan.py"


def is_realesrgan_installed(base_dir: Path) -> bool:
    repo_dir = get_realesrgan_dir(base_dir)
    script_path = repo_dir / "inference_realesrgan.py"
    if not script_path.exists():
        return False
    try:
        importlib.metadata.version("realesrgan")
    except importlib.metadata.PackageNotFoundError:
        return False
    except Exception:
        return False
    return True


def install_realesrgan(base_dir: Path, python_executable: str | None = None) -> None:
    python_executable = python_executable or sys.executable
    repo_dir = get_realesrgan_dir(base_dir)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not shutil.which("git"):
        raise RuntimeError("git не найден. Установите git перед установкой Real-ESRGAN.")

    if not repo_dir.exists():
        subprocess.run(
            ["git", "clone", "https://github.com/xinntao/Real-ESRGAN.git", str(repo_dir)],
            check=True,
        )
    else:
        subprocess.run(["git", "-C", str(repo_dir), "fetch", "--all", "--tags"], check=True)
        subprocess.run(["git", "-C", str(repo_dir), "pull", "--ff-only"], check=True)

    subprocess.run(
        [python_executable, "-m", "pip", "install", *REALESRGAN_RUNTIME_DEPS],
        check=True,
    )
    subprocess.run(
        [python_executable, "-m", "pip", "install", "-e", str(repo_dir), "--no-deps"],
        check=True,
    )
    ensure_torchvision_functional_tensor_shim(python_executable)


def ensure_torchvision_functional_tensor_shim(python_executable: str | None = None) -> None:
    python_executable = python_executable or sys.executable
    shim_code = """
from pathlib import Path
import torchvision

root = Path(torchvision.__file__).resolve().parent / "transforms"
legacy = root / "functional_tensor.py"
modern = root / "_functional_tensor.py"

if not legacy.exists() and modern.exists():
    legacy.write_text("from ._functional_tensor import *\\n", encoding="utf-8")
    print(f"Created torchvision shim: {legacy}")
else:
    print(f"Torchvision shim OK: {legacy}")
"""
    subprocess.run([python_executable, "-c", shim_code], check=True)


def build_realesrgan_cmd(
    base_dir: Path,
    input_path: Path,
    output_dir: Path,
    scale: int = 2,
) -> list[str]:
    if scale not in (2, 4):
        raise ValueError("scale must be 2 or 4")

    model_name = "RealESRGAN_x2plus" if scale == 2 else "RealESRGAN_x4plus"
    return [
        sys.executable,
        str(get_realesrgan_inference_script(base_dir)),
        "-i",
        str(input_path),
        "-o",
        str(output_dir),
        "-n",
        model_name,
        "-s",
        str(scale),
        "--suffix",
        "",
        "--ext",
        "auto",
        "--fp32",
    ]


def resolve_upscaled_output(output_dir: Path, source_name: str) -> Path | None:
    direct = output_dir / source_name
    if direct.exists():
        return direct

    source_stem = Path(source_name).stem
    matches = sorted(output_dir.glob(f"{source_stem}.*"))
    return matches[0] if matches else None


def replace_source_with_upscaled(source_path: Path, upscaled_path: Path, backup_dir: Path | None = None) -> Path:
    final_path = source_path

    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / source_path.name
        if backup_path.exists():
            backup_path.unlink()
        source_path.replace(backup_path)
    else:
        source_path.unlink()

    for candidate in source_path.parent.glob(f"{source_path.stem}.*"):
        if candidate.is_file() and candidate != upscaled_path and candidate != final_path:
            candidate.unlink()
    upscaled_path.replace(final_path)
    return final_path
