# git-commit-dater

A TUI/CLI tool to create or amend a git commit while setting **both** the
author date and the committer date to a value you choose.

Run it with no arguments for an interactive terminal UI (a calendar plus an
hour/minute/second picker), or pass `--date` to commit directly from the
command line without the UI.

## Features

- Sets `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` to the same chosen value.
- Interactive TUI built with [Textual](https://textual.textualize.io/):
  calendar navigation, time inputs, commit message editor, and an "Amend HEAD"
  toggle.
- Non-interactive CLI mode via `--date` / `--message` / `--amend`.
- Seeds the message editor with the last commit message and shows the current
  HEAD commit date.
- Responsive layout: stacked single-column on tall terminals, two-column on
  short ones.

## Requirements

- Python 3.12 (the project venv was created with 3.12.3).
- git available on `PATH`.
- The `textual` package (see `requirements.txt`).

## Installation

Create a virtual environment and install the dependencies from
`requirements.txt`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To leave the virtual environment later:

```bash
deactivate
```

## Usage

With the venv active:

```bash
python git_commit_dater.py
```

Or use the launcher script, which runs the tool from the venv against the git
repository in your current working directory (edit the hardcoded `DIR` path in
`git-commit-dater` if you move the project):

```bash
./git-commit-dater
```

Both must be run from inside a git repository.

### Interactive TUI

Launch with no `--date` argument:

```bash
python git_commit_dater.py
```

- Navigate the calendar with arrow keys; `<` / `>` change the month.
- Fill in hour / minute / second.
- Edit the commit message.
- Toggle "Amend HEAD" to amend the current commit instead of creating a new
  one.
- Press OK to commit, Cancel or `Esc` to abort.

### Command-line mode

Pass `--date` to skip the TUI:

```bash
# New commit with an explicit message
python git_commit_dater.py --date '2024-12-24 18:30:00' -m 'xmas'

# Amend HEAD, reusing its existing message
python git_commit_dater.py --date 24.12.2024 --amend

# Force a new commit
python git_commit_dater.py --date 2024-12-24T18:30:00 -m msg --no-amend
```

Options:

- `-d`, `--date` — commit date/time. If given, commits directly without the TUI.
- `-m`, `--message` — commit message. Required with `--date` unless `--amend`
  reuses the existing one.
- `--amend` / `--no-amend` — amend HEAD or force a new commit (CLI defaults to
  a new commit).

### Supported date formats

The local timezone is assumed. Missing time parts default to `00`.

```
%Y-%m-%dT%H:%M:%S
%Y-%m-%d %H:%M:%S
%Y-%m-%d %H:%M
%Y-%m-%d %H
%Y-%m-%d
%d/%m/%Y %H:%M:%S
%d/%m/%Y %H:%M
%d/%m/%Y
%d.%m.%Y %H:%M:%S
%d.%m.%Y %H:%M
%d.%m.%Y
```
