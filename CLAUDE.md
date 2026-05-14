# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

This is **nrfmodule-dev-manifest** — the West manifest that orchestrates the entire nRFModule firmware ecosystem. It does NOT contain application or library source code. It pins versions, defines workspace layout, and hosts CI/CD infrastructure.

## 4-Repo Architecture

| Repo | Role | What lives there |
|------|------|-----------------|
| **nrfmodule-dev-manifest** (this) | Workspace orchestrator | `west.yml`, CI workflows, Docker image |
| **nrfmodule-core** | Private implementation | All `.c` source files (the actual modem bridge code) |
| **nrfmodule-sdk** | Public distribution | `.h` headers + `libmodem_core.a` binary, board definitions |
| **nrfmodule-product-template** | Reference app | Test application for integration validation |

The SDK auto-detects whether nrfmodule-core is present. If so, it builds from source; otherwise it links the prebuilt binary. This enables closed-source distribution to customers.

## How the System Works

nRF52840 (host MCU) proxies AT commands to an external nRF9151 modem (running Nordic SLM firmware) over UART. The trick: nrfmodule-core compiles Nordic's standard `lte_link_control` sources directly for nRF52840, bypassing the `LTE_LINK_CONTROL` Kconfig (which requires `NRF_MODEM_LIB`). Instead, `lte_lc_client.cmake` manually compiles each module with custom defines, and `nrf_modem_at_*()` calls are routed through `sm_at_client` over UART.

URC dispatch uses renamed symbols (`sm_monitor_*` instead of `at_monitor_*`) to avoid linker conflicts when both AT_MONITOR and SM_MONITOR handlers coexist.

## west.yml Rules

- `sdk-nrf` is listed FIRST to override transitive version pulls from `import: true`
- `nrfmodule-sdk` has `import: true` (loads its `module.yml`); `nrfmodule-core` does not
- Changing `path:` values breaks existing workspaces (requires full re-init)
- `self.path: config/manifest` places this repo at `workspace/config/manifest/`

Current pins: NCS v3.2.1, nrfmodule-sdk v2.2.0, nrfmodule-core v2.2.0.

## Common Commands

### Workspace initialization
```bash
west init -m https://github.com/nrfmodule/nrfmodule-dev-manifest
west update
```

### Building firmware (from workspace root)
```bash
west build -b <board> <app-dir>
# Example: west build -b livetracker_nrf52840 ../nRFTracker-demo
```

### Running tests
```bash
west twister -T modules/lib/nrfmodule-core/tests --integration
```

### Docker image (CI)
```bash
cd infra/docker
docker build -t nrfmodule-test:local .
docker run -it nrfmodule-test:local /bin/bash
```
Image published to `ghcr.io/nrfmodule/nrfmodule-dev-manifest:latest`. Rebuilds trigger on changes to `infra/docker/**`.

## CI Workflows

- **`reusable-ci.yml`** — Called by nrfmodule-core. Swaps PR code into workspace, runs `west twister`.
- **`reusable-build.yml`** — Called by product apps. Takes `board` + `app-dir` inputs, runs `west build`, uploads hex/bin/elf artifacts.
- **`publish-docker.yml`** — Builds and pushes Docker image on `infra/docker/**` changes.

All CI runs in Docker container `ghcr.io/nrfmodule/nrfmodule-dev-manifest:latest` (Ubuntu 22.04, Zephyr SDK 0.17.4 ARM-only, NCS v3.1.1 Python deps).

## Version Strategy

Semantic versioning independent of NCS. Current: nRFModule v2.x tracks NCS 3.2.x; v1.x (legacy) tracks NCS 3.1.x.

Branches: `main` (latest stable), `v2.x` (patch series), `legacy-ncs-v3.1` (v1.x maintenance). Tags on both nrfmodule-core and nrfmodule-sdk must match (e.g., both tagged v2.1.0).

## Git Protocol

**Never push directly to `main`** — there is no branch protection (GitHub Free). Always use feature branches and PRs. See CONTRIBUTING.md for recovery steps if you accidentally commit to main.

## Updating NCS Version

High-risk operation — affects all developers and CI:
1. Update `sdk-nrf` revision in `west.yml`
2. Follow `nrfmodule-core/docs/NCS_PORTING_GUIDE.md`
3. Rebuild Docker image if needed (`infra/docker/Dockerfile`)
4. Test all dependent repos
5. Tag new version on both core and SDK repos
