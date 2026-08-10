/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Build the streaming-library WebSocket base URL for a UI served below a proxy
 * path (for example `/vst/`). URL.pathname is used instead of string
 * concatenation so leading and trailing slashes cannot produce an invalid
 * `//vst` path.
 */
export const buildWebSocketEndpoint = (httpEndpoint: string, proxyPathname: string): string => {
    const endpoint = new URL(httpEndpoint);
    endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:';

    const basePath = endpoint.pathname.replace(/^\/+|\/+$/g, '');
    const proxyPath = proxyPathname.replace(/^\/+|\/+$/g, '');
    endpoint.pathname = `/${[basePath, proxyPath].filter(Boolean).join('/')}`;

    return endpoint.toString().replace(/\/$/, '');
};
