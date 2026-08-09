"""Level definitions for the tilt labyrinth.

The first four levels have no holes at all. Learning to meter a tilt is
already the hard part; punishing it with a reset before anyone has the feel
for it just teaches them the game is unfair. Difficulty comes from geometry
first - corridors, a pen, a staircase - and holes arrive small and well clear
of the racing line, then grow.

Board spans -12..12 on both axes. Walls are (cx, cz, half_w, half_d).
"""

BOARD_HALF = 12.0

LEVELS = [
    dict(
        name="first roll",
        walls=[(-4.0, 0.0, 8.0, 0.42)],
        holes=[],
        hole_r=1.15,
        start=(-9.0, -9.0),
        goal=(9.0, 9.0),
    ),
    dict(
        name="switchback",
        walls=[(-4.0, -4.5, 8.0, 0.42),
               (4.0, 4.5, 8.0, 0.42)],
        holes=[],
        hole_r=1.15,
        start=(-9.2, -9.6),
        goal=(9.0, 9.2),
    ),
    dict(
        name="the pen",
        walls=[(0.0, -5.0, 6.0, 0.42),
               (-6.0, 0.0, 0.42, 5.0),
               (6.0, 0.0, 0.42, 5.0),
               (-4.5, 5.0, 3.0, 0.42),
               (4.5, 5.0, 3.0, 0.42)],
        holes=[],
        hole_r=1.15,
        start=(-9.4, -9.6),
        goal=(0.0, 0.5),
    ),
    dict(
        name="steps",
        walls=[(-8.0, -6.5, 4.0, 0.42),
               (-1.0, -2.5, 4.0, 0.42),
               (5.5, 1.5, 4.0, 0.42),
               (-7.0, 5.5, 4.0, 0.42),
               (1.5, 9.0, 5.0, 0.42)],
        holes=[],
        hole_r=1.15,
        start=(-9.6, -10.2),
        goal=(9.2, 9.4),
    ),
    dict(
        name="first holes",
        walls=[(-4.0, -5.0, 8.0, 0.42),
               (4.0, 2.5, 8.0, 0.42)],
        holes=[(6.4, -8.8), (-6.2, -1.2)],
        hole_r=1.15,
        start=(-9.5, -10.2),
        goal=(9.0, 9.2),
    ),
    dict(
        name="threading",
        walls=[(-4.0, -6.0, 8.0, 0.42),
               (4.0, -0.5, 8.0, 0.42),
               (-4.0, 5.0, 8.0, 0.42)],
        holes=[(7.2, -9.2), (-7.4, -3.4), (1.2, -3.4), (7.0, 1.8)],
        hole_r=1.22,
        start=(-9.6, -10.2),
        goal=(9.2, 9.4),
    ),
    dict(
        name="the gauntlet",
        walls=[(-5.0, -7.0, 7.0, 0.42),
               (5.0, -2.5, 7.0, 0.42),
               (-5.0, 2.0, 7.0, 0.42),
               (5.0, 6.5, 7.0, 0.42)],
        holes=[(8.0, -9.6), (-2.0, -4.8), (-8.4, -4.8),
               (2.0, -0.2), (8.2, -0.2), (-3.0, 4.4), (3.6, 8.8)],
        hole_r=1.32,
        start=(-9.6, -10.4),
        goal=(9.1, 9.2),
    ),
    dict(
        name="the classic",
        walls=[(-4.0, -6.0, 8.0, 0.42),
               (4.0, -1.0, 8.0, 0.42),
               (-4.0, 4.0, 8.0, 0.42),
               (4.0, 7.0, 8.0, 0.42)],
        holes=[(-7.5, -8.6), (0.5, -8.2), (7.0, -3.6), (-1.5, -3.4),
               (-8.5, -3.2), (-6.0, 1.4), (2.5, 1.8), (7.6, 6.2),
               (-3.0, 6.6), (0.8, 9.6)],
        hole_r=1.42,
        start=(-9.6, -10.2),
        goal=(9.0, 9.6),
    ),
]


def get(index):
    """Levels loop, growing no harder once the last one is reached."""
    return LEVELS[min(index, len(LEVELS) - 1)]
