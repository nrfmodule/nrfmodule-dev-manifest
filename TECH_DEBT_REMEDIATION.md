# Technical Debt Remediation Plan: nRF Modem Library Migration

> **Status (2026-09-03): executed. Kept as history.**
> The `nrf_modem_at` shim lives in `nrfmodule-core/src/client/`.
> The public headers live in `nrfmodule-sdk/include/`.
> Nordic's stock `lte_link_control` sources are compiled unchanged by `lte_lc_client.cmake` in nrfmodule-core.
> The fork of `lte_lc` described below was not kept.

## Summary Table

| Metric | Rating | Description |
| :--- | :--- | :--- |
| **Ease of Remediation** | 3/5 | Moderate. Requires restructuring and verifying shim compliance. |
| **Impact** | 5/5 | 🔴 Critical. Enables clean separation of concerns and easier updates. |
| **Risk** | 3/5 | 🟡 Medium. Risk of breaking existing modem behavior during refactor. |
| **Overview** | Migrate `nrf_modem_lib` to `nrfmodule` ecosystem, decoupling implementation from interface. |

## Detailed Analysis

### 1. Overview
The current `nrf_modem_lib` is a monolithic folder containing both the implementation of a custom AT command layer (`nrf_modem_at`) and forked copies of Nordic's middleware (`lte_link_control`, `modem_info`, etc.). This structure makes it difficult to maintain (upstream updates require manual merging) and violates the `nrfmodule` architecture of separating Core (source) from SDK (headers/binaries).

### 2. Explanation & Resolution Approach

**The Core Problem:**
You have forked `lte_lc` and other libraries because they depend on `nrf_modem_at` functions, and you needed to inject your custom SLM-based implementation.

**The "nrfmodule" Solution:**
Instead of forking the *consumers* (`lte_lc`), we should only replace the *provider* (`nrf_modem_at`).

1.  **Library Structure**:
    *   **`nrfmodule-core`**: Should contain the *implementation* of `nrf_modem_at` (the shim layer that talks to SLM).
    *   **`nrfmodule-sdk`**: Should expose the standard `nrf_modem_at.h` headers so the application (and Nordic's libraries) can link against it.

2.  **Maintenance Strategy (The "Shim" Pattern)**:
    *   **Goal**: Use the *original* Nordic `lte_lc` library from NCS, but link it against *your* `nrf_modem_at` implementation.
    *   **Benefit**: When Nordic updates `lte_lc`, you get the update for free. You only maintain your shim.
    *   **Challenge**: Nordic's `lte_lc` might use internal calls or rely on the binary `libmodem`.
    *   **Fallback**: If strict linking isn't possible due to private headers (like `cereg.h`), keep the fork but isolate it in `nrfmodule-core/src/modules/lte_lc` and use a "3-way merge" workflow for updates.

### 3. Requirements

*   Existing `nrfmodule-core` and `nrfmodule-sdk` repositories setup.
*   Understanding of `nrf_modem_at` API surface used by `lte_lc`.

### 4. Implementation Steps

#### Phase 1: Restructuring (Immediate)
1.  **Move Source**:
    *   Move `nrf_modem_at/src/*.c` -> `nrfmodule-core/src/shim/`.
    *   Move `lte_link_control/src/*.c` -> `nrfmodule-core/src/modules/lte_lc/` (if keeping fork).
2.  **Move Headers**:
    *   Move `nrf_modem_at/include/*.h` -> `nrfmodule-sdk/include/`.
    *   Ensure these headers match Nordic's public API signatures *exactly*.

#### Phase 2: Build System Update
1.  **`nrfmodule-sdk/CMakeLists.txt`**:
    *   Update to link your shim implementation when `CONFIG_NRF_MODEM_LIB` is enabled (or a custom Kconfig).
    *   Use `zephyr_library_amend()` or `zephyr_library_named()` to override default Nordic implementations if necessary.

#### Phase 3: Naming Conventions
*   **Library Name**: `nrfmodule_modem_shim` (Internal) / `nrfmodule_connectivity` (Public).
*   **Files**: Keep `nrf_modem_at.c` as is (it implements a standard interface).
*   **Functions**: Your *internal* helpers in the shim can use `slm_client_*` prefix to distinguish from standard `nrf_modem_*` calls.

### 5. Testing
1.  **Compilation Test**: Build `nrfmodule-product-template` with the new structure.
2.  **Linker Test**: Verify that `lte_lc_connect()` calls *your* `nrf_modem_at_cmd()` implementation, not the default one.
3.  **Functional Test**: Run the `modem_say_hello` test but replace it with a real AT command test (e.g., `AT+CGMR`).

### 6. Addressing Build Failures & Missing Headers

The build logs indicate missing headers (`nrf_modem_at.h`, `nrf_errno.h`, `nrf_socket.h`) when compiling `lte_lc` on nRF52. This confirms that `lte_lc` expects the full `nrf_modem_lib` environment.

**Resolution Strategy:**

1.  **`nrf_errno.h`**:
    *   Already exists in `common/include/nrf_errno.h`.
    *   **Fix**: Ensure `nrfmodule-sdk/include/` contains this file or `CMakeLists.txt` adds `common/include` to public include paths.

2.  **`nrf_modem_at.h`**:
    *   Already exists in `nrf_modem_at/include/`.
    *   **Fix**: Move to `nrfmodule-sdk/include/` so it's globally visible.

3.  **`nrf_socket.h`**:
    *   Missing from your current structure. `lte_lc` uses it for DNS lookups (`modules/dns.c`).
    *   **Fix**: You need to shim this header too if you want to support DNS, or disable DNS in Kconfig if not needed.

4.  **`NRF_MODEM_LIB_ON_CFUN` Hooks**:
    *   The build fails because `lte_lc` and `date_time` rely on these macros to register callbacks.
    *   **Fix**: Implement the `NRF_MODEM_LIB_ON_*` macros in a new header `nrf_modem_lib.h` within `nrfmodule-sdk`.
    *   **Implementation**: Use Zephyr's `STRUCT_SECTION_ITERABLE` (just like Nordic does) to create a registry of callbacks, then iterate them in your shim when events occur.

### 7. Implementing Hooks (The "Shim" Detail)

To support `NRF_MODEM_LIB_ON_CFUN`, you must replicate Nordic's section-based callback mechanism in your shim.

**`nrfmodule-sdk/include/nrf_modem_lib.h` (New File):**
```c
#include <zephyr/kernel.h>

struct nrf_modem_lib_at_cfun_cb {
    void (*callback)(int mode, void *ctx);
    void *context;
};

#define NRF_MODEM_LIB_ON_CFUN(name, _callback, _context) \
    static void _callback(int mode, void *ctx); \
    STRUCT_SECTION_ITERABLE(nrf_modem_lib_at_cfun_cb, nrf_modem_at_cfun_hook_##name) = { \
        .callback = _callback, \
        .context = _context, \
    }
```

**`nrfmodule-core/src/shim/nrf_modem_lib_shim.c` (New File):**
```c
// Call this when your SLM/AT layer detects a CFUN change
void nrfmodule_trigger_cfun_callbacks(int mode) {
    STRUCT_SECTION_FOREACH(nrf_modem_lib_at_cfun_cb, hook) {
        if (hook->callback) {
            hook->callback(mode, hook->context);
        }
    }
}
```
