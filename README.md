# SmokeCRM — Playwright MCP · IA QA

> CRM de smoke tests API alimenté par Claude (Anthropic) — interface web intégrée, alertes automatiques Slack/email, diagnostic IA en temps réel, zéro infrastructure lourde.

![Python](https://img.shields.io/badge/Python-3.11+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green) ![Playwright](https://img.shields.io/badge/Playwright-1.45-orange) ![Claude](https://img.shields.io/badge/Claude-Haiku-purple) ![Jinja2](https://img.shields.io/badge/UI-Jinja2-lightgrey)

## Installation

### Linux / macOS

```bash
pip install -r requirements.txt && playwright install chromium
cp .env.example .env  # renseigner ANTHROPIC_API_KEY + APP_BASE_URL
uvicorn api:app --reload --port 8000
```

### Windows

Sur Windows, pip installe les scripts dans un dossier `Scripts` souvent absent du PATH. Utiliser `python -m` pour contourner :

```bash
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env   # renseigner ANTHROPIC_API_KEY + APP_BASE_URL
python -m uvicorn api:app --reload --port 8000
```

> **Solution permanente (optionnelle)** — ajouter le dossier Scripts au PATH pour ne plus avoir à préfixer `python -m` :
> ```bash
> setx PATH "%PATH%;C:\Users\<TON_USER>\AppData\Roaming\Python\Python313\Scripts"
> ```
> Relancer le terminal après cette commande.

Ouvrir `http://localhost:8000` — c'est tout.

## Pourquoi ce projet

Les équipes QA passent 2h/jour à analyser des rapports de test et créer des tickets Jira manuellement. SmokeCRM automatise 100 % de ce travail :

- **Exécute** les smoke tests API via Playwright en parallèle toutes les 15 minutes (ou manuellement via le bouton UI)
- **Analyse** les échecs avec Claude Haiku — 1 seul appel batché pour tous les échecs = −99 % de tokens
- **Alerte** Slack + email automatiquement avec diagnostic structuré et fix suggéré
- **Affiche** un dashboard web complet avec KPIs, graphiques de tendance et historique

## Interface web (Jinja2 + FastAPI)

Trois pages accessibles depuis `http://localhost:8000` :

| Page | URL | Contenu |
|---|---|---|
| Dashboard | `/` | KPIs, panneau alertes, graphiques 14j, table des runs récents, monitoring tokens |
| Test cases | `/tests` | Catalogue complet des smoke tests (endpoint, méthode, criticité, tags) |
| Historique | `/runs` | Tous les runs avec pass rate, tokens consommés et coût par run |

## Architecture

```
Scheduler APScheduler (toutes les 15 min) + bouton UI
       ↓
  Playwright Runner — API mode, parallèle (runner.py)
       ↓
  Filtre : échecs uniquement (95 % des cas → 0 token Claude)
       ↓
  Claude Haiku — 1 appel batché (analyser.py)
       ↓
  Slack blocks API + email SMTP (alerts.py)
       ↓
  SQLite async — aiosqlite (storage.py)
       ↓
  FastAPI + Jinja2 → Dashboard web (api.py + templates/)
```

## Structure du projet

```
smokecrm/
├── api.py              — FastAPI : routes UI (Jinja2) + API JSON + scheduler
├── orchestrator.py     — Pipeline complet run → analyse → alerte → stockage
├── runner.py           — Playwright API mode, exécution parallèle
├── analyser.py         — Agent Claude Haiku, batch optimisé tokens
├── alerts.py           — Slack Blocks API + email SMTP
├── storage.py          — SQLite async (aiosqlite)
├── models.py           — Schémas Pydantic typés
├── catalogue.py        — 8 smoke tests préconfigurés (SMK-001 à SMK-008)
├── templates/
│   ├── base.html       — Layout sidebar + navigation + CSS
│   ├── dashboard.html  — Page principale (KPIs, alertes, charts, table)
│   ├── tests.html      — Catalogue des smoke tests
│   └── runs.html       — Historique des runs
├── test_analyser.py    — 4 tests pytest (mock Anthropic, zéro appel API réel)
├── requirements.txt
└── .env.example
```

## Optimisation tokens Claude

| Scénario | Tokens/run | Coût/run |
|---|---|---|
| Sans optimisation (brut) | ~40 000 | ~0,12 € |
| Avec SmokeCRM (filtré + batché) | ~387 | ~0,0001 € |
| **Réduction** | **−99 %** | **−99 %** |

**Coût mensuel estimé (10 runs/jour) : ~0,55 €.**

Trois règles appliquées : (1) appeler Claude uniquement sur les échecs, jamais sur les tests passés ; (2) compresser chaque log à 5 lignes avant l'envoi ; (3) grouper tous les échecs en un seul appel batché.

## API JSON (pour PowerBI ou intégrations)

```
POST /api/run       Déclenche un run et retourne le rapport
GET  /api/runs      Historique des runs (param: limit)
GET  /api/results   Résultats détaillés (param: limit)
GET  /api/health    Santé du service + état du scheduler
```

## Tests

```bash
pip install pytest pytest-asyncio
pytest test_analyser.py -v
# 4 passed — zéro appel API réel (mock Anthropic)
```

## Variables d'environnement

| Variable | Description | Requis |
|---|---|---|
| `ANTHROPIC_API_KEY` | Clé API Anthropic | ✓ |
| `APP_BASE_URL` | URL de base de l'app à tester | ✓ |
| `APP_ENV` | Environnement (staging, prod…) | ✓ |
| `SLACK_WEBHOOK_URL` | Webhook Slack pour alertes | optionnel |
| `ALERT_EMAIL` | Email destinataire des alertes | optionnel |
| `SMTP_HOST/PORT/USER/PASS` | Config SMTP pour les emails | optionnel |
| `RUN_INTERVAL_MINUTES` | Intervalle du scheduler (défaut: 15) | optionnel |

## Limites connues

- L'analyse Claude est probabiliste — toujours vérifier les diagnostics `is_real_bug: true` avant de créer un ticket Jira en production
- Playwright API mode ne supporte pas les flows OAuth multi-étapes (token statique requis)
- SQLite local — migrer vers PostgreSQL pour un déploiement multi-équipes
- Le scheduler redémarre à chaque restart du serveur (les runs planifiés ne persistent pas en mémoire)

## Roadmap

- [ ] Intégration Jira — création automatique de tickets depuis le diagnostic Claude
- [ ] Export CSV pour dashboard PowerBI
- [ ] Support multi-environnements dans la même instance
- [ ] Flakiness scoring par endpoint (taux d'instabilité sur 30 jours glissants)
- [ ] Serveur MCP exposant les capacités SmokeCRM à un agent Claude externe
- [ ] Auth basique (login/password) pour déploiement en équipe
