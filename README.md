# SchoolMessenger MCP

Absence-only MCP server for SchoolMessenger SafeArrival.

This server is intentionally narrow. It can list attendance-enabled students, list absence
types/reasons, list existing absences, draft an absence, submit a previously drafted absence,
draft an absence cancellation, and cancel a previously drafted cancellation only when the caller
provides the exact confirmation phrase returned by the draft tool.

## Configuration

Use environment variables:

```bash
export SCHOOLMESSENGER_REGION=ca
export SCHOOLMESSENGER_USERNAME='parent@example.com'
export SCHOOLMESSENGER_PASSWORD='...'
schoolmessenger-mcp
```

Or use the existing local credentials file:

```bash
export SCHOOLMESSENGER_REGION=ca
export SCHOOLMESSENGER_CREDS_FILE=~/.config/schoolmessenger.ca/creds.yml
export SCHOOLMESSENGER_ACCOUNT=default
schoolmessenger-mcp
```

Credential YAML shape:

```yaml
default:
  username: parent@example.com
  password: password
```

Do not commit credentials.

## Tools

- `list_students`
- `list_absence_options`
- `list_absences`
- `draft_absence`
- `submit_absence`
- `draft_cancel_absence`
- `cancel_absence`

## Safety

`draft_absence` performs local validation and returns a human-readable confirmation phrase.
`submit_absence` refuses to call SchoolMessenger unless the phrase exactly matches a draft stored
in the current MCP process.

`draft_cancel_absence` looks up an existing absence, returns a human-readable cancellation summary,
and provides a `CANCEL ABSENCE <draft_id>` confirmation phrase. `cancel_absence` refuses to call
SchoolMessenger unless that phrase exactly matches a cancellation draft stored in the current MCP
process.

The server never logs OAuth tokens or passwords.

## Codex Desktop Example

```json
{
  "mcpServers": {
    "schoolmessenger": {
      "command": "python3",
      "args": ["-m", "schoolmessenger_mcp.server"],
      "env": {
        "SCHOOLMESSENGER_REGION": "ca",
        "SCHOOLMESSENGER_CREDS_FILE": "~/.config/schoolmessenger.ca/creds.yml",
        "SCHOOLMESSENGER_ACCOUNT": "default"
      }
    }
  }
}
```

## API Notes

Discovery notes are in `docs/api.md`.
