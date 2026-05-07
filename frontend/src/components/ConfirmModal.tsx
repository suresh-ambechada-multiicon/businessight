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
    <div className="modal-overlay" onClick={onCancel} style={{ zIndex: 9999 }}>
      <div 
        ref={modalRef}
        className="modal-content" 
        onClick={(e) => e.stopPropagation()} 
        style={{ maxWidth: "400px", padding: "20px" }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
      >
        <h3 id="confirm-title" style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "12px", color: "var(--text-primary)" }}>
          {title}
        </h3>
        <p style={{ fontSize: "0.95rem", color: "var(--text-secondary)", marginBottom: "24px", lineHeight: 1.5 }}>
          {message}
        </p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px" }}>
          <button 
            ref={cancelRef}
            onClick={onCancel}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              background: "transparent",
              border: "1px solid var(--border-color)",
              color: "var(--text-primary)",
              cursor: "pointer",
              outlineOffset: "2px"
            }}
          >
            {cancelText}
          </button>
          <button 
            ref={confirmRef}
            onClick={onConfirm}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              background: "var(--danger-color, #ef4444)",
              border: "none",
              color: "white",
              cursor: "pointer",
              outlineOffset: "2px"
            }}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};
