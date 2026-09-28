import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Close } from "@/components/ui/icons";
import { cn } from "@/lib/utils";

// Modal dialogs: focus is trapped inside while open, returned to
// whatever opened it on close, the page behind is inert to both mouse
// and screen readers, and Escape / clicking the backdrop dismiss it.
// The file browser used to be an inline panel with none of that -- it
// pushed the rest of the page down and left everything behind it
// clickable while a path was being chosen.

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogPortal = DialogPrimitive.Portal;
const DialogClose = DialogPrimitive.Close;

const DialogOverlay = React.forwardRef(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn("fixed inset-0 z-50 bg-black/60", className)}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

const DialogContent = React.forwardRef(
  ({ className, children, ...props }, ref) => (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        ref={ref}
        className={cn(
          "fixed left-1/2 top-1/2 z-50 grid w-full max-w-2xl",
          "-translate-x-1/2 -translate-y-1/2 gap-3 rounded-lg border",
          "border-border bg-card p-5 text-card-foreground shadow-xl",
          "max-h-[85vh] focus:outline-none",
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className={cn(
            "absolute right-3 top-3 rounded-sm p-1 text-muted-foreground",
            "hover:text-foreground focus:outline-none focus-visible:ring-2",
            "focus-visible:ring-ring"
          )}
          aria-label="Close"
        >
          <Close className="h-4 w-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPortal>
  )
);
DialogContent.displayName = DialogPrimitive.Content.displayName;

const DialogHeader = ({ className, ...props }) => (
  <div className={cn("flex flex-col gap-1 pr-6", className)} {...props} />
);

const DialogFooter = ({ className, ...props }) => (
  <div
    className={cn("flex items-center justify-end gap-2", className)}
    {...props}
  />
);

const DialogTitle = React.forwardRef(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-base font-semibold", className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-xs text-muted-foreground", className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
};
