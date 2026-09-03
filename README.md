# YCLIENTS Operations

Закрытый переносимый проект для:

- read-only сверки продаж, клиентов и истории абонементов;
- формирования аналитических таблиц;
- безопасной выдачи новых абонементов;
- проверки transaction/document и post-write состояния;
- идемпотентного повторного запуска с `0 writes`.

## Важно

В репозитории **нет действующих токенов, SSH-ключей, Google OAuth-файлов, клиентских выгрузок или ledger**. Каждый оператор использует отдельную учётную запись и отдельные отзываемые credentials.

## Структура

- `app/` — рабочие Python-скрипты и mapping типов консультаций.
- `tests/` — unit-тесты safety-инвариантов.
- `skills/yclients-subscription-reporting/` — полный процедурный runbook.
- `config/` — только примеры конфигурации.
- `runtime/` — локальные dry-run, ledger и audit; не коммитятся.
- `docs/` — модель доступа и безопасности.

## Установка

```bash
cd /path/to/yclients-ops
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export YCLIENTS_OPS_HOME="$PWD"
```

Создайте `secrets/`, скопируйте туда шаблоны без суффикса `.example`, заполните **отдельными** credentials и ограничьте права:

```bash
install -d -m 700 secrets runtime
chmod 600 secrets/*
```

## Тесты

```bash
PYTHONPATH=app python -m unittest discover -s tests -v
```

## Dry-run выдачи за включительный период

```bash
PYTHONPATH=app python app/build_subscription_dry_run.py \
  --start 2026-09-01 --end 2026-09-03
```

Telegram override допускается только после подтверждения пользователя и exact email:

```bash
--telegram-override 'client@example.com=@confirmed_username'
```

## Массовая выдача

Сначала запуск без `--execute`:

```bash
PYTHONPATH=app python app/mass_yclients_subscriptions.py \
  --start 2026-09-01 --end 2026-09-03
```

Write-запуск допустим только после ручной проверки dry-run manifest:

```bash
PYTHONPATH=app python app/mass_yclients_subscriptions.py \
  --start 2026-09-01 --end 2026-09-03 --execute
```

После него обязательно выполнить независимую проверку и повторный execute, который должен вернуть `0 writes`.

## Google Sheets аналитика

Укажите отдельный Google OAuth-файл и Spreadsheet ID:

```bash
export GOOGLE_SHEETS_ID='spreadsheet-id'
export GOOGLE_TOKEN_FILE="$PWD/secrets/google_token.json"
PYTHONPATH=app python app/rebuild_overall_monthly_structure.py
```

Этот скрипт изменяет вкладку `Общее`; перед запуском проверьте доступ и целевую таблицу.

## Правила

Обязательные safety-инварианты находятся в `AGENTS.md` и skill `skills/yclients-subscription-reporting/SKILL.md`.
