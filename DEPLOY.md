# Деплой на Beget VPS

Проверено локально (`docker-compose.prod.yml` + `Dockerfile`) — миграции и бот
поднимаются с нуля без ошибок. На сервере повторить те же шаги.

## 1. Подготовка сервера

- Docker + Docker Compose plugin установлены (`docker --version`, `docker compose version`)
- Код на сервере: `git clone https://github.com/elenakolodnitskay-web/arina.git` (или `git pull`, если уже клонирован)

## 2. `.env`

Скопировать `.env.prod.example` в `.env` и заполнить настоящими значениями:

```bash
cp .env.prod.example .env
```

- `TELEGRAM_BOT_TOKEN` — токен от @BotFather
- `POSTGRES_PASSWORD` — сгенерировать случайный пароль
- `DATABASE_URL` — тот же пароль, что в `POSTGRES_PASSWORD`, хост `postgres` (имя сервиса в docker-сети, не `localhost`)
- `OPENROUTER_API_KEY` — с openrouter.ai
- `OPENROUTER_BASE_URL` — **не** `https://openrouter.ai/api/v1` напрямую: с российских IP
  (Beget в их числе) OpenRouter отвечает `403` на любой запрос — гео-блокировка на
  уровне их WAF. Нужен релей: `https://arina-openrouter-relay.onrender.com/api/v1`
  (уже задеплоен и проверен, репозиторий — [arina-openrouter-relay](https://github.com/elenakolodnitskay-web/arina-openrouter-relay),
  на Render.com, не Cloudflare — Cloudflare Workers эту блокировку не обходят,
  подробности в `Plan.md`, раздел «Блокер верхнего уровня»). Значение уже стоит по
  умолчанию в `.env.prod.example`, менять не нужно, если не разворачиваете свой релей.
- `FERNET_KEY` — сгенерировать **один раз**:
  ```bash
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  **Никогда не менять после того, как в БД появятся данные** — потеря ключа делает все зашифрованные записи нечитаемыми навсегда.
- `ALLOWED_USER_IDS` — с кого начинать бету (можно с одного своего ID, расширять по мере приглашений)

## 3. Запуск

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Миграции (`alembic upgrade head`) применяются автоматически при каждом старте контейнера `bot` — безопасно, `alembic` идемпотентен (uже применённые миграции пропускает).

Проверить, что всё поднялось:

```bash
docker compose -f docker-compose.prod.yml logs -f bot
```

Ожидается:
```
INFO  [alembic.runtime.migration] ...
...
apscheduler.scheduler - INFO - Scheduler started
telegram.ext.Application - INFO - Application started
```

## 4. Ручной прогон перед открытием доступа

Пройти вживую весь путь пользователя из спецификации на своём Telegram ID из `ALLOWED_USER_IDS`:

1. `/start` → онбординг-опрос → «Профиль сохранён»
2. Свободное сообщение → содержательный ответ + кнопки «Рабочее»/«Личное»
3. `/task <текст с датой>` → напоминание приходит в заданное время
4. `/document <описание>` → черновик → «Подтвердить» → сохранено
5. `/delete_my_data` → все данные удалены

## 5. После открытия доступа

Периодически (раз в неделю) смотреть retention:

```bash
docker compose -f docker-compose.prod.yml exec bot python scripts/retention_report.py
```

## Обновление после новых коммитов

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Контейнер `bot` пересоберётся и перезапустится, применит новые миграции если есть;
`postgres` с данными не пересоздаётся (именованный volume `postgres_data`).
