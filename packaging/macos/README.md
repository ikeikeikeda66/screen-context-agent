# Indexer and start at login (macOS)

The menu bar app runs both capture and the indexer. The indexer is a child process of the app (`screen-context index --watch`), restarted up to 3 times in 10 minutes if it crashes, and stopped when you quit the app. The menu shows its state. Its output goes to `~/Library/Logs/ScreenContext/indexer.log`.

## Start at login

Turn on **Start at Login** in the app's menu. It registers the app's own login item (`SMAppService`, macOS 13 or later). If macOS asks for approval, allow ScreenContext in System Settings > General > Login Items. The item is available only in the built app (`dist/ScreenContext.app`), not when running from source.

## Moving from the indexer LaunchAgent

Earlier versions asked you to install `local.screencontext.indexer` as a LaunchAgent. Only one indexer can run at a time, because each one holds `indexer.lock`. On start, the app looks for that agent, loaded or installed.

- **Remove the Agent** (the default) unloads it with `launchctl bootout` and renames `~/Library/LaunchAgents/local.screencontext.indexer.plist` to `…plist.disabled`, so it does not come back at login. The app then starts its own indexer.
- **Keep the Agent** leaves it alone. The app starts no indexer, and the menu says that the old LaunchAgent runs it.

To remove the agent by hand:

```sh
launchctl bootout gui/$(id -u)/local.screencontext.indexer
mv ~/Library/LaunchAgents/local.screencontext.indexer.plist ~/Library/LaunchAgents/local.screencontext.indexer.plist.disabled
```

## Without the app

If you do not use the app, for example on a Mac that only indexes frames copied from elsewhere, run the indexer in a terminal:

```sh
.venv/bin/screen-context index --watch
```

`screencontext.indexer.plist` is still here as a template for that case: a LaunchAgent that starts `index --watch` at login and restarts it 60 seconds after an abnormal exit. Do not install it on a Mac that runs the app.

```sh
mkdir -p ~/Library/Logs/ScreenContext
sed -e "s|REPO|$PWD|" -e "s|HOME|$HOME|g" packaging/macos/screencontext.indexer.plist \
  > ~/Library/LaunchAgents/local.screencontext.indexer.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.screencontext.indexer.plist
```

Run the commands from the repository root.
