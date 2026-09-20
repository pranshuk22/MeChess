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
| `greeting.hello` | say that the bot is a research bot with **deliberately limited strength** | Lichess expects bots that do not try to win to say so, especially in rated games |

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

## Licences and privacy

lichess-bot is AGPL-3.0: run it as a separate program and keep its checkout out of this repository. Games are public. A bot that plays your own book or a prior
fine-tuned on your games exposes your repertoire; a prior derived from Maia weights has its own terms (see [third-party software](third-party.md)).
