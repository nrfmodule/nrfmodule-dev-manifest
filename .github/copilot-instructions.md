# nRFModule Dev Manifest - AI Agent Instructions

## Architecture Overview

**This is "The Boss" repository** - it orchestrates the entire nRFModule ecosystem using West multi-repo management.

**4-Repository Architecture:**
- **nrfmodule-dev-manifest** (THIS REPO): Defines SDK versions, workspace configuration, CI infrastructure
- **nrfmodule-core**: Private source code (`.c` files)
- **nrfmodule-sdk**: Public distribution (`.h` headers + `.a` binaries)
- **nrfmodule-product-template**: Reference application for testing integration

## Key Responsibilities

1. **Version Control for External Dependencies** - `west.yml` pins NCS, Zephyr, and internal modules
2. **CI/CD Infrastructure** - Hosts reusable workflows and Docker image for all repos
3. **Workspace Initialization** - Entry point for developers ("Create from URL" in nRF Connect Extension)

## Critical Files

### `west.yml` - The Master Configuration

**Explicit SDK Version Pinning:**
```yaml
projects:
  - name: sdk-nrf
    remote: ncs
    revision: v3.2.1  # PINNED - Don't auto-update without testing
    import: true
```

**Why pinned?** West's `import` can transitively pull different versions. By listing `sdk-nrf` FIRST with explicit revision, we override any transitive dependencies.

**Internal Module Loading:**
```yaml
  - name: nrfmodule-sdk
    path: modules/lib/nrfmodule-sdk
    revision: main
    import: true  # Loads its module.yml but sdk-nrf version is ignored
    
  - name: nrfmodule-core
    path: modules/lib/nrfmodule-core
    revision: main
    # No import - just clones the repo
```

**Workspace structure created:**
```
workspace/
├── config/manifest/          # THIS REPO (via self.path)
├── nrf/                      # Nordic SDK v3.2.1
├── zephyr/                   # Transitive from sdk-nrf
├── ncs-serial-modem/         # Serial modem (pinned SHA)
├── modules/lib/
│   ├── nrfmodule-core/      # Private source
│   └── nrfmodule-sdk/       # Public wrapper
└── .west/                    # West metadata
```

## Docker Image Management

### `infra/docker/Dockerfile`

**Pre-installed components:**
- Ubuntu 22.04 base
- Zephyr SDK 0.17.4 (ARM toolchain only to save space)
- NCS v3.2.1 with all Python requirements
- QEMU for ARM emulation testing
- Nordic CLI tools (nrfjprog)

**Environment variables set:**
```dockerfile
ENV ZEPHYR_TOOLCHAIN_VARIANT=zephyr
ENV ZEPHYR_SDK_INSTALL_DIR=/opt/toolchains/zephyr-sdk-0.17.4
```

**Image published to:** `ghcr.io/nrfmodule/nrfmodule-dev-manifest:latest`

**Rebuild triggers:** Any change to `infra/docker/**` triggers `.github/workflows/publish-docker.yml`

### Reusable CI Workflows

**`.github/workflows/reusable-ci.yml`** - For library testing (used by nrfmodule-core):
- Inputs: `test-path` (e.g., `"tests"`)
- Runs: `west twister -T {test-path}` in Docker container
- Caller example: `nrfmodule-core/.github/workflows/ci.yml`

**`.github/workflows/reusable-build.yml`** - For application builds (used by product-template):
- Inputs: `board`, `build-path`
- Runs: `west build` in Docker container
- Caller example: `nrfmodule-product-template/.github/workflows/build.yml`

**Access control:** Repository Settings → Actions → General → "Allow reusable workflows" enabled

## Developer Onboarding Workflow

**Never clone manually!** Documented in `README.md`:

1. Install nRF Connect for VS Code Extension
2. Click "Create Workspace from URL"
3. Enter: `https://github.com/nrfmodule/nrfmodule-dev-manifest`
4. Let it initialize (downloads ~2GB, takes 5-10 min)

**VS Code multi-repo handling:**
- Source Control shows all Git repos separately
- Work in `modules/lib/nrfmodule-core/` for code changes
- Create branches in specific repos, not the manifest

## Modification Guidelines

### Updating NCS Version

**⚠️ High risk operation** - affects all developers and CI:

1. Update `west.yml` revision: `sdk-nrf: v3.x.x`
2. Rebuild Docker image (push change to `infra/docker/Dockerfile` to trigger rebuild)
3. Update Docker image version in reusable workflows if needed
4. Test all dependent repos build successfully
5. Notify team - everyone must re-init workspaces

### Adding New Internal Module

```yaml
projects:
  - name: nrfmodule-newmodule
    remote: nrfmodule
    path: modules/lib/nrfmodule-newmodule
    revision: main
    import: false  # Set true only if it has its own west.yml
```

### Modifying Docker Image

**What requires rebuild:**
- Changing Zephyr SDK version
- Adding/removing apt packages
- Updating Python requirements
- Changing NCS version in Docker init

**What doesn't require rebuild:**
- Updating `west.yml` (workspace handles this at runtime)
- Changing reusable workflow logic
- Documentation updates

## Common Pitfalls

1. **Don't commit `.west/` or build artifacts** - these are workspace-local
2. **Don't pin `nrfmodule-core/sdk` to commits** - use `main` for active development
3. **Docker image size matters** - currently ~2GB, avoid adding full toolchains
4. **West update behavior** - `import: true` can override settings, order matters
5. **Path changes break workspaces** - changing `path:` in `west.yml` requires full re-init

## CI/CD Permissions

**GitHub Actions cross-repo calls require:**
- Settings → Actions → General → Workflow permissions: "Read and write"
- Settings → Actions → General → Allow access from other repositories

**GitHub Packages (Docker registry) require:**
- Package settings → "Add Repository" → Grant read access to consuming repos
- Packages are public by default via `ghcr.io`

## Testing Changes Locally

**Test workspace initialization:**
```powershell
# Delete old workspace
Remove-Item -Recurse -Force test_workspace
# Create new
cd test_workspace
west init -m https://github.com/nrfmodule/nrfmodule-dev-manifest --mr your-branch
west update
```

**Test Docker build locally:**
```powershell
cd infra/docker
docker build -t nrfmodule-test:local .
docker run -it nrfmodule-test:local /bin/bash
```
