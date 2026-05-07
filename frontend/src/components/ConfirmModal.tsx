import React, { useEffect, useRef } from 'react';

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  title,
  message,
  confirmText = "Delete",
  cancelText = "Cancel",
  onConfirm,
  onCancel,
}) => {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      // Focus cancel button by default
      cancelRef.current?.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Handle escape
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
        return;
      }

      // Handle left/right arrow keys for button navigation
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        if (document.activeElement === cancelRef.current) {
          confirmRef.current?.focus();
        } else {
          cancelRef.current?.focus();
        }
        return;
      }

      // Focus trap for Tab
      if (e.key === "Tab") {
        const focusableElements = [cancelRef.current, confirmRef.current].filter(Boolean) as HTMLElement[];
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          // Shift + Tab
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement?.focus();
          }
        } else {
          // Tab
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement?.focus();
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay modal-overlay-high" onClick={onCancel}>
      <div 
        ref={modalRef}
        className="modal-content modal-content-narrow" 
        onClick={(e) => e.stopPropagation()} 
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
      >
        <h3 id="confirm-title" className="confirm-modal-title">
          {title}
        </h3>
        <p className="confirm-modal-message">
          {message}
        </p>
        <div className="confirm-modal-actions">
          <button 
            ref={cancelRef}
            onClick={onCancel}
            className="modal-btn"
          >
            {cancelText}
          </button>
          <button 
            ref={confirmRef}
            onClick={onConfirm}
            className="modal-btn modal-btn-danger"
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};
