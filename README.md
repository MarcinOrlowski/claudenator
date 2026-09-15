# Claudenator

Claude Code session manager

Claude Code writes each session to many places under `~/.claude`: the transcript, a sidecar folder of
subagent transcripts that is often larger than the transcript itself, and a handful of small folders named
after the session id. `claudenator` finds every session, shows what it is and how much disk it takes, and, in
the releases that follow, moves the ones you pick to a Trash you can restore from.

## Install

```bash
pipx install https://github.com/MarcinOrlowski/claudenator.git
```

## Licence

MIT. See [LICENSE.md](LICENSE.md).
