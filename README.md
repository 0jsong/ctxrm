# ctxrm

English | [한국어](README.ko.md)

Remove a kubeconfig context and clean up its unused cluster and user entries.
Useful when short-lived test clusters leave stale entries in a merged kubeconfig.

```bash
kubectl ctxrm kind-test --dry-run
kubectl ctxrm kind-test
```

`ctxrm` only edits local kubeconfig files. It does not contact a Kubernetes API server
or delete an actual cluster.

## Requirements

- Python 3.10 or newer and `kubectl` on your `PATH`.
- Tested on Linux. Native Windows is not supported because directory locking uses
  `fcntl`. macOS compatibility has not been verified.
- No third-party Python packages at runtime.

## Install

```bash
git clone https://github.com/0jsong/ctxrm.git
cd ctxrm
mkdir -p "$HOME/.local/bin"
install -m 0755 kubectl-ctxrm "$HOME/.local/bin/kubectl-ctxrm"
export PATH="$HOME/.local/bin:$PATH"
kubectl ctxrm --version
kubectl plugin list
```

Add the `PATH` setting to `~/.bashrc` or `~/.zshrc` to keep it in new shells.
You can also run `make install` after cloning. Use `make install PREFIX=/custom/prefix`
to choose a different prefix.

If you use `alias k=kubectl`, the command is `k ctxrm kind-test`.
This plugin is not yet published in the Krew community index; use the manual
installation above.

## Usage

```bash
# Preview without changing files or creating backups.
kubectl ctxrm kind-test --dry-run

# Show the plan, ask for confirmation, then apply it.
kubectl ctxrm kind-test

# Skip the prompt for automation.
kubectl ctxrm kind-test --yes

# Limit the operation to a single physical file.
kubectl ctxrm kind-test --kubeconfig /path/to/config --dry-run

# Do not retain backups after a successful change.
kubectl ctxrm kind-test --yes --no-backup
```

Context names are exact and case-sensitive. Quote names containing spaces. For a
name beginning with a dash, put the options first and use `--` before the name:

```bash
kubectl ctxrm --dry-run -- '--test-context'
```

The tool removes the selected context, then removes its cluster and user only if
no remaining context in the selected scope references them. Shared dependencies
are shown as `KEEP`.

If the removed context was active, `current-context` is cleared. Choose the next
context explicitly:

```bash
kubectl config use-context remaining-context
```

## Kubeconfig scope

The scope follows this order:

1. `--kubeconfig FILE`: inspect and modify only that file.
2. `KUBECONFIG`: inspect each existing physical file in the path list.
3. Otherwise, use `~/.kube/config`.

Cross-file references are checked across the selected scope. To protect entries
shared across files, include all those files in `KUBECONFIG` and omit
`--kubeconfig`. Files outside the selected scope are not inspected.

Missing paths in `KUBECONFIG` are reported and skipped. A context defined in more
than one physical file is rejected; select one file explicitly to resolve the
ambiguity. Duplicate cluster or user definitions are retained.

See the official [kubectl config loading rules](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_config/)
for kubeconfig precedence.

## Backups and write behavior

- Before applying a change, the tool shows the exact entries and physical files
  involved. Non-interactive runs require `--yes`.
- Modified files receive an adjacent `config.bak.YYYYMMDDTHHMMSSZ` backup containing
  the original bytes. Colliding backup names receive a numeric suffix.
- Changes are applied to temporary copies, checked with `kubectl`, and written
  using a per-file atomic replacement. Detected concurrent edits abort the run.
- Directory locks prevent overlapping `ctxrm` runs. Other editors and `kubectl`
  do not honor these locks; avoid editing the same files during a run.
- The original permissions and ownership are preserved. Backups contain the same
  credentials as the source and need the same protection.
- A failed multi-file commit attempts to restore the original files. Force-killing
  the process or losing power cannot provide an all-files-at-once transaction.
- The native `kubectl` writer may reformat YAML and remove comments. Backups retain
  the original formatting.

The replacement order clears standalone `current-context` values first, removes
the context next, and removes orphan dependencies last to reduce the impact of
an interrupted multi-file operation.

To restore a backup, inspect the reported backup path and copy that exact file
over its original file. Close other kubeconfig writers first.

## Update or uninstall

Run `git pull --ff-only` in your clone and repeat the install command to update.
To uninstall, remove the installed `~/.local/bin/kubectl-ctxrm` file.

## Development

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

The tests use temporary kubeconfig fixtures and do not modify your personal
kubeconfig. GitHub Actions runs the suite with Python 3.10 and 3.12.

## License

[MIT](LICENSE)
