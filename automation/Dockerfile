# Deploys n8n as a standalone, self-configuring service (Render, Fly.io,
# Railway, any Docker host) — no persistent disk required.
#
# Render's free tier (like every free-tier host used elsewhere in this
# project) has no persistent disk: a redeploy starts from a clean
# filesystem. The two tracked workflow JSON files are imported and
# activated at BUILD time (baked into the image), not at container
# start — measured by hand: each separate `n8n <command>` invocation
# pays a real, fixed cost (re-checking every migration, ~25-30s even
# when none are pending), and doing that across import + activate + start
# at every container boot pushed a real deploy past Render's port-scan
# timeout in production. Doing it once here, during the build, means the
# runtime entrypoint is just `n8n start` with nothing left to prepare.
# (No VOLUME is declared on /home/node/.n8n in the base image, so a
# build-time RUN step genuinely persists into the final image layer.)
#
# Secrets (SLACK_WEBHOOK_URL) and the backend's public URL
# (OMNIRAG_BACKEND_URL, OMNIRAG_WEBHOOK_SECRET) are never baked in here —
# the workflows only store the literal expression string
# ({{ $env.VAR }}), resolved at execution time from real environment
# variables set on the host, not at import time.
#
# Docker Hub, not docker.n8n.io (n8n's own registry, used by the local
# docker-compose setup) — Render's build servers hit a 429 rate limit
# pulling from docker.n8n.io. Same image, different registry.
FROM n8nio/n8n:latest

USER root
COPY n8n-campaign-moderation-workflow.json /workflows/campaign-moderation.json
COPY n8n-voice-booking-workflow.json /workflows/voice-booking.json
RUN chown -R node:node /workflows

USER node

# Node Code nodes read $env.SLACK_WEBHOOK_URL / $env.OMNIRAG_BACKEND_URL /
# $env.OMNIRAG_WEBHOOK_SECRET — blocked by default. Not a secret itself,
# safe to bake in.
ENV N8N_BLOCK_ENV_ACCESS_IN_NODE=false

# --all is no longer supported for activation (confirmed by hand: it
# silently leaves every workflow inactive) — publish each by id instead.
RUN n8n import:workflow --separate --input=/workflows && \
    n8n publish:workflow --id=omnirag-campaign-moderation && \
    n8n publish:workflow --id=omnirag-voice-booking

ENTRYPOINT ["n8n", "start"]
