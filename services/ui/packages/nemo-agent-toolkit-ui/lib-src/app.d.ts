import type { ComponentType } from 'react';
import type { AppProps } from 'next/app';

import type { NemoAgentToolkitAppProps } from './index';

export type { NemoAgentToolkitAppProps } from './index';

export const App: ComponentType<AppProps>;
export const NemoAgentToolkitApp: ComponentType<NemoAgentToolkitAppProps>;
export const EmbeddedNemoApp: ComponentType<NemoAgentToolkitAppProps>;
export const NemoAppWithProviders: ComponentType<AppProps>;
