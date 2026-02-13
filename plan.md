# SEND_BOT to'liq ish rejasi (boshlanishdan productiongacha)

Bu hujjat loyiha bo'yicha hech narsa qolib ketmasdan, boshidan oxirigacha bajariladigan amaliy plan.

## 0. Maqsad va SLA

- Maqsad: foydalanuvchi o'z Telegram akkaunti orqali tanlangan guruhlarga interval asosida avtomatik xabar yuborishi.
- Asosiy talablar:
  - Barqaror login (code + 2FA).
  - Guruh import va dedupe.
  - Auto-broadcast scheduler + queue + worker.
  - Flood-safe retry.
  - Fairness: bir user butun workerni band qilib qo'ymasligi.
  - Operatsion kuzatuv (log, status, alert).

## 1. Muhit tayyorlash (local/dev)

1. Node/NPM versiyasini tekshirish.
2. `npm install`.
3. `.env` yaratish va to'ldirish:
   - `TG_BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH`
   - `DATABASE_URL`
   - Redis parametrlari (`REDIS_URL` yoki `REDIS_HOST/PORT`)
   - Broadcast tuning parametrlari.
4. DB tayyorlash:
   - `npx prisma generate`
   - `npx prisma db push`
5. Lokal run:
   - app role: `BOT_ROLE=app`
   - worker role: `BOT_ROLE=worker`

## 2. Arxitektura qatlamlari

- App role (`bot`):
  - Telegraf UI
  - Access control
  - Scheduler
- Worker role (`worker`):
  - BullMQ processor
  - Micro-batch send
  - Retry/continuation
- Shared:
  - PostgreSQL (Prisma)
  - Redis (queue + distributed lock)

## 3. Ma'lumotlar modeli (Prisma) tekshiruv ro'yxati

- `User`
- `TelegramAccount`
- `UserGroup`
- `BroadcastConfig`
- `BroadcastAttempt`
- `AllowedUser`
- `SentMessage`
- `Session` (legacy)

Checklist:

- [ ] Unique/indexlar mavjudligini tekshirish.
- [ ] `BroadcastAttempt` idempotency (`idempotencyKey`) ishlashini tekshirish.
- [ ] `BroadcastConfig.userId` unique ekanligini tasdiqlash.

## 3.1 DB (PostgreSQL) qanday ishlaydi - amaliy tushuntirish

Asosiy tamoyil:

- PostgreSQL - "source of truth" (hamma holat shu yerda).
- Redis - vaqtinchalik queue/lock transport (doimiy ma'lumot emas).
- Worker qayta ishga tushsa ham broadcast holati DB dan davom etadi (`BroadcastAttempt`).

### Jadval vazifalari (kim nima uchun ishlatiladi)

- `User`
  - Bot foydalanuvchisi asosiy identifikatori.
  - `id` Telegram user id (string).

- `AllowedUser`
  - Ruxsat boshqaruvi.
  - `expiresAt` orqali aktiv/pending/tugagan holat.

- `TelegramAccount`
  - Userning ulangan Telegram akkaunt(lar)i.
  - `sessionString` shu yerda saqlanadi.
  - `isFloodWait`, `floodWaitUntil` bilan account health boshqariladi.

- `UserGroup`
  - User tanlagan target guruhlar.
  - Composite PK: `(userId, id)`.

- `BroadcastConfig`
  - Auto-broadcast sozlamasi: `message`, `interval`, `isActive`, `lastRunAt`.
  - Har user uchun bitta (`userId` unique).

- `BroadcastAttempt`
  - Har campaigndagi har guruh uchun alohida attempt yozuvi.
  - Durable state machine: `pending -> in-flight -> sent/failed-terminal`.
  - Retry va error sabablari shu yerda saqlanadi.

- `SentMessage`
  - UI tarixi uchun yuborilgan matnlar logi.

- `Session` (legacy)
  - Eski sessiya izlari; amalda asosiy oqim `TelegramAccount` bilan.

### Muhim constraint/indexlar nega kerak

- `BroadcastConfig.userId @unique`
  - Bir userda bir dona aktiv config bo'lishini ta'minlaydi.

- `BroadcastAttempt.idempotencyKey @unique`
  - Bir campaign + target uchun duplicate yozuv kirib ketmasligini to'xtatadi.

- `@@unique([campaignId, targetGroupId])`
  - Qo'shimcha dedupe himoya qavati.

- `@@index([userId, campaignId, status])`
  - Worker status kesimida tez query qilish uchun.

## 3.2 DB o'qish/yozish oqimlari (real lifecycle)

### A) Login paytida

1. `startLogin` -> tashqi Telegramdan code yuboriladi.
2. `completeLogin/complete2FA` muvaffaqiyatli bo'lsa:
   - `TelegramAccount` ga `sessionString` va profil yoziladi (upsert/create logic).
3. Keyin barcha send amallar active account(lar) orqali ishlaydi.

### B) Scheduler paytida

1. `BroadcastConfig` dan due userlar olinadi.
2. Har due config uchun queuega job ketadi.
3. Queuega tushgan configlar uchun `lastRunAt` update qilinadi.

### C) Worker paytida

1. Worker `BroadcastAttempt` seed qiladi (agar campaign boshlanayotgan bo'lsa).
2. Pending attempt claim qilinadi (`in-flight`).
3. Send success bo'lsa `sent`.
4. Retriable xato bo'lsa `pending + nextAttemptAt`.
5. Terminal xato bo'lsa `failed-terminal`.
6. Campaign tugaguncha continuation joblar orqali davom etadi.

## 3.3 DB barqarorlik, tranzaksiya va race holatlar

- Race holatlar:
  - Access auto-registerda `P2002` unique race ushlangan.
  - Attempt claim `updateMany(where: id + status='pending')` bilan optimistic lock uslubi.

- Tranzaksiya ishlatiladigan joylar:
  - Admin panel statistikalarida bir nechta count query birga olinadi.
  - Zarur joylarda atomiklikni saqlash uchun transaction qo'llanadi.

- Idempotent yozishlar:
  - `upsert` (`UserGroup`, `BroadcastConfig`) ko'p urinishda ham xavfsiz.
  - Unique constraintlar duplicate insertni kesadi.

## 3.4 DB maintenance va retention plan

- `BroadcastAttempt` jadvali tez o'sadi; retention siyosat kerak:
  - Masalan: 14-30 kundan eski `sent/failed-terminal` yozuvlarini tozalash cron.
- `SentMessage` tarixini ham periodik arxiv/tozalash mumkin.
- `vacuum/analyze` jadval yukiga qarab monitoring qilinadi.

Checklist:

- [ ] `BroadcastAttempt` retention cron reja tasdiqlangan.
- [ ] Katta loadda index scan/seq scan tekshirilgan (`EXPLAIN ANALYZE`).

## 3.5 DB kuzatuv uchun tayyor SQL'lar

Campaign holati:

```sql
SELECT status, count(*)
FROM "BroadcastAttempt"
WHERE "createdAt" > now() - interval '30 minutes'
GROUP BY status
ORDER BY status;
```

Queue lagga yaqin signal (eski pendinglar):

```sql
SELECT count(*) AS pending_over_10m
FROM "BroadcastAttempt"
WHERE status = 'pending'
  AND "createdAt" < now() - interval '10 minutes';
```

Flood bo'layotgan accountlar:

```sql
SELECT id, "userId", "isFloodWait", "floodWaitUntil"
FROM "TelegramAccount"
WHERE "isFloodWait" = true
ORDER BY "floodWaitUntil" DESC;
```

## 4. Login va sessiya oqimi

1. User `login` ni bosadi.
2. Phone yuboradi (text/contact).
3. `startLogin` code yuboradi.
4. `completeLogin` bilan kod tasdiqlanadi.
5. Kerak bo'lsa `complete2FA` ishlaydi.
6. Session `TelegramAccount.sessionString` ga saqlanadi.

Checklist:

- [ ] Timeout/flood xatolari foydalanuvchiga tushunarli ko'rsatiladi.
- [ ] Noto'g'ri kod/parol holatlari qayta urinishga yaroqli.
- [ ] `isActive`, `isFloodWait`, `floodWaitUntil` to'g'ri boshqariladi.

## 5. Access va admin boshqaruv

- Middleware:
  - Super admin username orqali bypass.
  - `AllowedUser` orqali ruxsat.
  - Muddati tugagan user bloklanadi.
  - Yangi user pending holatda auto-yaratiladi.

Admin funksiyalar:

- `/adduser <id> <days>`
- `/ban <id>`
- `/info`, `/id`
- Inline admin panel (all/confirmed/requested)
- Expiry +30/-30 kun
- Barchaga announcement

Checklist:

- [ ] `P2002` race holati ushlangan.
- [ ] Admin panel pagination to'g'ri ishlaydi.

## 6. Guruhlar bilan ishlash

1. Remote guruhlarni `getRemoteGroups` orqali olish.
2. Dedupe (id va normalized title bo'yicha).
3. `UserGroup` ga upsert/delete.
4. UI pagination va toggle.

GetDialogs bosimini kamaytirish:

- `REMOTE_GROUPS_CACHE_TTL_MS`
- `REMOTE_GROUPS_MIN_REFRESH_MS`
- `REMOTE_GROUPS_FAILURE_COOLDOWN_MS`
- in-flight single-flight map

Checklist:

- [ ] Bir user uchun parallel chaqiriqlar 1 ta fetchga collapse bo'ladi.
- [ ] Xato bo'lsa cached natija fallback bo'ladi.

## 7. Broadcast konfiguratsiya oqimi

1. User xabar matnini kiritadi.
2. Interval tanlaydi (preset/custom).
3. `BroadcastConfig` upsert qilinadi.
4. Auto-broadcast yoqiladi/o'chiriladi.
5. `SentMessage` tarixga yoziladi.

Checklist:

- [ ] Message bo'sh bo'lsa start qilinmaydi.
- [ ] Interval min check ishlaydi.

## 8. Scheduler bosqichi

- Har `SCHEDULER_CHECK_INTERVAL_MS` da due configlar tekshiriladi.
- `addBulk` bilan queuega yuboriladi.
- `lastRunAt` muvaffaqiyatli queued configlar uchun yangilanadi.
- Redis lock bilan singleton ishlash.
- Deterministic jitter (`SCHEDULER_JITTER_MAX_MS`) qo'llanadi.

Checklist:

- [ ] `MAX_DUE_PER_TICK` limit to'g'ri.
- [ ] Lock acquire/release xatolari loglanadi.

## 9. Worker/processor bosqichi

- Job kelganda user lock olinadi (`broadcast:user-lock:<userId>`).
- `broadcastMessage(...)` micro-batch budget bilan ishga tushadi.
- Agar pending qolsa continuation job schedule bo'ladi.
- Job oxirida lock release.

Parametrlar:

- `BROADCAST_CONCURRENCY`
- `BROADCAST_ATTEMPTS_PER_JOB`
- `BROADCAST_CONTINUATION_BASE_DELAY_MS`
- `BROADCAST_CONTINUATION_JITTER_MS`
- `BROADCAST_USER_LOCK_TTL_MS`

Checklist:

- [ ] Bir user parallel joblarda bir vaqtda ishlanmaydi.
- [ ] Deferred holatda continuation chiqadi.

## 10. Attempt lifecycle va retry siyosati

Statuslar:

- `pending`
- `in-flight`
- `sent`
- `failed-terminal`

Qoidalar:

- Re-triable xato: pendingga qaytadi, `nextAttemptAt` qo'yiladi.
- Terminal xato: `failed-terminal`.
- Retry limitdan oshsa `retry-exhausted`.
- Stuck `in-flight` lar recover qilinadi.

Checklist:

- [ ] `classifyTelegramError` to'g'ri.
- [ ] `computeRetryDelayMs` (exponential + retry_after + jitter) to'g'ri.
- [ ] `idempotencyKey` bilan duplicate yo'q.

## 11. Throughput, fairness, flood-safety tuning

Boshlang'ich xavfsiz profil:

- `BROADCAST_PER_ACCOUNT_CONCURRENCY=1`
- `TELEGRAM_PER_ACCOUNT_MPM=6`
- `TELEGRAM_PER_ACCOUNT_MIN_DELAY_MS=10000` (yoki ehtiyotkor qiymat)
- `BROADCAST_ATTEMPTS_PER_JOB=2`
- `SCHEDULER_JITTER_MAX_MS=15000+`

Bosqichma-bosqich oshirish:

1. `BROADCAST_CONCURRENCY` ni 8 -> 12 -> 16 -> 24.
2. Worker replica qo'shish (1 -> 2 -> 3).
3. Har bosqichda flood, queue lag, CPU/RAM, DB/Redis kechikishlarini kuzatish.

Checklist:

- [ ] Flood ko'payganda MPM pasaytiriladi.
- [ ] Queue lag oshganda jitter va concurrency qayta balanslanadi.

## 12. Monitoring va alert

Kuzatiladigan eventlar:

- `enqueue`, `dequeue`, `sent`
- `retry_scheduled`, `retry_exhausted`, `terminal_failure`
- `batch_processed`, `metrics_snapshot`
- `recovered_stuck_in_flight`

Alert thresholdlar:

- `BROADCAST_RETRY_STORM_THRESHOLD`
- `BROADCAST_STUCK_INFLIGHT_THRESHOLD`
- `BROADCAST_QUEUE_LAG_ALERT_MS`

Checklist:

- [ ] Worker loglar markazlashtirilgan.
- [ ] Tezkor tahlil uchun SQL status query tayyor.

## 13. Test strategiyasi

Automated:

- `broadcast-orchestrator.util.spec.ts`
- `broadcast.integration.spec.ts`
- `userbot.service.spec.ts`

Qo'lda test:

1. Login success/fail/2FA.
2. Group import + dedupe.
3. 1 user, 10 group, 5 min.
4. 10 user burst.
5. Flood simulyatsiya (retry ishlashi).
6. Worker restartdan keyin davom ettirish.

Checklist:

- [ ] `npm test` o'tadi.
- [ ] `npm run build` o'tadi.

## 14. Deployment (Docker Compose)

1. `.env` serverga qo'yish.
2. `docker compose up -d --build bot worker`.
3. `docker compose ps`.
4. `docker compose logs -f worker`.
5. DB va queue health tekshirish.

Checklist:

- [ ] `BOT_ROLE` to'g'ri ajratilgan.
- [ ] Redis/DB ulanishlari ishlaydi.
- [ ] Container restart policy yoqilgan.

## 15. Ops runbook (kundalik ishlatish)

- Scale up/down:
  - `docker compose up -d --scale worker=2`
- Tezkor status:
  - queue lag, pending/in-flight soni
- Incident paytida:
  1. Flood ko'p bo'lsa MPM kamaytirish.
  2. CPU yuqori bo'lsa concurrency pasaytirish.
  3. DB lock yoki latency bo'lsa scheduler tickni sekinlashtirish.

## 16. Capacity planning formulasi

- Kerakli xabar/min = `(active_users_per_cycle * avg_groups) / interval_minutes`
- Beriladigan xabar/min (taxmin) = `effective_concurrency * per_account_mpm`
- Agar kerakli > beriladigan bo'lsa, queue lag yig'iladi.

Qarorlar:

- Exact 5 min target uchun:
  - due userlarni jitter bilan yoyish,
  - worker slotlarini ko'paytirish,
  - micro-batch davomiyligini optimallashtirish,
  - flood xavfini nazorat qilish.

## 17. Security va hygiene

- `.env` dagi token va API keylarni publicga chiqarmaslik.
- Admin username ro'yxatini xavfsiz boshqarish.
- Keraksiz debug loglarni productionda kamaytirish.
- Destructive DB amallarni cheklash.

## 18. Yakuniy acceptance checklist

- [ ] User login flow to'liq ishlaydi.
- [ ] Group import barqaror va dedupe to'g'ri.
- [ ] Broadcast config saqlanadi va scheduler queuega chiqaradi.
- [ ] Worker micro-batch + continuation ishlaydi.
- [ ] Retry/flood handling to'g'ri.
- [ ] Admin panel va access nazorati ishlaydi.
- [ ] Monitoring eventlar chiqadi.
- [ ] Testlar va build muvaffaqiyatli.
- [ ] Docker deployment barqaror.
- [ ] Capacity bo'yicha real yukda sinov yakunlangan.

---

Bu plan bo'yicha har bir bo'lim alohida issue/task qilib yuritilsa, loyiha boshidan oxirigacha nazorat ostida va yo'qotishsiz bajariladi.
