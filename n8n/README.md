# n8n trigger layer (PRD FR-12, beyond the brief)

Demonstrates the production trigger layer from PRD §14.5: n8n decides **when**, the hunter service decides **what** - the exact same rule logic as the CLI's `hunter event connection-accepted` and `hunter simulate --days N`, just driven by a webhook and a schedule instead of a terminal command. The CLI remains the primary way to run the demo; this is the "beyond the brief" piece showing how it maps onto the stack named in the job description.

`hunter_triggers.json` has two independent flows:

- **Webhook: connection accepted** → **POST /events** - a connection-accepted event from LinkedIn (in production) hits the webhook, which calls `hunter serve`'s `/events` endpoint with `{"type": "connection_accepted", "lead_id": ...}`.
- **Schedule: daily tick** → **POST /tick** - a daily schedule calls `/tick` with `{"days": 7}`, which fires R3's cold-email rule for anyone still `INVITED` past the threshold.

## Run it locally

1. **Start the hunter API** (from the repo root, with the usual `hunter run` already done at least once so there's something to trigger):
   ```bash
   python -m hunter serve --port 8000
   ```
2. **Start n8n** (separate terminal, no install needed - downloads and runs via npx on first use):
   ```bash
   npx n8n
   ```
   n8n opens at `http://localhost:5678`. Create an owner account on first launch (local only, not sent anywhere).
3. **Import the workflow**: in the n8n UI, **Workflows → Add workflow → ⋯ menu → Import from File**, choose `n8n/hunter_triggers.json`.
4. **Try the webhook path**: click the "Webhook: connection accepted" node → **Listen for test event**, then in another terminal:
   ```bash
   curl -X POST http://localhost:5678/webhook-test/connection-accepted \
     -H "Content-Type: application/json" -d '{"lead_id": "p01"}'
   ```
   n8n calls `hunter serve`'s `/events` for you; the response (lead status, drafted message id) appears in both the `curl` output and the n8n execution log.
5. **Try the schedule path**: open the "POST /tick" node and click **Execute step** (or activate the workflow and wait for the schedule) to confirm it calls `/tick` and gets back `{"cold_drafted": [...]}`.

## Notes

- The webhook body shape (`{{$json.body.lead_id}}` in the "POST /events" node) matches n8n's default webhook output, which nests the incoming JSON under `.body`. If a different n8n version flattens it, adjust that one expression to `{{$json.lead_id}}`.
- Both HTTP Request nodes point at `http://localhost:8000` - change the host if `hunter serve` runs elsewhere.
- The workflow is exported **inactive** (`"active": false`) - activate it in the UI after import if you want the schedule to actually fire on its own.
