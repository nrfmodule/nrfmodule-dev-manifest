# Contributing to nRFModule

## ⚠️ The "Honor System" Protocol

**We are using GitHub Free for Private Repositories.**
This means **GitHub cannot technically stop you** from pushing directly to `main`.

**YOU** are responsible for not breaking the build.

### ⛔ The Golden Rule
**NEVER run `git push origin main`.**

### ✅ The Correct Workflow

1.  **Create a Branch** for every single change.
    ```bash
    git checkout -b feature/my-cool-feature
    ```
2.  **Commit** your changes.
3.  **Push the Branch** (NOT main).
    ```bash
    git push origin feature/my-cool-feature
    ```
4.  **Open a Pull Request** on GitHub.
    *   Go to the repository URL.
    *   You will see a yellow banner "feature/my-cool-feature had recent pushes".
    *   Click **Compare & pull request**.

### 🆘 "I accidentally committed to main!"

If you committed to `main` locally but haven't pushed yet:
1.  **STOP.** Do not push.
2.  Move your commit to a new branch:
    ```bash
    git branch feature/saved-work
    git reset --hard origin/main
    git checkout feature/saved-work
    ```
3.  Now you are safe to push the new branch.

### 🛡️ Optional: Install a Safety Hook

To prevent accidents, you can install a "Pre-Push Hook" that blocks pushes to main.

1.  Navigate to `.git/hooks/` in your repository.
2.  Create a file named `pre-push` (no extension).
3.  Paste this content:

```bash
#!/bin/sh
current_branch=$(git symbolic-ref HEAD | sed -e 's,.*/\(.*\),\1,')

if [ "$current_branch" = "main" ]; then
    echo "⛔ BLOCKED: Direct push to main is forbidden. Please use a Pull Request."
    exit 1
fi
```
