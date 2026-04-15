---
type: context
status: active
owner: schankel
updated: 2026-04-14
tags: [vpn, horizonnetvpn, amnezia, wireguard, telegram-bot, second-brain]
project: HorizonNetVPN
---

# CONTEXT — HorizonNetVPN (for Obsidian transfer)

## 1) Цель задачи
- Что нужно получить на выходе: продаваемый VPN-доступ через Telegram-бота с управлением клиентами через API.
- Почему это важно: автоматизировать выдачу/продление/отзыв доступов и не зависеть от ручных операций.

## 2) Текущая ситуация
- Что уже сделано:
  - Создан отдельный стек в `amnezia/`, без изменений в `3-x-ui/`.
  - Поднят FastAPI control plane с API жизненного цикла клиента и админ-UI.
  - Добавлены deploy-артефакты (systemd, nginx-гайд, wg-easy compose).
  - Подключен GitHub workflow деплоя через `git pull` на VPS.
- Что не работает/тормозит:
  - HTTPS для `horizonnetvpn.ru` отдает не тот сертификат (SNI уходит в другой nginx vhost).
  - Провайдер пока `MockProvider`, нет боевой интеграции с WireGuard backend API.
- На каком этапе сейчас:
  - Этап инфраструктуры и стабилизации прод-контура перед подключением Telegram-бота/биллинга.

## 3) Входные данные
- Файлы проекта:
  - `amnezia/control_plane/app/main.py`
  - `amnezia/control_plane/app/provider/base.py`
  - `amnezia/control_plane/app/provider/mock.py`
  - `amnezia/control_plane/tests/test_api.py`
  - `amnezia/wg_backend/docker-compose.yml`
  - `amnezia/deploy/horizonnetvpn-control-plane.service`
  - `amnezia/README.md`
  - `amnezia/DEPLOY.md`
  - `amnezia/docs/WG_BACKEND.md`
- Инфраструктурные параметры:
  - Сервер: `109.172.93.80`
  - Домен: `horizonnetvpn.ru`, `www.horizonnetvpn.ru`
  - App path: `/opt/horizonnetvpn/app`
  - Service: `horizonnetvpn-control-plane` (`127.0.0.1:8090`)

## 4) Контекст из личной БД (Obsidian)
- Найденный полезный meta-контекст:
  - `99 Templates/Шаблон — CONTEXT для проекта.md` (шаблон структуры)
  - `10 System/AI — Правила работы.md` (правила формата и глубины)
- Прямая тематическая заметка по VPN в vault не обнаружена (можно создать при переносе).

## 5) Ограничения
- Не менять/не ломать legacy `3-x-ui/`.
- Не вносить автоматические изменения в Obsidian (только ручной перенос).
- Сохранять совместимость API для будущего Telegram-бота при смене backend-провайдера.

## 6) Критерии результата
- [x] Есть отдельный control plane с API и UI.
- [x] Есть deploy/runbook для VPS.
- [ ] HTTPS для `horizonnetvpn.ru` стабильно отдает корректный LE-сертификат.
- [ ] Реальный WireGuard provider вместо `MockProvider`.
- [ ] API-аутентификация для бота (shared secret/JWT).
- [ ] Интеграция с Telegram-ботом и биллингом.

## 7) Ключевые решения (Decision Log)
- `D-001`: Изоляция нового решения в `amnezia/` вместо изменений в `3-x-ui/`.
- `D-002`: Контракт API проектируется вокруг control plane, backend-провайдер абстрагируется интерфейсом.
- `D-003`: На старте используется `MockProvider` для безопасной валидации API/UI и деплоя.
- `D-004`: Целевой backend для боя: WireGuard stack с API (wg-easy как первый вариант).

## 8) Техническое состояние (снимок)
- API endpoints:
  - `GET /health`
  - `POST /v1/clients`
  - `POST /v1/clients/{client_id}/renew`
  - `POST /v1/clients/{client_id}/revoke`
  - `GET /v1/clients/{client_id}/config`
  - `GET /v1/clients`
  - `GET /v1/stats/traffic` (mock-данные)
- UI:
  - Админ-страница на `GET /`, статика в `app/static/`, графики через Chart.js.
- Тесты:
  - Базовый lifecycle покрыт в `tests/test_api.py`.

## 9) Инцидент / блокер HTTPS
- Симптом:
  - `https://horizonnetvpn.ru` отдает сертификат другого домена (`vpn.getfanto.ru`).
- Вероятная причина:
  - Неверный выбор nginx vhost на `443` (default_server/дубли server block/порядок include).
- Что проверить:
  - Полный конфиг `sites-enabled/horizonnetvpn-control-plane`.
  - `nginx -T` на `listen 443`, `default_server`, `server_name`.
  - Перезагрузка после правок: `nginx -t && systemctl reload nginx`.

## 10) Следующие шаги (приоритет)
- P0: Исправить TLS vhost routing для `horizonnetvpn.ru`/`www`.
- P1: Реализовать `WgEasyProvider` и переключение по env.
- P2: Добавить API auth слой для вызовов от бота.
- P3: Зафиксировать операционный runbook (renew/revoke, инциденты, backup).
- P4: Подключить Telegram-бота и биллинг.

## 11) Объекты для занесения в базу знаний (вручную)
- Проект:
  - `HorizonNetVPN`
- Домен/бренд:
  - `horizonnetvpn.ru`
- Сервер:
  - `109.172.93.80` (prod VPS)
- Компоненты:
  - `Control Plane (FastAPI)`
  - `WireGuard Backend (wg-easy)`
  - `Nginx reverse proxy`
  - `Systemd unit`
- Открытые вопросы:
  - Финальный auth-механизм для bot->API.
  - Стратегия учета реального трафика и биллинга.
  - Политика хранения и ротации клиентских конфигов.

## 12) Готовые шаблоны заметок для Obsidian (копировать вручную)

### 12.1 Project Note
```md
---
type: project
status: active
owner: me
tags: [vpn, telegram-bot, wireguard]
---

# HorizonNetVPN

## Outcome
Автоматическая продажа и управление VPN-доступом через Telegram-бота.

## Current stage
Infrastructure stabilization + provider integration.

## Linked notes
- [[HorizonNetVPN — Tech Context]]
- [[HorizonNetVPN — Decision Log]]
- [[HorizonNetVPN — Operations Runbook]]
```

### 12.2 Decision Note
```md
---
type: decision
status: accepted
project: HorizonNetVPN
---

# D-004 — Use WireGuard API backend

## Decision
Использовать backend с API (wg-easy) и держать control plane как единый контракт для бота.

## Why
Снижает coupling с конкретной VPN-панелью и ускоряет развитие бота/биллинга.

## Consequences
- Нужен adapter `WgEasyProvider`
- Нужны проверки auth и устойчивости API
```

### 12.3 Incident Note
```md
---
type: incident
status: open
severity: high
project: HorizonNetVPN
---

# TLS mismatch on horizonnetvpn.ru

## Symptom
Сертификат на 443 не совпадает с доменом horizonnetvpn.ru.

## Suspected cause
Nginx SSL vhost selection/default_server conflict.

## Next action
Проверить `nginx -T` и выровнять `server_name`/`listen 443`.
```

## 13) Быстрый чек-лист перед ручным переносом в Obsidian
- [ ] Создать 3 заметки: Project / Decision / Incident по шаблонам выше.
- [ ] Связать заметки через wiki-links.
- [ ] Добавить текущий блокер TLS в active tasks.
- [ ] Отразить следующий конкретный шаг: фикс nginx vhost + verify openssl/curl.

