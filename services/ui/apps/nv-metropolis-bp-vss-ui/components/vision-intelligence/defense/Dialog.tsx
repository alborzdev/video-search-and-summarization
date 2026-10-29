// SPDX-License-Identifier: MIT
import React, { useEffect, useRef } from 'react';
import { IconX } from '@tabler/icons-react';
import styles from './Defense.module.css';
export function DefenseDialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; if (dialog && !dialog.open) dialog.showModal(); return () => { dialog?.close(); }; }, []);
  return <dialog ref={ref} className={styles.dialog} aria-label={title} onCancel={onClose}>
    <header><h2>{title}</h2><button aria-label="Close dialog" onClick={onClose}><IconX size={20} /></button></header>
    {children}
  </dialog>;
}
