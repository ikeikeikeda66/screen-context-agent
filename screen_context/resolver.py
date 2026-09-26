"""One place decides every setting: managed > user > default.

Managed values will come from MDM configuration profiles or Group Policy
(roadmap decision 7). Until then NoManagedSettings supplies nothing, and every
call site already reads through this module, so adding a source later needs no
changes elsewhere.
"""
MANAGED, USER, DEFAULT = "managed", "user", "default"


class NoManagedSettings:
    """Stand-in for a future managed source. A source returns {"options": {...}, "policy": {...}}."""
    def values(self): return {}


def managed_section(source, name):
    section = source.values().get(name, {})
    if not isinstance(section, dict): raise ValueError(f"Invalid managed {name}")
    return section


def option(name, default, user, managed):
    """(value, layer) for one scalar option."""
    if name in managed: return managed[name], MANAGED
    if name in user: return user[name], USER
    return default, DEFAULT


def policy(default, user, managed):
    """(policy, {key: layer}). Policy keys are exclusion lists, so managed entries are
    added to the user's list rather than replacing it: an administrator can require
    an exclusion, and the user can still add more but cannot remove it."""
    unknown = (set(user) | set(managed)) - set(default)
    if unknown: raise ValueError("Invalid policy keys")
    result, origin = {}, {}
    for key, fallback in default.items():
        values, origin[key] = (user[key], USER) if key in user else (fallback, DEFAULT)
        if key in managed:
            if not isinstance(managed[key], list): raise ValueError(f"Invalid policy: {key}")
            values, origin[key] = list(dict.fromkeys([*values, *managed[key]])), MANAGED
        result[key] = values
    return result, origin
