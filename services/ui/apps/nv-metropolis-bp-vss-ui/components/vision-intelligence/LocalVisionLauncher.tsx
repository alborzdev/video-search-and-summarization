// SPDX-License-Identifier: MIT
import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { IconScan } from '@tabler/icons-react';
const LocalVisionInspector = dynamic(() => import('./LocalVisionInspector').then(module => module.LocalVisionInspector), { ssr: false });
export function LocalVisionLauncher({ className, captureSelector }: { className?: string; captureSelector?: string }) {
  const [open, setOpen] = useState(false);
  return <><button type="button" className={className} onClick={() => setOpen(true)}><IconScan size={17} /><span>Local vision</span></button>{open && <LocalVisionInspector captureSelector={captureSelector} onClose={() => setOpen(false)} />}</>;
}
