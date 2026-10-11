# Квитто: API платежей на FastAPI

Небольшой сервис приёма оплаты курса онлайн-школы: три эндпоинта и вебхук банка.
Все суммы в API и в базе — **целые числа в копейках** (19 900 ₽ → `1990000`), float нигде не используется.

Стек: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite (PostgreSQL через `DATABASE_URL`), pytest + httpx.

## Запуск

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Сервис слушает `http://127.0.0.1:8000`, интерактивная документация — `http://127.0.0.1:8000/docs`.
При первом старте создаётся файл `kvitto.db` и три тарифа (повторный старт дублей не создаёт).

### Запуск через Docker

```bash
docker compose up --build
# с проверкой подписи вебхука:
WEBHOOK_SECRET=my-secret docker compose up --build
```

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

Каждый тест работает со своей временной SQLite-базой.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./kvitto.db` | Строка подключения. Для PostgreSQL: `postgresql+psycopg://user:pass@host/db` и `pip install "psycopg[binary]"` |
| `WEBHOOK_SECRET` | не задан | Секрет подписи вебхука. Не задан — подпись не проверяется |

## Эндпоинты

| Запрос | Результат |
|---|---|
| `GET /tariffs` | 200, `[{id, title, price}]` |
| `POST /payments` | 201 — платёж создан; 200 — платёж с таким `Idempotency-Key` уже есть; 422 — ошибка валидации |
| `GET /payments/{id}` | 200 или 404 |
| `POST /webhooks/bank` | 200 `{"result": "ok"}`; 404 — платежа нет; 409 `{"error": "invalid_transition"}`; 401 — неверная подпись |
| `GET /payments?email=&status=` | Бонус: список с фильтрами (`limit`, `offset` для постраничности) |

Платёж в ответах: `id, status, tariff_id, amount, discount, method, installment_months, schedule, email, created_at`.

## Примеры curl

(В PowerShell используйте `curl.exe` или Git Bash.)

```bash
# Тарифы
curl http://127.0.0.1:8000/tariffs

# Платёж с промокодом (регистр не важен), оплата картой
curl -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" \
  -d '{"tariff_id": 2, "email": "student@example.com", "method": "card", "promo_code": "kvitto10"}'

# Рассрочка на 3 месяца с ключом идемпотентности: повтор вернёт тот же платёж с кодом 200
curl -i -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" -H "Idempotency-Key: order-1001" \
  -d '{"tariff_id": 2, "email": "student@example.com", "method": "installment", "installment_months": 3}'
# -> "amount": 1990000, "schedule": [663334, 663333, 663333]

# Получить платёж (подставьте id из ответа)
curl http://127.0.0.1:8000/payments/<PAYMENT_ID>

# Уведомление от банка (без WEBHOOK_SECRET)
curl -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" \
  -d '{"payment_id": "<PAYMENT_ID>", "status": "succeeded"}'

# Уведомление с подписью (сервис запущен с WEBHOOK_SECRET=my-secret)
BODY='{"payment_id": "<PAYMENT_ID>", "status": "succeeded"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "my-secret" | awk '{print $NF}')
curl -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"

# Фильтры списка
curl "http://127.0.0.1:8000/payments?email=student@example.com&status=pending"
```

## Устройство

```
app/
  domain.py      # тарифы, промокоды, сроки рассрочки, таблица переходов, формулы (чистые функции)
  services.py    # работа с БД: создание платежа, идемпотентность, смена статуса
  schemas.py     # Pydantic-схемы и валидация
  models.py      # SQLAlchemy-модели Tariff, Payment
  routers/       # тонкие HTTP-обработчики
  security.py    # проверка подписи вебхука
  main.py        # create_app, lifespan (создание таблиц и тарифов), обработчик 409
tests/           # pytest: домен, платежи, идемпотентность, вебхуки, список
```

## Принятые решения (где задание допускает варианты)

- **Деньги.** `discount = price * percent // 100` (дробные копейки отбрасываются), `amount = price - discount`, поэтому `amount + discount == price` всегда. Сейчас все цены делятся на 10 нацело, но правило закреплено тестом на цене 1999.
- **График рассрочки.** `divmod(amount, months)`; остаток из `rem` копеек раскладывается по одной копейке в первые `rem` платежей. Сумма графика ровно равна `amount`.
- **Промокод.** `strip()` + верхний регистр. Пустая строка считается «не передан». Неизвестный код — 422.
- **Рассрочка.** Для `installment` поле `installment_months` обязательно (3, 6 или 12). Для `card` и `sbp` его передавать нельзя — 422 (чтобы не скрывать ошибку клиента). У платежей не в рассрочку `installment_months` и `schedule` равны `null`.
- **Неизвестный `tariff_id`** — 422 (в формате стандартной ошибки валидации FastAPI).
- **Идентификаторы.** `id` тарифа — целое число (1, 2, 3), `id` платежа — UUID4-строка. В путях и вебхуке `id` принимается как строка, поэтому любой несуществующий id даёт 404, а не 422.
- **Идемпотентность.** Сначала поиск по ключу, затем вставка; уникальный индекс в БД защищает от гонки, а при `IntegrityError` возвращается уже созданный платёж с кодом 200. Пустой или состоящий из пробелов ключ считается отсутствующим; длина ключа ≤ 255. Ключ глобально уникален. Если тот же ключ пришёл с другим телом, возвращается исходный платёж (как требует задание); сравнения тел запроса нет.
- **Статусы.** Разрешены только `pending → succeeded`, `pending → failed`, `succeeded → refunded`. Всё остальное, включая повтор того же статуса (`succeeded → succeeded`) и статус `pending` в вебхуке, — 409 `{"error": "invalid_transition"}`, статус не меняется. Смена статуса атомарна: `UPDATE ... WHERE id = :id AND status = :старый`, так что параллельный вебхук не перезапишет уже изменённый платёж.
- **Подпись вебхука (бонус).** Заголовок `X-Signature` — hex от HMAC-SHA256 над сырым телом запроса, без префикса. Сравнение через `hmac.compare_digest` по байтам. Проверка идёт до валидации тела (401 раньше 422); исключение — синтаксически битый JSON, который FastAPI отклоняет с 422 ещё до проверки. Без `WEBHOOK_SECRET` подпись не проверяется (при старте в лог пишется предупреждение).
- **Время.** `created_at` — UTC, ставится сервером.

## Бонусы

Сделано: `docker compose up`, проверка подписи вебхука, `GET /payments` с фильтрами, GitHub Actions (ruff + pytest), `CLAUDE.md`.
Не сделано: миграции Alembic (таблицы создаются при старте через `create_all`).
