#!/bin/sh
# Import + activate must both happen before `n8n start` — running them
# concurrently with a live server hits sqlite lock errors (confirmed by
# hand while building this). Re-importing the same workflow id is safe:
# it's an upsert, not an insert, so a redeploy or a restart on an
# instance that kept its disk just re-applies the same known-good state.
set -e

n8n import:workflow --input=/workflows/campaign-moderation.json
n8n import:workflow --input=/workflows/voice-booking.json

n8n update:workflow --id=omnirag-campaign-moderation --active=true
n8n update:workflow --id=omnirag-voice-booking --active=true

exec n8n start
