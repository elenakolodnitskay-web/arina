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
3. `/task <текст с датой>` → напоминание приходит в заданное время; `/tasks` →
   кнопки «Изменить»/«Отменить» работают
4. `/document <описание>` → черновик → «Подтвердить» → приходит настоящий файл
   (.docx/.xlsx/.pdf, формат определяет модель по описанию)
5. Голосовое сообщение → распознаётся и обрабатывается так же, как текст
6. «потратила 500 в Пятёрочке» / «баланс 5000» → записывается как трата/баланс
7. `/delete_my_data` → все данные удалены (включая транзакции и лог писем)

## 5. После открытия доступа

Периодически (раз в неделю) смотреть retention:

```bash
docker compose -f docker-compose.prod.yml exec bot python scripts/retention_report.py
```

## 6. MAX (мессенджер) — опционально

Добавлена 2026-08-20, вне пронумерованных фаз плана — MVP-срез (нет пока инлайн-кнопок
коррекции, `/tasks`, `/document`; есть онбординг, свободный чат с автоклассификацией,
задачи/напоминания естественным языком, `/help`, `/delete_my_data`). Подробности и
известные упрощения — в `Plan.md`.

1. Токен: в MAX найти `@MasterBot` → `/create` → задать имя (оканчивается на `_bot`)
   → получить токен. Вписать в `.env` как `MAX_BOT_TOKEN`, придумать `MAX_WEBHOOK_SECRET`
   (произвольная строка).
2. Нужен публичный HTTPS-адрес — переиспользуем существующий бесплатный домен вида
   `<ip-через-дефисы>.sslip.io` (резолвится в IP сервера без покупки домена) и уже
   выпущенный для него Let's Encrypt сертификат, если такой уже есть на сервере (было
   так на момент написания — см. `/etc/letsencrypt/live/`). Добавить в существующий
   nginx-конфиг с `listen 443 ssl` для этого домена новый `location`, ничего в
   остальном конфиге не трогая:
   ```nginx
   location /arina-max/ {
       proxy_pass http://127.0.0.1:8091/webhook;
       proxy_set_header Host $host;
   }
   ```
   Проверить `nginx -t`, затем `systemctl reload nginx`.
3. После `docker compose -f docker-compose.prod.yml up -d --build` (контейнер `bot`
   слушает `:8091` изнутри и наружу на `127.0.0.1:8091`, см. `docker-compose.prod.yml`)
   зарегистрировать вебхук один раз:
   ```bash
   curl -X POST "https://platform-api2.max.ru/subscriptions" \
     -H "Authorization: $MAX_BOT_TOKEN" -H "Content-Type: application/json" \
     -d '{"url": "https://<домен>/arina-max/", "update_types": ["message_created"], "secret": "$MAX_WEBHOOK_SECRET"}'
   ```
4. Проверить логи контейнера — должна появиться строка `MAX webhook server started
   on port 8091`. Написать боту в MAX — должен пройти тот же онбординг, что в Telegram.

## 7. Email-напоминания через Resend — опционально

Добавлено в Фазе 18 (`Plan.md`) — отправка письма-напоминания на email контактам,
у которых нет Арины. Без ключа функция просто недоступна (понятная ошибка
пользователю), остальной бот работает как обычно.

1. Зарегистрироваться на [resend.com](https://resend.com), получить API-ключ —
   вписать в `.env` как `RESEND_API_KEY`.
2. Верифицировать свой домен в Resend (Domains → Add Domain, добавить DNS-записи) —
   без верифицированного домена можно слать только на адрес владельца аккаунта через
   тестовый `onboarding@resend.dev`. `EMAIL_FROM_ADDRESS` — адрес с верифицированного
   домена, например `Арина <arina@ваш-домен.ru>`.
3. `docker compose -f docker-compose.prod.yml up -d --build` — переменные подхватятся
   при пересоздании контейнера `bot`.
4. Проверить вживую: «напиши на свой-email@..., что это тест» → черновик →
   «Отправить» → письмо должно прийти.

## Обновление после новых коммитов

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Контейнер `bot` пересоберётся и перезапустится, применит новые миграции если есть;
`postgres` с данными не пересоздаётся (именованный volume `postgres_data`).
