import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
const variants = cva("btn", {
  variants: {
    variant: {
      default: "btn-primary",
      outline: "btn-outline",
      ghost: "btn-ghost",
      destructive: "btn-destructive",
    },
    size: { default: "btn-md", sm: "btn-sm", icon: "btn-icon" },
  },
  defaultVariants: { variant: "default", size: "default" },
});
export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof variants> & { asChild?: boolean }) {
  const C = asChild ? Slot : "button";
  return (
    <C className={cn(variants({ variant, size, className }))} {...props} />
  );
}
