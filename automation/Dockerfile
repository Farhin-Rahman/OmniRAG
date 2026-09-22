# Deploys n8n as a standalone, self-configuring service (Render, Fly.io,
# Railway, any Docker host) — no persistent disk required.
#
# Render's free tier (like every free-tier host used elsewhere in this
# project) has no persistent disk: a redeploy starts from a clean
# filesystem. Rather than fight that, this embraces it the same way
# backend/entrypoint.sh does for the API — every container start imports
# the two tracked workflow JSON files fresh and activates them, so the
# service always comes up fully configured with zero manual setup,
# regardless of how many times it gets redeployed.
#
# Secrets (SLACK_WEBHOOK_URL) and the backend's public URL
# (OMNIRAG_BACKEND_URL) are never baked into the image or the workflow
# files — the workflows read them via {{ $env.VAR }} expressions at
# execution time, set as real environment variables on the host.
FROM docker.n8n.io/n8nio/n8n:latest

USER root
COPY entrypoint.sh /entrypoint.sh
COPY n8n-campaign-moderation-workflow.json /workflows/campaign-moderation.json
COPY n8n-voice-booking-workflow.json /workflows/voice-booking.json
RUN chmod +x /entrypoint.sh

USER node

# Node Code nodes read $env.SLACK_WEBHOOK_URL / $env.OMNIRAG_BACKEND_URL —
# blocked by default. Not a secret itself, safe to bake in.
ENV N8N_BLOCK_ENV_ACCESS_IN_NODE=false

ENTRYPOINT ["/entrypoint.sh"]
