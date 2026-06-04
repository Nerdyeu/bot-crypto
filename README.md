# trading_bot — bot de trading crypto (sécurité d'abord)

Un bot de trading de cryptomonnaies en Python, construit **étape par étape**, où
la **sécurité**, la **gestion du risque** et la **testabilité** passent avant la
performance.

> ⚠️ **Avertissement**
> Le trading de cryptomonnaies comporte un risque de perte en capital. Ce logiciel
> est fourni à des fins éducatives. Le mode par défaut est la **simulation
> (`paper`)** : aucun ordre réel ne peut être passé sans une série de garde-fous
> explicites (voir « Modèle de sécurité » plus bas). **N'utilisez le mode `live`
> qu'en pleine connaissance de cause, et d'abord sur le testnet de l'exchange.**

---

## 🧭 Principes non négociables

1. **Mode par défaut = `paper`** (simulation). Le réel (`live`) ne s'active qu'avec
   `TRADING_MODE=live` **ET** le flag `--i-understand-the-risks` **ET** une
   confirmation tapée à la main.
2. **Aucune clé API en dur.** Tout vient de variables d'environnement / `.env`
   (git-ignoré). Le bot vérifie la présence des clés avant tout passage en réel.
3. **Clés API sans permission de retrait (withdraw).** À configurer côté exchange
   (voir ci-dessous).
4. **Pas de levier ni de marge en V1.** Spot uniquement.
5. **Limites de risque** codées **et** configurables, vérifiées avant **chaque**
   ordre.
6. **Tout ordre réel est loggé** (horodatage, paire, sens, taille, prix, raison).
7. **Dans le doute, le bot s'arrête** plutôt que de continuer.

---

## 📦 État du projet (jalons)

La construction est **incrémentale**. Chaque jalon est validé avant le suivant.

| Jalon | Contenu | Statut |
|------:|---------|:------:|
| 1 | Structure + `config.py` + `.env.example` + `README.md` | ✅ **Fait** |
| 2 | `exchange.py` en lecture seule (prix, solde, OHLCV sur testnet) | ⏳ à venir |
| 3 | `strategy.py` (croisement de SMA) + tests | ⏳ à venir |
| 4 | `backtest.py` + rapport (rendement, drawdown, win rate) | ⏳ à venir |
| 5 | `risk.py` (tous les garde-fous) + tests | ⏳ à venir |
| 6 | `paper.py` (simulation temps réel) | ⏳ à venir |
| 7 | `executor.py` + mode `live` verrouillé (en dernier) | ⏳ à venir |

---

## 🗂️ Architecture

```
bot-crypto/
├─ trading_bot/
│  ├─ __init__.py
│  ├─ config.py        # chargement + validation de la config (pydantic)   ✅
│  ├─ logger.py        # logging fichier rotatif + console                  ✅
│  ├─ main.py          # point d'entrée + CLI (--mode), bannière de démarrage ✅
│  ├─ exchange.py      # wrapper ccxt (lecture seule d'abord)         (jalon 2)
│  ├─ strategy.py      # génération de signaux BUY/SELL/HOLD          (jalon 3)
│  ├─ backtest.py      # rejoue des données historiques + rapport     (jalon 4)
│  ├─ risk.py          # garde-fous (le module le plus important)     (jalon 5)
│  ├─ paper.py         # simulation temps réel (portefeuille virtuel) (jalon 6)
│  ├─ executor.py      # orchestration + verrou live                  (jalon 7)
│  ├─ data/            # CSV historiques (contenu git-ignoré)
│  └─ tests/           # tests unitaires (sans réseau ni exchange réel)
│     └─ test_config.py
├─ .env.example        # modèle de configuration (sans secrets)
├─ .gitignore
├─ requirements.txt
├─ pyproject.toml
└─ README.md
```

---

## ✅ Prérequis

- **Python 3.11+**

## ⚙️ Installation

```bash
# 1) Environnement virtuel
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate

# 2) Dépendances
pip install -r requirements.txt
```

## 🔧 Configuration

```bash
cp .env.example .env
# puis éditez .env
```

Le fichier `.env` (git-ignoré) contient toute la configuration. Les valeurs par
défaut sont **sûres** : `paper`, testnet activé, limites de risque prudentes.
Voir `.env.example` pour la liste commentée de **toutes** les variables.

Variables principales :

| Variable | Rôle | Défaut |
|----------|------|--------|
| `TRADING_MODE` | Verrou de sécurité (`paper` \| `live`) | `paper` |
| `EXCHANGE_ID` | Exchange ccxt | `binance` |
| `USE_SANDBOX` | Utiliser le testnet quand disponible | `true` |
| `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` | Clés (vides pour paper/backtest) | vide |
| `SYMBOL` | Paire (`BASE/QUOTE`) | `BTC/USDT` |
| `TIMEFRAME` | Période des bougies | `1h` |
| `INITIAL_CAPITAL` | Capital de départ (devise de cotation) | `1000` |
| `RISK__MAX_POSITION_PCT` | Taille max par trade | `0.02` (2%) |
| `RISK__MAX_DAILY_LOSS_PCT` | Perte journalière max | `0.05` (5%) |
| `RISK__KILL_SWITCH_FLOOR_PCT` | Plancher kill-switch | `0.80` (80%) |
| `RISK__MAX_TRADES_PER_DAY` | Nb max de trades/jour | `10` |
| `RISK__STOP_LOSS_PCT` | Stop-loss obligatoire | `0.02` (2%) |
| `STRATEGY__SHORT_WINDOW` / `STRATEGY__LONG_WINDOW` | Périodes des SMA | `20` / `50` |

> Les paramètres imbriqués utilisent le délimiteur `__`, par ex.
> `RISK__MAX_POSITION_PCT`.

### 🔐 Rappel important — clés API **sans retrait**

Quand vous créerez vos clés API côté exchange :

- **Décochez / n'activez PAS la permission de retrait (« Withdraw »/« Enable
  Withdrawals »).** Le bot n'a besoin que de **lire** le marché et de **passer des
  ordres spot**.
- Restreignez si possible l'accès par **IP**.
- Commencez sur le **testnet/sandbox** (`USE_SANDBOX=true`).
- Ne partagez jamais votre `.env` et ne le committez jamais (il est dans
  `.gitignore`).

---

## ▶️ Lancement

> Lancez les commandes **depuis la racine du dépôt**.

```bash
# Mode paper (simulation) — c'est le défaut
python -m trading_bot.main --mode paper

# Backtest (rejoue des données historiques, aucune connexion de trading)
python -m trading_bot.main --mode backtest

# Live (réel) — VERROUILLÉ tant que le jalon 7 n'est pas validé
python -m trading_bot.main --mode live
```

Au démarrage, le bot affiche une **bannière** récapitulant le mode, l'exchange, le
capital et les limites de risque actives.

> À ce jalon (1), les modes `backtest`/`paper`/`live` chargent et valident la
> configuration puis s'arrêtent : la logique de trading arrive aux jalons
> suivants. Le mode `live` refuse explicitement de démarrer.

---

## 🛡️ Modèle de sécurité (mode `live`)

Un ordre **réel** ne sera jamais passé sauf si **TOUTES** ces conditions sont
réunies (mises en place au jalon 7) :

1. `--mode live` (CLI)
2. `TRADING_MODE=live` (environnement)
3. `--i-understand-the-risks` (flag CLI)
4. une **confirmation tapée à la main** au lancement

Si l'une manque → le bot **refuse** de trader en réel et reste en simulation.

### Limites de risque (vérifiées avant chaque ordre — jalon 5)

- **Taille max par position** : jamais plus de `RISK__MAX_POSITION_PCT` du capital.
- **Perte journalière max** : au-delà, arrêt du trading jusqu'au lendemain.
- **Kill-switch** : si le capital passe sous `RISK__KILL_SWITCH_FLOOR_PCT` du
  capital initial, le bot se désactive et alerte.
- **Stop-loss obligatoire** sur chaque position.
- **Nombre max de trades/jour**.
- **Solde minimum** pour trader.

Tout blocage est loggé avec une **raison claire**.

---

## 🧪 Tests

Les tests **ne touchent jamais** un exchange réel ni le réseau.

```bash
pytest
```

Au jalon 1, `trading_bot/tests/test_config.py` couvre le chargement de la config,
les valeurs par défaut sûres, les surcharges via variables d'environnement, les
échecs de validation, et le **masquage des secrets** dans les logs.

---

## 🪵 Logging

- Sortie **console** + **fichier rotatif** (`logs/trading_bot.log` par défaut).
- Les secrets (clés API) **ne sont jamais écrits** dans les logs (ils sont
  masqués).
- Au démarrage : mode, exchange, capital et limites de risque actives.
- Hooks d'alerte (log d'alerte ; option Telegram) pour le kill-switch et la perte
  journalière (jalons 5/6).
