"use client";
import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  side,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
  // "right" renders the panel as a full-height tray instead of a centred sheet.
  side?: "right";
}) {
  const panel = ["dialog-panel", side === "right" && "drawer", className]
    .filter(Boolean)
    .join(" ");
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="dialog-overlay" />
        <D.Content className={panel}>
          <div className="dialog-heading">
            <D.Title className="dialog-title">{title}</D.Title>
            <D.Description className="dialog-desc">{description}</D.Description>
          </div>
          <D.Close className="dialog-close" aria-label="Close dialog">
            <X size={20} />
          </D.Close>
          {children}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
