"""Preparing against one opponent: read their public games, find where their play is weak (openings first, then middlegames, endgames and the clock), and work out
which openings you should steer into. The modules here are pure logic (no network, no database, the engine comes in as a `search(board)` callable) so that they
are tested with scripted data; `chessme.app.prep_job` and `chessme.app.routers.prep` connect them to the app."""
