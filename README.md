<!-- The image links in README.md are absolute links to make them render on PyPI too. -->

![Claudenator](https://raw.githubusercontent.com/MarcinOrlowski/claudenator/master/img/logo.webp)

[![Version](https://img.shields.io/pypi/v/claudenator?style=flat)](https://pypi.org/project/claudenator/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE.md)

## The only Claude Code session manager you need

Claude Code writes a lot. Every session leaves a transcript from the main session and its subagents.
Then goes the environment, file history, jobs and todos. That's tons of disk. Additionally,
it auto-purges all the sessions older than 30 days, but if you decide to prevent that and keep some
old sessions for longer, it can stack up a massive pile pretty quickly.

This is where Claudenator comes to the rescue. It shows all your sessions, grouped by project
folder, sorts them by whatever column you like and shows tons of additional information that
would help you manage them and purge only real garbage.

![Claudenator in action](https://raw.githubusercontent.com/MarcinOrlowski/claudenator/master/img/claudenator.webp)

## Features

* Shows every session, its title, project, size, date, messages, model, git branch, tools and moar.
* A details pane under the table, and a full-screen view for the whole story.
* Order the table by any column and narrow it to what you look for with a filter.
* A deleted session first goes to a Trash so it disappears but is not yet gone and can be either
  restored or purged for good.
* Comes with "Deep scan" feature, that process the full transcript to give you more stats for nerds.
* Configurable TUI with themes, layout, time formats and more.

## Installation

The [pipx](https://pypi.org/project/pipx/) is the recommended way to install it:

```bash
# Install pipx if not present
sudo apt install -y pipx

# Install the tool
pipx install claudenator

# Upgrade existing installation
pipx upgrade claudenator
```

To get the latest code, install straight from the repository:

```bash
# Install the current "master" branch
pipx install --force git+https://github.com/MarcinOrlowski/claudenator.git

# Install the "dev" branch or any other branch, tag or commit
pipx install --force git+https://github.com/MarcinOrlowski/claudenator.git@dev
```

The `--force` option is only needed if there's already existing Claudenator installation present.

## License

* Written and copyrighted &copy;2026 by Marcin Orlowski <mail (#) marcinorlowski (.) com>
* This is open-source software licensed under the [MIT license](http://opensource.org/licenses/MIT)
