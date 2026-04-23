from .dreamina_cli_node import DreaminaCLI_VideoGenerator, DreaminaCLI_Login

NODE_CLASS_MAPPINGS = {
    "DreaminaCLI_VideoGenerator": DreaminaCLI_VideoGenerator,
    "DreaminaCLI_Login": DreaminaCLI_Login,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DreaminaCLI_VideoGenerator": "🎬 Dreamina CLI Video Generator",
    "DreaminaCLI_Login": "🔐 Dreamina CLI Login",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

# ── Auto-install CLI on Linux / macOS ───────────────────────────────────────
import os
import subprocess
import platform


def install_dreamina_cli():
    system = platform.system()
    if system not in ("Linux", "Darwin"):
        return
    # Already on PATH?
    if os.system("which dreamina > /dev/null 2>&1") == 0:
        return
    try:
        subprocess.run(
            "curl -fsSL https://jimeng.jianying.com/cli | bash",
            shell=True, check=True, timeout=120,
        )
    except Exception:
        pass


install_dreamina_cli()
