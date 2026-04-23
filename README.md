# ComfyUI-DreaminaCLI

ComfyUI custom node for [Dreamina (即梦)](https://jimeng.jianying.com) video generation via the official CLI tool.

> **Target use-case**: Cloud / headless ComfyUI instances where you cannot access a terminal or install the CLI manually.

## Features

- 🔐 **OAuth Device Flow** — Login without a browser on the server; just open a link on your local machine.
- 🎬 **Video Generation** — Submit multimodal-to-video tasks with image references.
- 📥 **Auto-install** — On Linux/macOS the CLI is downloaded automatically on first ComfyUI start.
- 🖼️ **Frame Output** — Returns decoded video frames as `IMAGE` tensors for preview/compositing.

## Installation

### Option A: ComfyUI Manager (Recommended)

1. Open **ComfyUI Manager** → **Install via Git URL**
2. Paste:
   ```
   https://github.com/YOUR_USERNAME/ComfyUI-DreaminaCLI.git
   ```
3. Restart ComfyUI

On **Linux**, the Dreamina CLI will be installed automatically (`curl | bash`).  
On **Windows**, install the CLI manually first:
```powershell
irm https://jimeng.jianying.com/cli | iex
```

### Option B: Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/YOUR_USERNAME/ComfyUI-DreaminaCLI.git
# Restart ComfyUI
```

## First-time Setup (OAuth Login)

Because Dreamina uses OAuth Device Flow, you must authorize once before generating videos.

### Step 1: Get the Login URL

1. Add a **🔐 Dreamina CLI Login** node to your workflow
2. Set `action` to **`login`**
3. Queue prompt
4. The node will output a URL like:
   ```
   https://jimeng.jianying.com/ai-tool/cli-auth?verification_uri=...
   ```
   Copy this URL and open it in your **local browser** (the machine in front of you, not the cloud server).

### Step 2: Authorize in Browser

- Open the link and click **Authorize** on the Dreamina page.

### Step 3: Complete Login

1. Back in ComfyUI, change the Login node `action` to **`check`**
2. Queue prompt again
3. If successful, the node returns **`SUCCESS`**

> The token is saved locally inside the node directory (`data/.dreamina_cli`). It persists across ComfyUI restarts.

## Usage — Video Generation

1. Add **🎬 Dreamina CLI Video Generator** node
2. Connect reference images (optional) to `image1` / `image2`
3. Fill in `prompt`, `model_version`, `ratio`, `duration`
4. Queue prompt — the node will:
   - Submit the task
   - Poll until completion
   - Download the MP4
   - Decode frames and return them as `IMAGE` tensors

### Connecting to VHS (VideoHelperSuite)

Feed the `frames` output into `VHS_VideoCombine` for preview inside ComfyUI:

```
DreaminaCLI_VideoGenerator.frames ──► VHS_VideoCombine.images
```

## Node Parameters

### 🔐 Dreamina CLI Login

| Parameter | Description |
|-----------|-------------|
| `action` | `login` — get auth URL; `check` — poll for completion |
| `dreamina_data_dir` | Custom path for token storage (default: inside node dir) |

### 🎬 Dreamina CLI Video Generator

| Parameter | Description |
|-----------|-------------|
| `prompt` | Text prompt for video generation |
| `model_version` | `seedance2.0`, `seedance2.0fast`, `seedance2.0_vip`, `seedance2.0fast_vip` |
| `ratio` | Aspect ratio: `1:1`, `3:4`, `16:9`, `4:3`, `9:16`, `21:9` |
| `duration` | Video length in seconds (4–15) |
| `video_resolution` | Currently only `720p` is supported |
| `max_wait_time` | Max seconds to poll for task completion |
| `poll_interval` | Seconds between status checks |
| `output_dir` | Where to save downloaded MP4s |
| `frame_skip` | Decode every N-th frame (1 = all frames) |
| `dreamina_data_dir` | Custom token directory |
| `image1` / `image2` | Reference images (optional) |

## Cloud-specific Notes

- **No terminal access?** No problem — everything happens inside ComfyUI nodes.
- **No browser on the server?** No problem — the OAuth link opens on **your** local browser.
- **Token persistence**: By default tokens are saved inside the custom node folder. Most cloud ComfyUI platforms persist `custom_nodes/` across restarts. If your platform wipes the directory, set `dreamina_data_dir` to a persistent path (e.g., ComfyUI's `input/` or `output/` folder).

### Old glibc / Ubuntu 20.04 support (proot auto-adapt)

Some cloud platforms run older Linux distributions (e.g., Ubuntu 20.04 with glibc 2.31) that cannot run the official Dreamina CLI binary (which requires glibc ≥ 2.34).

This node automatically detects the situation and **downloads a lightweight proot + Debian 12 rootfs** on first run — no root privileges needed. The CLI then runs inside the isolated environment transparently.

> **One-time setup**: first execution may take 3–5 minutes to download the rootfs (~25 MB) and install the CLI inside it. Subsequent runs are instant.

If automatic proot setup fails, you can still:
1. Complete `dreamina login` on your **local Windows/Mac** machine
2. Zip the `~/.dreamina_cli` folder and upload it to the cloud node's `data/` directory
3. The node will use the uploaded token

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Dreamina CLI not found` | On Linux it auto-installs. On Windows install manually via `irm \| iex`. |
| `NOT_LOGGED_IN` | Run the Login node first (`login` → authorize → `check`). |
| `CHECK_FAILED` | The auth URL expired (valid ~10 min). Run `login` again and authorize faster. |
| `SUBMIT_ERROR` | Make sure at least one reference image is connected, or check the prompt length. |

## License

MIT
