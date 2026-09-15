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

## Settings

The `F2` key opens the settings, in sections: General, Lists, Times and Layout. A change takes effect at
once. `ctrl+s` keeps it, `escape` puts it back, and `ctrl+d` puts the option under the cursor back to its
default.

What you keep goes to `~/.config/claudenator/config.toml` (`$XDG_CONFIG_HOME` wins over `~/.config`). The
file holds only the options you changed, and the command line reads it too.

## Licence

MIT. See [LICENSE.md](LICENSE.md).
