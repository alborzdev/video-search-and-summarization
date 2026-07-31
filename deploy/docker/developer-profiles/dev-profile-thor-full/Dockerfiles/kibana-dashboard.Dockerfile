# syntax=docker/dockerfile:1
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

FROM alpine:3.23.4

WORKDIR /opt/mdx

RUN apk add --no-cache bash curl

COPY developer-profiles/dev-profile-search/kibana-dashboard/search-kibana-objects.ndjson ./search-kibana-objects.ndjson
COPY developer-profiles/dev-profile-alerts/kibana-dashboard/its-kibana-objects.ndjson ./its-kibana-objects.ndjson
COPY industry-profiles/warehouse-operations/warehouse-2d-app/kibana-dashboard/warehouse-2d-kibana-objects.ndjson ./warehouse-2d-kibana-objects.ndjson
COPY developer-profiles/dev-profile-thor-full/kibana-dashboard/thor-vss-overview.ndjson ./thor-vss-overview.ndjson
COPY developer-profiles/dev-profile-thor-full/kibana-dashboard/init-scripts/kibana-import-dashboards.sh ./init-scripts/kibana-import-dashboards.sh

RUN chmod 0555 ./init-scripts/kibana-import-dashboards.sh
