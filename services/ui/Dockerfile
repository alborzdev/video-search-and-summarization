ARG USER_ID=65532
ARG GROUP_ID=65532
ARG BUILD_TYPE=prod
ARG RUNTIME_IMAGE_PROD=nvcr.io/nvidia/distroless/node:22-v4.0.7
ARG RUNTIME_IMAGE_DEV=nvcr.io/nvidia/distroless/node:22-v4.0.7-dev


# Builder phase
FROM node:22.22.3 AS builder
ARG USER_ID
ARG GROUP_ID
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org

WORKDIR /repo

# Install dependencies from manifests before copying source. UI edits then
# reuse this expensive layer instead of reinstalling the entire workspace.
COPY services/ui/package.json services/ui/package-lock.json services/ui/
COPY services/ui/apps/nemo-agent-toolkit-ui/package.json services/ui/apps/nemo-agent-toolkit-ui/
COPY services/ui/apps/nv-metropolis-bp-vss-ui/package.json services/ui/apps/nv-metropolis-bp-vss-ui/
COPY services/ui/packages/common/package.json services/ui/packages/common/
COPY services/ui/packages/nemo-agent-toolkit-ui/package.json services/ui/packages/nemo-agent-toolkit-ui/
COPY services/ui/packages/nv-metropolis-bp-vss-ui/alerts/package.json services/ui/packages/nv-metropolis-bp-vss-ui/alerts/
COPY services/ui/packages/nv-metropolis-bp-vss-ui/all/package.json services/ui/packages/nv-metropolis-bp-vss-ui/all/
COPY services/ui/packages/nv-metropolis-bp-vss-ui/dashboard/package.json services/ui/packages/nv-metropolis-bp-vss-ui/dashboard/
COPY services/ui/packages/nv-metropolis-bp-vss-ui/map/package.json services/ui/packages/nv-metropolis-bp-vss-ui/map/
COPY services/ui/packages/nv-metropolis-bp-vss-ui/search/package.json services/ui/packages/nv-metropolis-bp-vss-ui/search/
COPY services/ui/packages/nv-metropolis-bp-vss-ui/video-management/package.json services/ui/packages/nv-metropolis-bp-vss-ui/video-management/

ENV NEXT_TELEMETRY_DISABLED=1
ENV TURBO_TELEMETRY_DISABLED=1
ENV NEXT_BUILD_TRACES=false
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY}

# `npm ci` and the subsequent `turbo` invocation must run from the UI workspace root,
# which is where `package.json` and `package-lock.json` live after the COPY above.
WORKDIR /repo/services/ui

RUN --mount=type=cache,target=/root/.npm \
    npm config set replace-registry-host always \
    && npm ci --no-audit --no-fund

# Copy source only after the lockfile-backed dependency layer is complete.
WORKDIR /repo
COPY services/ui/ services/ui/
WORKDIR /repo/services/ui
# Matches CI: run `bundle` after `build` where defined (e.g. nv-metropolis-bp-vss-ui). The runner
# stage still COPYs standalone, `.next/static`, and `public` explicitly for custom-server.js, so this
# mainly keeps Docker builds aligned with `turbo run build bundle` and validates those tasks. Keep
# workspace tasks serial: the two Next production builds otherwise overlap and can exhaust unified
# memory on an AGX Thor that is simultaneously serving the local LLM and VLM.
RUN ./node_modules/.bin/turbo run build bundle --concurrency=1

# Set permissions for __ENV.js files to be writable at runtime
RUN chmod -R 755 apps/nv-metropolis-bp-vss-ui/public && \
    chmod -R 755 apps/nemo-agent-toolkit-ui/public && \
    chown -R ${USER_ID}:${GROUP_ID} apps/nv-metropolis-bp-vss-ui/public && \
    chown -R ${USER_ID}:${GROUP_ID} apps/nemo-agent-toolkit-ui/public


# Conditional runner phase
FROM ${RUNTIME_IMAGE_PROD} AS runner-prod
ARG BUILD_TYPE

FROM ${RUNTIME_IMAGE_DEV} AS runner-dev
ARG BUILD_TYPE


FROM runner-${BUILD_TYPE} AS runner
ARG USER_ID
ARG GROUP_ID


WORKDIR /repo


# Copy standalone output from each app into its own subdirectory (read-only)
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/apps/nv-metropolis-bp-vss-ui/.next/standalone ./apps/nv-metropolis-bp-vss-ui/
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/apps/nv-metropolis-bp-vss-ui/.next/static ./apps/nv-metropolis-bp-vss-ui/apps/nv-metropolis-bp-vss-ui/.next/static
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=755 /repo/services/ui/apps/nv-metropolis-bp-vss-ui/public ./apps/nv-metropolis-bp-vss-ui/apps/nv-metropolis-bp-vss-ui/public

COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/apps/nemo-agent-toolkit-ui/.next/standalone ./apps/nemo-agent-toolkit-ui/
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/apps/nemo-agent-toolkit-ui/.next/static ./apps/nemo-agent-toolkit-ui/apps/nemo-agent-toolkit-ui/.next/static
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=755 /repo/services/ui/apps/nemo-agent-toolkit-ui/public ./apps/nemo-agent-toolkit-ui/apps/nemo-agent-toolkit-ui/public

# Copy required configuration files with their dependencies for next-runtime-env in custom-server.js (read-only)
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/node_modules/next-runtime-env ./node_modules/next-runtime-env
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/node_modules/chalk ./node_modules/chalk
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/node_modules/ansi-styles ./node_modules/ansi-styles
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/node_modules/supports-color ./node_modules/supports-color
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/node_modules/color-convert ./node_modules/color-convert
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/node_modules/color-name ./node_modules/color-name
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/node_modules/has-flag ./node_modules/has-flag

# Copy custom server (read-only)
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=555 /repo/services/ui/custom-server.js ./custom-server.js

# Copy license files (read-only)
COPY --from=builder --chown=${USER_ID}:${GROUP_ID} --chmod=444 /repo/services/ui/LICENSE* ./
COPY --from=builder --chown=root:root --chmod=0444 /repo/services/ui/NVIDIA-Software-License-Agreement.pdf ./

# Set environment variables
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOST=0.0.0.0


# Create separate stages for prod and dev commands
FROM runner AS runner-prod-cmd
ARG USER_ID
ARG GROUP_ID

# Ensure we run as nonroot user
USER ${USER_ID}:${GROUP_ID}
CMD ["node", "custom-server.js"]


FROM runner AS runner-dev-cmd
ARG USER_ID
ARG GROUP_ID

USER ${USER_ID}:${GROUP_ID}


# Final stage that selects the appropriate command based on BUILD_TYPE
FROM runner-${BUILD_TYPE}-cmd
ARG USER_ID
ARG GROUP_ID

USER ${USER_ID}:${GROUP_ID}
