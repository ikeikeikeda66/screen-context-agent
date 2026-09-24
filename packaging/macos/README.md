# Run the indexer at login (macOS)

`screencontext.indexer.plist` is a LaunchAgent template that starts `screen-context index --watch` at login and restarts it 60 seconds after an abnormal exit.

```sh
mkdir -p ~/Library/Logs/ScreenContext
sed -e "s|REPO|$PWD|" -e "s|HOME|$HOME|g" packaging/macos/screencontext.indexer.plist \
  > ~/Library/LaunchAgents/local.screencontext.indexer.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.screencontext.indexer.plist
```

Run the commands from the repository root.

```sh
launchctl print gui/$(id -u)/local.screencontext.indexer | grep -E "state|pid"   # status
launchctl kickstart -k gui/$(id -u)/local.screencontext.indexer                  # restart
launchctl bootout gui/$(id -u)/local.screencontext.indexer                       # stop and unload
```

Do not start a second `index --watch` by hand while the agent runs. It cannot take `indexer.lock` and exits.

To start the menu bar app at login, add `ScreenContext.app` in System Settings > General > Login Items.
