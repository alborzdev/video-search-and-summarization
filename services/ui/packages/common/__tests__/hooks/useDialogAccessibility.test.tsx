import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { useDialogAccessibility } from '../../lib-src/hooks/useDialogAccessibility';

function Dialog({ label, onClose }: { label: string; onClose: () => void }) {
  const dialogRef = useDialogAccessibility({ isOpen: true, onClose });
  return (
    <div ref={dialogRef} role="dialog" aria-label={label}>
      <button type="button" onClick={onClose}>Close {label}</button>
      <button type="button">Last {label}</button>
    </div>
  );
}

function DialogHarness() {
  const [open, setOpen] = useState(false);
  const [nestedOpen, setNestedOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open dialog</button>
      {open && (
        <Dialog
          label="Parent dialog"
          onClose={() => setOpen(false)}
        />
      )}
      {open && <button type="button" onClick={() => setNestedOpen(true)}>Open nested dialog</button>}
      {nestedOpen && <Dialog label="Nested dialog" onClose={() => setNestedOpen(false)} />}
    </>
  );
}

describe('useDialogAccessibility', () => {
  it('focuses the first control, traps Tab, and restores the opener', () => {
    render(<DialogHarness />);
    const opener = screen.getByRole('button', { name: 'Open dialog' });
    opener.focus();
    fireEvent.click(opener);

    const close = screen.getByRole('button', { name: 'Close Parent dialog' });
    const last = screen.getByRole('button', { name: 'Last Parent dialog' });
    expect(close).toHaveFocus();

    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('lets only the topmost dialog handle Escape and restores focus to its opener', () => {
    render(<DialogHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Open dialog' }));
    const nestedOpener = screen.getByRole('button', { name: 'Open nested dialog' });
    nestedOpener.focus();
    fireEvent.click(nestedOpener);

    expect(screen.getByRole('button', { name: 'Close Nested dialog' })).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Nested dialog' })).not.toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Parent dialog' })).toBeInTheDocument();
    expect(nestedOpener).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
