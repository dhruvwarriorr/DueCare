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
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/45" />
        <D.Content
          className={className ? "dialog-panel " + className : "dialog-panel"}
        >
          <div className="dialog-heading">
            <D.Title className="text-xl font-semibold">{title}</D.Title>
            <D.Description className="mt-1 text-sm text-secondary">
              {description}
            </D.Description>
          </div>
          <D.Close
            className="absolute right-4 top-4 rounded-md p-2 hover:bg-muted"
            aria-label="Close dialog"
          >
            <X size={18} />
          </D.Close>
          {children}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
