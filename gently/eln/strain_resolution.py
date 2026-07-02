"""Display-side strain resolution — non-mutating, bare-string safe.

A strain reference that matches no record becomes a ``{"name": ref}`` shim, so the
UI always has something to show and no migration is forced.
"""

from __future__ import annotations


def resolve_ref(store, ref):
    """Resolve a strain ref to its record, or a ``{"name": ref}`` shim, or None."""
    if not ref:
        return None
    rec = store.resolve_strain(ref)
    return rec if rec else {"name": ref}


def enrich_imaging_spec(store, spec_dict):
    """Return a copy of an imaging-spec dict with a ``strain_record`` attached.

    Non-mutating: the input dict is untouched and the raw ``strain`` string stays.
    """
    out = dict(spec_dict)
    ref = out.get("strain")
    if ref:
        out["strain_record"] = resolve_ref(store, ref)
    return out
