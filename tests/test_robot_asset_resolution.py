from __future__ import annotations

from isaac_sim_mcp_extension.handlers import robots


def test_franka_alias_resolves_to_panda_instead_of_shortest_fuzzy_match(monkeypatch) -> None:
    monkeypatch.setattr(
        robots,
        "_discovered_robots",
        {
            "fr3": {
                "asset_path": "/Isaac/Robots/FrankaRobotics/FR3/fr3.usd",
                "description": "FrankaRobotics FR3",
                "manufacturer": "FrankaRobotics",
            },
            "frankapanda": {
                "asset_path": "/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd",
                "description": "FrankaRobotics FrankaPanda",
                "manufacturer": "FrankaRobotics",
            },
        },
    )

    match = robots._find_robot(object(), "franka")

    assert match is not None
    assert match["key"] == "frankapanda"
