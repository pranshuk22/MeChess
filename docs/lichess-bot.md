# Running MeChess as a Lichess bot

A bot account lets other players (and other bots) play MeChess, and gives the calibrated dial a real Lichess rating to be compared with.
It uses [lichess-bot](https://github.com/lichess-bot-devs/lichess-bot) (AGPL-3.0), which is installed **next to** this repository, never copied into it.

## 1. The account and the token

1. Create a **new** Lichess account for the bot. **It must not have played any game**, and upgrading is **irreversible**: the account can only play as a
   bot afterwards (see the [API documentation](https://lichess.org/api#tag/Bot/operation/botAccountUpgrade)). Never use your personal account.
2. Create an API token for it with **only** the `bot:play` scope: <https://lichess.org/account/oauth/token/create?scopes[]=bot:play>. Lichess shows the token once.
3. **The token lives only in the environment variable `LICHESS_BOT_TOKEN`.** lichess-bot reads that variable and it overrides the `token` field of
   `config.yml`, so the file only holds a placeholder. Never put the token in a file, a commit or a chat. In the terminal where you will run the
   bot (the variable exists only in that terminal):

   ```bash
   read -s LICHESS_BOT_TOKEN; export LICHESS_BOT_TOKEN     # paste the token, press Enter; nothing is echoed
   ```

   If a token is ever exposed, revoke it at <https://lichess.org/account/oauth/token> and create another.

## 2. Upgrade the account to a bot (once)

Check that it is the right, fresh account (prints the name, title and number of games played; the games must be 0):

```bash
curl -s https://lichess.org/api/account -H "Authorization: Bearer $LICHESS_BOT_TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['username'], d.get('title'), 'games:', d['count']['all'])"
```

Then upgrade (irreversible):

```bash
curl -d '' https://lichess.org/api/bot/account/upgrade -H "Authorization: Bearer $LICHESS_BOT_TOKEN"     # {"ok":true}
```

(`python3 lichess-bot.py -u` does the same, and then starts playing.)

## 3. Install lichess-bot and point it at MeChess

```bash
mkdir bot && git clone --depth 1 https://github.com/lichess-bot-devs/lichess-bot.git bot/lichess-bot     # /bot/ is git-ignored
python3 -m venv bot/venv && bot/venv/bin/pip install -r bot/lichess-bot/requirements.txt
```

Engine wrapper `bot/lichess-bot/engines/mechess-bot.sh` (make it executable). Use the prior, book and calibration file you want the public
to play against; the example uses the uniform prior and no book, so nothing about your own play is exposed:

```bash
#!/bin/bash
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$(dirname "$0")/../../.."
exec .venv/bin/python -m chessme mechess --engine engine/build/chessme-engine --prior uniform \
     --calibration data/calibration/dial_uniform.json
```

For a bot that plays *like you*, use your own book first and the theory book of the level second, your style prior, and a calibration measured for
exactly that configuration (`tools/after_calibration.sh` fits the style model, smoke-tests, calibrates and writes this script):

```bash
exec .venv/bin/python -m chessme mechess --engine engine/build/chessme-engine --book profiles/<you>/book.bin,data/explorer \
     --prior style=data/style/mechess_style.json --calibration data/calibration/dial_mechess.json
```

`data/explorer` holds the theory books built by the opening explorer; when a longer explorer run finishes, copy its `theory_*.bin` files over
them and the bot uses them at its next start.

In `bot/lichess-bot/config.yml` (copy of `config.yml.default`) the settings that matter:

| Setting | Suggested | Why |
|---|---|---|
| `engine.name` / `engine.protocol` | `mechess-bot.sh` / `uci` | the wrapper above |
| `engine.uci_options.Elo` | the target strength (with a calibration file: the *measured* Elo, on Stockfish's scale) | the dial |
| `engine.ponder` | `false` | MeChess does not ponder |
| `engine.draw_or_resign.*_enabled` | `false` | MeChess does not report scores |
| `challenge.time_controls` | `blitz`, `rapid` | MeChess ignores the clock and spends the dial's search budget; very fast games can flag |
| `challenge.min_base` / `max_base` | 180 / 900 | same reason |
| `challenge.concurrency` | 1 | one game at a time keeps the timing predictable |
| `matchmaking.allow_matchmaking` | `false` at first | no unsolicited challenges until you decide |
| `greeting.hello` | say that the bot is a research bot with **deliberately limited strength**, in **at most 140 characters after `{me}` is replaced by the bot's name** | Lichess expects bots that do not try to win to say so, especially in rated games; longer chat messages are silently not sent (check `bot.log` for a WARNING) |

### Keeping the token out of files but available to a launcher (macOS)

The variable set with `read -s ... ; export ...` exists only in that one terminal. To let a launcher script (or an assistant running it in the
background) start the bot without you pasting the token again, store it in the macOS Keychain, which is encrypted and not a plain file. Run this
in your own terminal (it asks for the token without echoing it):

```bash
security add-generic-password -a "$USER" -s lichess-bot-token -w
```

The launcher `bot/run-bot.sh` (kept beside the checkout, git-ignored) uses `LICHESS_BOT_TOKEN` if set, otherwise reads that Keychain item with
`security find-generic-password -w`; the first read may show a system prompt asking you to allow access. Remove it later with
`security delete-generic-password -a "$USER" -s lichess-bot-token`.

## 4. Run

```bash
cd bot/lichess-bot && ../venv/bin/python lichess-bot.py          # in the terminal where LICHESS_BOT_TOKEN is set
```

Challenge the bot from your own account to test it. Bots may play at most 100 games per day against other bots; games against humans are unlimited.

## Comparing the dial with Lichess ratings

Play a few dozen rated games at a fixed `Elo` setting; the bot's Lichess rating (Glicko-2, provisional at first, with its deviation shown) then
estimates that setting on the Lichess scale. Several settings and enough games (roughly 50 or more per setting) are needed before a constant offset between
the Stockfish scale and Lichess can be trusted; set it as `offset` in the calibration file only after that.

## How much it plays like you (held-out check)

`chessme mechess-agreement` asks, on games the bot was not built from, how much probability the bot gives the moves you actually played. One run
(1,142 newest games kept out of the personal book; 800 positions from held-out games for the move check; the bot's dial at the position's rating):

| | Result |
|---|---|
| Your own book (from the older games), your first 20 plies | in the book for **50%** of your moves; the probability it gives your move over all of them **42%** (85% where it has the position) |
| Theory book of your rating | in the book for 39%; probability of your move 17% |
| Both stacked (yours first) | 51% covered; 43% |
| Your move among the engine's candidates at your rating | 68% (the other 32% were outside the candidate window: your mistakes or unusual moves) |
| Probability of your move: engine's own ranking / with your style prior | **20.6% / 24.5%** |

So the opening is clearly yours (42% against 17% for generic theory), while your style prior adds about 4 points over the engine's own ranking in the
middlegame: real but small, as the style analysis predicted. The error of 800 positions is about a point, and a paired significance test is not
included. The clock and the blunders you make are not modelled, which is why the bot cannot match the 32% of your moves that lie outside the engine's window.

### Widening the candidate window did not help

The 32% of your moves that the engine's candidates miss are your mistakes and unusual moves. Widening the window (window x1.5 to x4 with 1 to 6 extra
lines) reaches more of them (68% up to 85% of your moves) but *lowers* the probability given to the move you played (24.5% down to 20.7%), because the
probability spreads over more candidates, and it raises the expected loss per move from 13 to 25 centipawns, i.e. a weaker bot. Retuning the
temperature and the strength scale with the wider window gave 23% to 26%, within the noise of 800 positions, and tuning on the same positions
would flatter it anyway. So the calibrated dial stays as it is and no recalibration was needed (`mechess-agreement --sweep` reproduces the table).

### Clock habits

The bot searches in a fraction of a second, so it used to answer every move at once. `chessme mechess-clock-fit` learns from your Lichess games how much
of the time left you use, per time control, stage of the game and kind of move (a recapture or a nearly forced move is fast), and keeps the empirical
distribution, so the bot's delays have your spread. `mechess --clock data/style/clock_model.json` makes the bot wait accordingly whenever lichess-bot sends
the clocks with `go` (it does); it never uses more than a quarter of what is left. `--clock-strength 0` turns it off.

Held-out games (every 7th game kept out of the fit), think time per move, yours against the model, and the distance (Kolmogorov-Smirnov, 0 = identical)
to your real distribution for the model and for a bot that answers at once:

| Time control | your moves | yours (median / mean) | model (median / mean) | distance: model / at once |
|---|---|---|---|---|
| bullet | 11,654 | 1.0s / 1.6s | 1.0s / 1.7s | 0.07 / 0.38 |
| blitz | 5,852 | 2.0s / 3.6s | 2.0s / 4.3s | 0.05 / 0.66 |
| rapid | 3,172 | 3.0s / 6.6s | 3.0s / 7.3s | 0.03 / 0.79 |

Lichess clocks are whole seconds, so short thoughts are recorded as 0 or 1. The model does not think longer where the position is hard (beyond the
simple-move flag), and your clock trouble (tilt, flagging) is not modelled.

## Licences and privacy

lichess-bot is AGPL-3.0: run it as a separate program and keep its checkout out of this repository. Games are public. A bot that plays your own book or a prior
fine-tuned on your games exposes your repertoire; a prior derived from Maia weights has its own terms (see [third-party software](third-party.md)).
