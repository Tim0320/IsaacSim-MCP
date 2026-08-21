"""Minimal ScriptNode controller used by live MCP Action Graph checks."""

COUNT = 0


def setup(db):
    import omni.usd
    from pxr import Sdf

    prim = omni.usd.get_context().get_stage().DefinePrim("/World/MCPActionGraphFileMarker", "Xform")
    attr = prim.GetAttribute("test:ticks")
    if not attr.IsValid():
        attr = prim.CreateAttribute("test:ticks", Sdf.ValueTypeNames.Int, custom=True)
    attr.Set(0)


def compute(db):
    global COUNT

    import omni.usd

    COUNT += 1
    prim = omni.usd.get_context().get_stage().GetPrimAtPath("/World/MCPActionGraphFileMarker")
    prim.GetAttribute("test:ticks").Set(COUNT)
    return True
