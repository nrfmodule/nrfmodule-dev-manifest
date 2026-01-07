# nRFModule Development Manifest

This is the master configuration for the nRFModule Firmware Ecosystem. It orchestrates the Nordic SDK (NCS), Zephyr, and our private libraries into a single workspace.

## 1. Prerequisites

*   **VS Code** installed.
*   **nRF Connect for VS Code Extension Pack** installed.
*   **Git** installed and authenticated.

## 2. Setup (The Correct Way)

**⚠️ STOP! Do not clone `nrfmodule-core` manually.**

We use a **West Workspace** managed by the nRF Connect Extension. This ensures you have the correct version of the SDK, Zephyr, and our private libraries all linked together correctly.

### Step-by-Step Guide

1.  Open VS Code.
2.  Click on the **nRF Connect** icon in the sidebar (the Nordic logo).
3.  In the **Welcome** or **Manage SDKs** section, click **"Create new workspace"**.
4.  Select **"Copy from URL"** (or "Initialize from URL").
5.  Paste this URL:
    ```text
    https://github.com/nrfmodule/nrfmodule-dev-manifest
    ```
6.  Select a folder on your drive (e.g., `C:\nrfmodule_workspace`) and let it initialize. This will take a few minutes to download NCS and our libraries.

![Setup Workspace Animation](doc/images/setup_workspace.gif)

### Verifying the Setup

Once finished, open the folder in VS Code. You should see a folder structure like this:

```text
workspace/
├── .west/
├── nrf/                  <-- Nordic SDK (v3.x)
├── zephyr/               <-- Zephyr RTOS
├── modules/
│   └── lib/
│       ├── nrfmodule-core/  <-- PRIVATE SOURCE (Edit code here!)
│       └── nrfmodule-sdk/   <-- PUBLIC WRAPPER
└── ...
```

## 3. How to Develop (The Workflow)

**CRITICAL:** You are working *inside* the workspace. The folders `modules/lib/nrfmodule-core` are actual Git repositories.

### Step 1: Create a Feature Branch
1.  Go to the **Source Control** tab in VS Code.
2.  You will see multiple repositories listed (manifest, core, sdk, zephyr, nrf).
3.  Locate **`nrfmodule-core`** (or whichever repo you are editing).
4.  Create a new branch: `feature/my-new-feature`.

![Source Control View](doc/images/source_control.png)

### Step 2: Test Your Changes
To run your code, you need an application.
*   **Quick Test:** Create a temporary app inside the workspace.
*   **Real Product:** Use the `nrfmodule-product-template` (see its README).

### Step 3: Push & Pull Request
1.  Commit your changes in VS Code.
2.  **Push** the branch to GitHub.
3.  Go to GitHub and open a **Pull Request (PR)** to `main`.
4.  **⛔ DO NOT PUSH DIRECTLY TO MAIN.**
    *   We are on the "Honor System". GitHub will not stop you, but you will break the CI for everyone.
    *   See [CONTRIBUTING.md](CONTRIBUTING.md) for the full protocol.

## 4. Repository Map

| Repository | Role | Description |
| :--- | :--- | :--- |
| **`nrfmodule-dev-manifest`** | **The Boss** | Defines the SDK version and dependencies. Hosts the Docker CI image. |
| **`nrfmodule-core`** | **The Brains** | Private C source code. This is where you do 99% of your work. |
| **`nrfmodule-sdk`** | **The Face** | Public headers and binary distribution. |
| **`nrfmodule-product-template`** | **The Body** | Reference application to run and test the code. |

## 5. Version Management & Release Workflow

We use **semantic versioning** independent of NCS versions. This gives us our own identity while clearly documenting compatibility.

### Version Strategy

| nRFModule Version | NCS Version | Branch | Status |
|-------------------|-------------|--------|--------|
| **v2.x** | **3.2.x** | `main` | ✅ **Active Development** |
| v1.x | 3.1.x | `v1.x` | 🔧 Maintenance Only |

### Branch Workflow

```
main                    ← Latest stable (currently v2.x for NCS 3.2.x)
  ├─ v1.x              ← Maintenance branch (NCS 3.1.x)
  └─ feature/*         ← Short-lived feature branches
```

### Creating a Release

1. **Feature Development:**
   ```bash
   git checkout -b feature/my-feature
   # Make changes, commit
   git push -u nrfmodule feature/my-feature
   # Open PR to main
   ```

2. **Bug Fixes:**
   ```bash
   git checkout -b fix/issue-123
   # Make fixes, commit
   git push -u nrfmodule fix/issue-123
   # PR to main → tagged as v2.0.1 (patch)
   ```

3. **Release Tagging:**
   ```bash
   # After merging to main
   git checkout main
   git pull
   
   # Tag both repositories with same version
   cd modules/lib/nrfmodule-core
   git tag -a v2.1.0 -m "Release v2.1.0: Description"
   git push nrfmodule v2.1.0
   
   cd ../nrfmodule-sdk
   git tag -a v2.1.0 -m "Release v2.1.0: Description"
   git push nrfmodule v2.1.0
   ```

4. **Updating This Manifest:**
   Update `west.yml` to reflect the new stable version if needed (or keep on `main`).

### Porting to New NCS Version

When Nordic releases a new NCS version:

1. Create `feature/ncs-vX.X-port` branch
2. Follow [nrfmodule-core/docs/NCS_PORTING_GUIDE.md](https://github.com/nrfmodule/nrfmodule-core/blob/main/docs/NCS_PORTING_GUIDE.md)
3. Decide on version bump:
   - **Patch (v2.0.1):** Bug fixes only
   - **Minor (v2.1.0):** New features, backward compatible
   - **Major (v3.0.0):** Breaking changes
4. Merge to `main` and tag
5. Update this manifest's `west.yml` to new NCS version

### Customer Usage

Customers pin to stable versions in their `west.yml`:

```yaml
manifest:
  projects:
    - name: nrfmodule-sdk
      url: https://github.com/nrfmodule/nrfmodule-sdk
      revision: v2.0.0  # Pin to specific version
      # OR
      revision: main    # Latest patches for v2.x
      # OR
      revision: v1.x    # Legacy NCS 3.1.x support
```

## 6. CI/CD & Docker

This repository hosts the Docker image used by our CI pipelines.
*   **Image:** `ghcr.io/nrfmodule/nrfmodule-dev-manifest:latest`
*   **Trigger:** Modifying files in `infra/docker/` will trigger a rebuild of the image (takes ~15 mins).

## 7. FAQ

**Q: Should I work on `main` or a feature branch?**  
A: Always create a feature branch. Never commit directly to `main`.

**Q: Which version should customers use?**  
A: For new projects on NCS 3.2.x, use `v2.0.0` or `main`. For NCS 3.1.x, use `v1.x`.

**Q: How do I backport a fix to v1.x?**  
A: Cherry-pick the commit to the `v1.x` branch and tag as v1.0.1, v1.0.2, etc.

**Q: Do I need to tag both core and SDK with the same version?**  
A: Yes! Keep versions synchronized across both repositories for clarity.
