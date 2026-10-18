"""Uninstall from the menu bar app (#37-B): which dialogs appear, in which order, and what each answer does.

Free of AppKit: mac_app.py passes `ui` (the dialogs), tests pass a fake.

  ask()     plan (reads only) -> dialog 1 (what goes, what stays; Cancel is the default)
            -> dialog 2 (keep or erase the data; Keep is the default)
            -> dialog 3, only for erase (the same text as `uninstall --wipe`, and the word ERASE must be typed)
            Returns the confirmed Plan, or None. It never changes anything and never calls apply.
  finish()  uninstall.apply(plan), then the result dialog.

The app holds capture.lock itself and runs the indexer as a child, so apply() cannot run inside the menu
action. mac_app.py keeps the Plan, stops the capture loop, and calls finish() after the loop, both locks
and the indexer are gone. apply() would otherwise stop at "Quit ScreenContext first" and change nothing.

ui.confirm(title, body, ok, cancel) -> bool         True for ok; the cancel button is the default
ui.ask_word(title, body, ok, cancel) -> str | None  the typed text; None for cancel
ui.report(title, body)
"""
from . import uninstall
from .i18n import t


def ask(settings, ui, lang, plan=uninstall.plan):
    keep = plan(settings, wipe=False)
    title, body = uninstall.confirmation(keep, lang)
    if not ui.confirm(title, body, t("uninstall.confirm", lang), t("uninstall.cancel", lang)): return None
    erase = plan(settings, wipe=True)
    if not erase.erase: return keep                      # no key and no data folder: nothing to ask about
    items = [t("uninstall.do.wipe", lang, path=erase.root)]
    items += [t("uninstall.do.exports", lang, path=e["detail"]) for e in erase.erase if e["code"] == "exports"]
    body = t("uninstall.wipe.body", lang) + "\n\n" + "\n".join("- " + s for s in items)
    if not ui.confirm(t("uninstall.wipe.title", lang), body, t("uninstall.wipe.erase", lang), t("uninstall.wipe.keep", lang)): return keep
    word = uninstall.confirmation_word(erase)
    title, body = uninstall.confirmation(erase, lang)
    ok = t("uninstall.confirm.wipe", lang)
    typed = ui.ask_word(title, body + "\n\n" + t("uninstall.word.hint", lang, word=word, ok=ok), ok, t("uninstall.cancel", lang))
    if typed is None: return None
    if typed.strip() != word:
        ui.report(t("uninstall.not_confirmed", lang), "")
        return None
    return erase


def details(plan, result, lang):
    """Body of the result dialog: failed steps, what the user does by hand, what stays."""
    if result.aborted: return ""                         # the title already holds the reason
    text = uninstall.lines(plan, lang)
    parts = ["\n".join(f"- {s['step']}: {s['detail']}" for s in result.steps if s["status"] == "failed")]
    if text["manual"]: parts.append(t("uninstall.manual.header", lang) + "\n" + "\n".join("- " + s for s in text["manual"]))
    parts.append(t("uninstall.remains.header", lang) + "\n" + "\n".join("- " + s for s in text["remains"]))
    return "\n\n".join(p for p in parts if p)


def finish(plan, ui, lang, apply=uninstall.apply):
    """Carry out the confirmed plan and show the result. Call it only after capture.lock and indexer.lock
    are free. `lang` must be read before this call: a wipe deletes the language setting with the data folder."""
    try: result = apply(plan, actor="app")
    except Exception as error:
        _report(ui, t("error.uninstall", lang, error=type(error).__name__), "")
        return None
    if result.aborted: _report(ui, t("uninstall.app_aborted", lang), "")     # app wording: no "quit first" (that is the CLI's)
    else: _report(ui, uninstall.result_message(result, lang), details(plan, result, lang))
    return result


def _report(ui, title, body):
    """A result dialog that fails must not turn a finished uninstall into a traceback: the work is already done."""
    try: ui.report(title, body)
    except Exception: pass
