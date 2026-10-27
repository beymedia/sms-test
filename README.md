# SMS servisi (test)

Flask əsaslı kiçik SMS servisi: tək və kütləvi göndəriş, hər nömrəyə və ümumi gündəlik limit, STOP ilə abunəlikdən çıxma, arxa planda növbə.

## Lokal işə salma

```bash
pip install -r requirements.txt
export API_KEY=dəyişdir SMS_PROVIDER=log
python -m unittest discover -s tests -v   # testlər
gunicorn -w 1 -b 127.0.0.1:8000 app:app
```

`SMS_PROVIDER=log` test rejimidir: heç bir mesaj göndərilmir, yalnız bazaya "simulated" kimi yazılır.

## Mühit dəyişənləri

| Ad | Təsvir | Standart |
|---|---|---|
| `API_KEY` | Bütün endpoint-lər üçün `X-API-Key` başlığı | (məcburi) |
| `SMS_PROVIDER` | `log` (test) və ya `twilio` | `log` |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | Twilio məlumatları (`twilio` rejimi) | — |
| `INBOUND_TOKEN` | Twilio gələn mesaj webhook-u üçün gizli yol hissəsi | — |
| `PER_NUMBER_DAILY_LIMIT` | Hər nömrəyə gündə maksimum mesaj | `3` |
| `GLOBAL_DAILY_LIMIT` | Bütün servis üzrə gündəlik maksimum | `100` |
| `MAX_BULK` | Bir kütləvi sorğuda maksimum alıcı | `500` |
| `SEND_RATE_PER_SEC` | Saniyədə göndəriş sayı | `1` |
| `DB_PATH` | SQLite faylının yolu | `sms.db` |

Limitlər UTC gününə görə sıfırlanır. Uğursuz (`failed`) və bloklanmış mesajlar limitə sayılmır.

## Endpoint-lər

Bütün sorğularda `X-API-Key` başlığı lazımdır (`/health` və Twilio webhook istisna).

- `GET /health`
- `POST /sms/send` — `{"to": "+994501234567", "body": "Salam"}`
- `POST /sms/bulk` — `{"recipients": ["+994...", "+994..."], "body": "Salam"}`
- `GET /sms/<id>` — mesajın statusu
- `GET /limits?to=+994501234567` — istifadə olunmuş və qalan limit
- `POST /sms/inbound/<INBOUND_TOKEN>` — Twilio-da "Incoming message" webhook-u olaraq qeyd edin. `STOP`, `DUR` və ya `UNSUBSCRIBE` cavabı nömrəni abunəlikdən çıxarır.

Nümunə:

```bash
curl -X POST https://SİZİN-SERVİS.onrender.com/sms/send \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"to": "+994501234567", "body": "Test mesajı"}'
```

## Render-ə yerləşdirmə

1. GitHub-dakı repozitoriyanı Render-də "New Web Service" kimi qoşun (və ya `render.yaml`-dan Blueprint).
2. Render panelində `API_KEY`, `INBOUND_TOKEN` və Twilio dəyişənlərini əlavə edin.
3. Test üçün `SMS_PROVIDER=log` saxlayın. Real göndərişə keçəndə `twilio` edin.

**Vacib qeydlər:**
- Servis **tək worker** ilə işləməlidir (`-w 1`), çünki göndəriş növbəsi həmin prosesin içindədir.
- Render-in pulsuz planında disk saxlanmır: yenidən başladıqda `sms.db` silinir. Limit və növbə məlumatını qorumaq üçün ödənişli plan və persistent disk (`/var/data`) lazımdır, sonra `DB_PATH=/var/data/sms.db` təyin edin.
- Twilio webhook-u real təhlükəsizlik üçün `INBOUND_TOKEN` ilə qorunur; əlavə olaraq Twilio imza yoxlaması əlavə etmək tövsiyə olunur.
- Alıcılardan razılıq olmadan kütləvi göndəriş provayder qaydalarına və qanunvericiliyə zidd ola bilər.
