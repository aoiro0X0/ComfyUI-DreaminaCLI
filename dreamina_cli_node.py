import os
import json
import time
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

import torch
import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

# ── Paths ────────────────────────────────────────────────────────────────────
NODE_DIR = Path(__file__).parent
DEFAULT_DATA_DIR = NODE_DIR / "data"
DEFAULT_OUTPUT_DIR = Path(tempfile.gettempdir()) / "dreamina_cli_output"
DEVICE_CODE_FILE = NODE_DIR / ".device_code.json"


# ── Find executable ──────────────────────────────────────────────────────────
def _find_dreamina_exe() -> Optional[str]:
    env_path = os.environ.get("DREAMINA_EXE")
    if env_path and Path(env_path).exists():
        return str(Path(env_path))
    # On Windows, npm creates a .CMD wrapper; prefer the real .exe.
    if os.name == "nt":
        candidates_win = [
            Path.home() / "bin" / "dreamina.exe",
            Path.home() / ".local" / "bin" / "dreamina.exe",
            Path("C:/Users/Admin/bin/dreamina.exe"),
        ]
        for c in candidates_win:
            if c.exists():
                return str(c)
    import shutil
    found = shutil.which("dreamina")
    if found:
        # If it is a Windows script wrapper, try to find the real binary next to it.
        p = Path(found)
        if p.suffix.lower() in (".cmd", ".bat", ".ps1"):
            real = p.with_suffix(".exe")
            if real.exists():
                return str(real)
            # npm global: wrapper sits in Roaming/npm, binary in same-named folder
            sibling = p.parent / p.stem / "dreamina.exe"
            if sibling.exists():
                return str(sibling)
        return found
    candidates = [
        Path.home() / ".local" / "bin" / "dreamina",
        Path.home() / "bin" / "dreamina",
        Path("/usr/local/bin/dreamina"),
        Path("/usr/bin/dreamina"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ── Env helpers ──────────────────────────────────────────────────────────────
def _make_env(data_dir: Optional[Path] = None) -> Dict[str, str]:
    """Prepare env so the CLI reads/writes token under data_dir."""
    env = os.environ.copy()
    target = str(data_dir) if data_dir else str(DEFAULT_DATA_DIR)
    # Linux / macOS
    env["HOME"] = target
    # Windows (CLI also respects USERPROFILE on Win)
    env["USERPROFILE"] = target
    return env


def _data_dir_for(data_dir_str: str = "") -> Path:
    if data_dir_str and data_dir_str.strip():
        return Path(data_dir_str).expanduser().resolve()
    return DEFAULT_DATA_DIR


# ── Run CLI ──────────────────────────────────────────────────────────────────
def _run_cli(cmd: list, data_dir: Optional[Path] = None, timeout: int = 60) -> Tuple[int, str, str]:
    env = _make_env(data_dir)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        return -1, e.stdout or "", e.stderr or ""


# ── Login state ──────────────────────────────────────────────────────────────
def _is_logged_in(dreamina_exe: str, data_dir: Optional[Path] = None) -> bool:
    """Use user_credit to probe whether we have a valid token."""
    rc, out, err = _run_cli([dreamina_exe, "user_credit"], data_dir, timeout=15)
    combined = (out or "") + (err or "")
    if "未检测到有效登录态" in combined or "请先执行 dreamina login" in combined:
        return False
    # If we got a credit number or any normal output, consider logged in
    return rc == 0


# ── Headless login ───────────────────────────────────────────────────────────
def _login_headless(dreamina_exe: str, data_dir: Optional[Path] = None) -> Dict[str, str]:
    """Run `dreamina login --headless` and parse the OAuth material."""
    rc, out, err = _run_cli([dreamina_exe, "login", "--headless"], data_dir, timeout=30)
    combined = (out or "") + (err or "")
    if rc != 0 and not ("verification_uri" in combined):
        raise RuntimeError(f"login --headless failed: {combined}")

    # Parse fields from one-line output:
    # verification_uri: <url> user_code: <code> device_code: <code> poll_interval: <dur> expires_at: <iso>
    data = {}
    for key in ("verification_uri", "user_code", "device_code", "poll_interval", "expires_at"):
        m = re.search(rf"{key}:\s*(\S+)", combined)
        if m:
            data[key] = m.group(1)
    if "device_code" not in data:
        raise RuntimeError(f"Could not parse device_code from: {combined}")
    return data


def _check_login(dreamina_exe: str, device_code: str, data_dir: Optional[Path] = None) -> bool:
    """Poll for authorization completion."""
    rc, out, err = _run_cli(
        [dreamina_exe, "login", "checklogin", f"--device_code={device_code}", "--poll=30"],
        data_dir,
        timeout=45,
    )
    combined = (out or "") + (err or "")
    # Success indicator: no "未检测到有效登录态" and no "超时"
    if "超时" in combined or "请重试" in combined:
        return False
    if "未检测到有效登录态" in combined or "请先执行 dreamina login" in combined:
        return False
    return rc == 0


# ── Save / load device code ──────────────────────────────────────────────────
def _save_device_code(data: Dict[str, str]) -> None:
    try:
        with open(DEVICE_CODE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _load_device_code() -> Optional[Dict[str, str]]:
    try:
        if DEVICE_CODE_FILE.exists():
            with open(DEVICE_CODE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _clear_device_code() -> None:
    try:
        if DEVICE_CODE_FILE.exists():
            DEVICE_CODE_FILE.unlink()
    except Exception:
        pass


# ── Image helpers ────────────────────────────────────────────────────────────
def _save_comfy_image(image_tensor, filepath: Path):
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if image_tensor.ndim == 4:
        img_np = image_tensor[0].cpu().numpy()
    else:
        img_np = image_tensor.cpu().numpy()
    img_np = (np.clip(img_np, 0.0, 1.0) * 255).astype(np.uint8)
    pil_img = Image.fromarray(img_np)
    pil_img.save(str(filepath), "PNG")
    return str(filepath)


# ── Task submit / query / download ───────────────────────────────────────────
def _dreamina_submit(dreamina_exe, prompt, image_paths, model_version, ratio, duration, video_resolution, data_dir=None):
    cmd = [
        dreamina_exe, "multimodal2video",
        "--prompt", prompt,
        "--model_version", model_version,
        "--ratio", ratio,
        "--duration", str(duration),
        "--video_resolution", video_resolution,
    ]
    for p in image_paths:
        cmd.extend(["--image", str(p)])

    rc, out, err = _run_cli(cmd, data_dir, timeout=60)
    combined = (out or "") + (err or "")
    if rc != 0:
        raise RuntimeError(f"Dreamina submit failed: {combined}")
    return json.loads(out)


def _dreamina_query_status(dreamina_exe, submit_id, data_dir=None):
    rc, out, err = _run_cli([dreamina_exe, "query_result", f"--submit_id={submit_id}"], data_dir, timeout=30)
    if rc != 0:
        return "unknown"
    m = re.search(r'"gen_status"\s*:\s*"([^"]+)"', out)
    return m.group(1) if m else "unknown"


def _dreamina_download(dreamina_exe, submit_id, output_dir, data_dir=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        dreamina_exe, "query_result",
        f"--submit_id={submit_id}",
        f"--download_dir={output_dir}",
    ]
    rc, out, err = _run_cli(cmd, data_dir, timeout=120)
    if rc != 0:
        return None
    try:
        data = json.loads(out)
        videos = data.get("result_json", {}).get("videos", [])
        for v in videos:
            p = v.get("path")
            if p and os.path.exists(p):
                return p
    except Exception:
        pass
    mp4s = sorted(output_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(mp4s[0]) if mp4s else None


# ── Video frames ─────────────────────────────────────────────────────────────
def _load_video_frames(video_path: str, frame_skip: int = 1):
    if not HAS_CV2:
        raise RuntimeError("OpenCV (cv2) is required. pip install opencv-python")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    frames = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % frame_skip == 0:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = frame.astype(np.float32) / 255.0
            frames.append(frame)
        idx += 1
    cap.release()
    if not frames:
        raise RuntimeError("No frames read from video.")
    return torch.from_numpy(np.stack(frames))


# ═══════════════════════════════════════════════════════════════════════════════
#  Node: DreaminaCLI_Login
# ═══════════════════════════════════════════════════════════════════════════════
class DreaminaCLI_Login:
    """
    OAuth device-flow helper for cloud / headless ComfyUI.

    Workflow:
      1. Add this node, set action="login", queue prompt.
         → It prints a verification URL; open it in your browser and authorize.
      2. Change action to "check", queue prompt again.
         → It polls for completion and saves the token locally.
      3. After success, DreaminaCLI_VideoGenerator can be used normally.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (["login", "check"], {"default": "login"}),
                "dreamina_data_dir": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("status", "message")
    FUNCTION = "do_login"
    CATEGORY = "DreaminaCLI"

    def do_login(self, action: str, dreamina_data_dir: str):
        dreamina_exe = _find_dreamina_exe()
        if not dreamina_exe:
            return ("ERROR", "Dreamina CLI not found. On Linux it will auto-install on first ComfyUI start.")

        data_dir = _data_dir_for(dreamina_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        # Already logged in?
        if _is_logged_in(dreamina_exe, data_dir):
            return ("LOGGED_IN", "Already logged in. You can use DreaminaCLI_VideoGenerator now.")

        if action == "login":
            # Clear stale device code first
            _clear_device_code()
            try:
                auth = _login_headless(dreamina_exe, data_dir)
            except Exception as e:
                return ("LOGIN_ERROR", str(e))

            _save_device_code(auth)
            url = auth.get("verification_uri", "")
            user_code = auth.get("user_code", "")
            expires = auth.get("expires_at", "")
            msg = (
                f"Please open the following URL in your browser and authorize:\n"
                f"URL: {url}\n"
                f"User Code: {user_code}\n"
                f"Expires At: {expires}\n\n"
                f"After authorizing, change action to 'check' and queue prompt again."
            )
            return ("NEED_AUTH", msg)

        # action == "check"
        saved = _load_device_code()
        if not saved or "device_code" not in saved:
            return ("NO_DEVICE_CODE", "No pending login found. Please run action='login' first.")

        device_code = saved["device_code"]
        ok = _check_login(dreamina_exe, device_code, data_dir)
        if ok:
            _clear_device_code()
            return ("SUCCESS", "Login successful! You can now use DreaminaCLI_VideoGenerator.")
        else:
            _clear_device_code()
            return (
                "CHECK_FAILED",
                "Authorization not completed or timed out. Please run action='login' again and authorize in your browser.",
            )


# ═══════════════════════════════════════════════════════════════════════════════
#  Node: DreaminaCLI_VideoGenerator
# ═══════════════════════════════════════════════════════════════════════════════
class DreaminaCLI_VideoGenerator:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model_version": ([
                    "seedance2.0", "seedance2.0fast",
                    "seedance2.0_vip", "seedance2.0fast_vip",
                ], {"default": "seedance2.0_vip"}),
                "ratio": (["1:1", "3:4", "16:9", "4:3", "9:16", "21:9"], {"default": "1:1"}),
                "duration": ("INT", {"default": 8, "min": 4, "max": 15, "step": 1}),
                "video_resolution": (["720p"], {"default": "720p"}),
                "max_wait_time": ("INT", {"default": 600, "min": 60, "max": 3600, "step": 30}),
                "poll_interval": ("INT", {"default": 15, "min": 5, "max": 120, "step": 5}),
                "output_dir": ("STRING", {"default": str(DEFAULT_OUTPUT_DIR)}),
                "frame_skip": ("INT", {"default": 1, "min": 1, "max": 10, "step": 1}),
                "dreamina_data_dir": ("STRING", {"default": ""}),
            },
            "optional": {
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("frames", "video_path", "status")
    FUNCTION = "generate"
    CATEGORY = "DreaminaCLI"

    def generate(self, prompt, model_version, ratio, duration, video_resolution,
                 max_wait_time, poll_interval, output_dir, frame_skip, dreamina_data_dir,
                 image1=None, image2=None):

        dreamina_exe = _find_dreamina_exe()
        if not dreamina_exe:
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, "", "ERROR: Dreamina CLI not found. On Linux it will auto-install on first ComfyUI start.")

        data_dir = _data_dir_for(dreamina_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        # ── Check login ──────────────────────────────────────────────────────
        if not _is_logged_in(dreamina_exe, data_dir):
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (
                empty,
                "",
                "NOT_LOGGED_IN: Please run DreaminaCLI_Login first (action='login', then authorize in browser, then action='check').",
            )

        # 1. Save images
        temp_dir = Path(tempfile.gettempdir()) / "dreamina_cli_inputs"
        temp_dir.mkdir(parents=True, exist_ok=True)
        image_paths = []
        for idx, img in enumerate([image1, image2], 1):
            if img is not None:
                path = temp_dir / f"ref_{idx}_{int(time.time()*1000)}.png"
                _save_comfy_image(img, path)
                image_paths.append(str(path))

        # 2. Submit
        try:
            submit_result = _dreamina_submit(
                dreamina_exe, prompt, image_paths, model_version, ratio, duration, video_resolution, data_dir
            )
        except Exception as e:
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, "", f"SUBMIT_ERROR: {e}")

        submit_id = submit_result.get("submit_id", "")
        if not submit_id:
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, "", f"NO_SUBMIT_ID: {submit_result}")

        # 3. Poll
        start = time.time()
        final_status = "querying"
        while time.time() - start < max_wait_time:
            status = _dreamina_query_status(dreamina_exe, submit_id, data_dir)
            if status == "success":
                final_status = status
                break
            if status in ("failed", "error", "canceled", "cancelled"):
                final_status = status
                break
            time.sleep(poll_interval)
        else:
            final_status = "timeout"

        if final_status != "success":
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, "", f"{final_status.upper()}: {submit_id}")

        # 4. Download
        video_path = _dreamina_download(dreamina_exe, submit_id, Path(output_dir), data_dir)
        if not video_path:
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, "", f"DOWNLOAD_FAILED: {submit_id}")

        # 5. Load frames for preview
        try:
            frames = _load_video_frames(video_path, frame_skip=frame_skip)
        except Exception as e:
            empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (empty, video_path, f"success_but_load_failed: {e}")

        return (frames, video_path, f"success: {submit_id}")
