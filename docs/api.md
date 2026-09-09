# SchoolMessenger Absence API

Discovery date: 2026-09-08

Canadian deployment:

- Web app: `https://go.schoolmessenger.ca/`
- PortalAuth API: `https://portal.schoolmessenger.ca/api/2`
- Attendance API root: `https://go.schoolmessenger.ca/api/1`

Auth uses OAuth password grant:

```text
POST /api/2/oauth/token
Host: portal.schoolmessenger.ca
Authorization: Basic base64("json-client:secret")
Content-Type: application/x-www-form-urlencoded

grant_type=password&username=<username>&password=<password>
```

Attendance requests use:

- `Authorization: Bearer <access_token>`
- `X-Authorization: Bearer <access_token>`
- `X-App-Client: 1`
- `X-Requested-With: XMLHttpRequest`

Read settings:

```text
GET https://go.schoolmessenger.ca/api/1/attendance
```

Read absence range:

```text
GET https://go.schoolmessenger.ca/api/1/attendance/absences/{from}/{to}
GET https://go.schoolmessenger.ca/api/1/attendance/absences/{from}/{to}?filter=canBeExplained
```

Create absence:

```text
POST https://go.schoolmessenger.ca/api/1/attendance/absences
```

Read or cancel one absence:

```text
GET https://go.schoolmessenger.ca/api/1/attendance/{customerId}/absences/{absenceId}
DELETE https://go.schoolmessenger.ca/api/1/attendance/{customerId}/absences/{absenceId}
```

Payload:

```json
{
  "student": {
    "customerId": 0,
    "personId": 0,
    "organizationId": 0
  },
  "source": "user",
  "client": "web",
  "absenceType": "fullDay",
  "reasonCode": "I",
  "absenceDates": [
    {
      "date": "YYYY-MM-DD",
      "inTime": null,
      "outTime": null
    }
  ]
}
```

Observed absence types:

- `fullDay`
- `late`
- `earlyDeparture`
- `partialDay`
- `multiDay`

Reason codes are organization/type-specific and should be read from `organizationSettings` at
runtime.
