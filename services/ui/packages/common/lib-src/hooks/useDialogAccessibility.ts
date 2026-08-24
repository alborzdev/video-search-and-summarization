import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]', 'area[href]', 'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])', 'select:not([disabled])',
  'textarea:not([disabled])', 'iframe', '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

type DialogRegistration = {
  getDialog: () => HTMLElement | null;
  getOptions: () => UseDialogAccessibilityOptions;
};

const openDialogs: DialogRegistration[] = [];
let isListening = false;

function isFocusable(element: HTMLElement): boolean {
  return !element.closest('[aria-hidden="true"], [inert]');
}

function focusableElements(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(isFocusable);
}

function focusInitialElement(dialog: HTMLElement, options: UseDialogAccessibilityOptions) {
  const initialFocus = options.initialFocusRef?.current;
  const target = initialFocus && isFocusable(initialFocus) ? initialFocus : focusableElements(dialog)[0];
  if (target) {
    target.focus();
    return;
  }
  // A dialog with no interactive descendants still needs a keyboard focus target.
  if (!dialog.hasAttribute('tabindex')) dialog.tabIndex = -1;
  dialog.focus();
}

function handleDocumentKeyDown(event: KeyboardEvent) {
  const registration = openDialogs.at(-1);
  const dialog = registration?.getDialog();
  if (!registration || !dialog) return;

  const { dismissible = true, onClose } = registration.getOptions();
  if (event.key === 'Escape') {
    // Always consume Escape for the topmost modal. A non-dismissible progress
    // dialog must not leak Escape to the dialog underneath it.
    event.preventDefault();
    event.stopPropagation();
    if (dismissible) onClose?.();
    return;
  }
  if (event.key !== 'Tab') return;

  const focusable = focusableElements(dialog);
  if (focusable.length === 0) {
    event.preventDefault();
    dialog.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement as HTMLElement | null;
  const isInsideDialog = Boolean(activeElement && dialog.contains(activeElement));
  if (event.shiftKey && (!isInsideDialog || activeElement === first)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (!isInsideDialog || activeElement === last)) {
    event.preventDefault();
    first.focus();
  }
}

function ensureListener() {
  if (isListening || typeof document === 'undefined') return;
  document.addEventListener('keydown', handleDocumentKeyDown);
  isListening = true;
}

function removeListenerWhenIdle() {
  if (!isListening || openDialogs.length > 0 || typeof document === 'undefined') return;
  document.removeEventListener('keydown', handleDocumentKeyDown);
  isListening = false;
}

export interface UseDialogAccessibilityOptions {
  /** Whether the modal is currently rendered and should participate in the focus stack. */
  isOpen: boolean;
  /** Invoked by Escape only when this is the topmost, dismissible dialog. */
  onClose?: () => void;
  /** Optional explicit initial focus target; otherwise the first tabbable element is used. */
  initialFocusRef?: RefObject<HTMLElement>;
  /** Set false for a modal that must block Escape while work is in progress. */
  dismissible?: boolean;
  /** Set false only when closing should deliberately leave focus where it is. */
  restoreFocus?: boolean;
}

/**
 * Adds the keyboard behavior required by a custom modal without owning its
 * markup: initial focus, Tab/Shift+Tab containment, topmost-only Escape, and
 * restoration to the element that opened it. The module-level stack lets a
 * nested dialog temporarily take control without closing its parent.
 */
export function useDialogAccessibility<T extends HTMLElement = HTMLElement>(
  options: UseDialogAccessibilityOptions,
): RefObject<T> {
  const dialogRef = useRef<T>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    if (!options.isOpen || typeof document === 'undefined') return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const registration: DialogRegistration = {
      getDialog: () => dialogRef.current,
      getOptions: () => optionsRef.current,
    };
    openDialogs.push(registration);
    ensureListener();
    const dialog = dialogRef.current;
    if (dialog) focusInitialElement(dialog, optionsRef.current);

    return () => {
      const index = openDialogs.indexOf(registration);
      if (index !== -1) openDialogs.splice(index, 1);
      removeListenerWhenIdle();
      if (optionsRef.current.restoreFocus !== false && opener?.isConnected) opener.focus();
    };
  }, [options.isOpen]);

  return dialogRef;
}
