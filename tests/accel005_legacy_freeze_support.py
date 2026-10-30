"""Remove only the two exact reviewed Wave005 native-permission additions."""

_PRELOOKUP = """            if self._fpl_transport is None:
                from dmf_pulse.ingestion.fpl.direct import _require_supplier_route

                _require_supplier_route(
                    "GET", "fantasy.premierleague.com", f"/api/my-team/{request.entry_id}/", started
                )
"""
_FORWARD = """    @property
    def requires_supplier_permission(self) -> bool:
        from dmf_pulse.ingestion.fpl.direct import DirectUrllibTransport

        return (
            isinstance(self.delegate, DirectUrllibTransport)
            or getattr(self.delegate, "requires_supplier_permission", False) is True
        )

"""


def without_accel005_permission(source: str, path: str) -> str:
    fragments = {
        "src/dmf_pulse/private_v1/team_strength_live.py": _PRELOOKUP,
        "src/dmf_pulse/private_v1/team_strength_live_network.py": _FORWARD,
    }
    fragment = fragments[path]
    if source.count(fragment) != 1:
        raise ValueError("reviewed native-permission seam changed")
    return source.replace(fragment, "", 1)
