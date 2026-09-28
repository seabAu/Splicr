import * as React from "react";
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// For confirmations that shouldn't be dismissed by accident. Unlike
// Dialog: clicking the backdrop does NOT close it, it's announced as an
// alertdialog, and Radix puts initial focus on Cancel -- so pressing
// Enter by reflex cancels rather than confirms. Replaces window.confirm,
// which can't be styled and blocks the whole page's JS while open.

const AlertDialog = AlertDialogPrimitive.Root;

const AlertDialogContent = React.forwardRef(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Portal>
    <AlertDialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60" />
    <AlertDialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-1/2 top-1/2 z-50 grid w-full max-w-md -translate-x-1/2",
        "-translate-y-1/2 gap-3 rounded-lg border border-border bg-card p-5",
        "text-card-foreground shadow-xl focus:outline-none",
        className
      )}
      {...props}
    />
  </AlertDialogPrimitive.Portal>
));
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName;

const AlertDialogTitle = React.forwardRef(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Title
    ref={ref}
    className={cn("text-base font-semibold", className)}
    {...props}
  />
));
AlertDialogTitle.displayName = AlertDialogPrimitive.Title.displayName;

const AlertDialogDescription = React.forwardRef(
  ({ className, ...props }, ref) => (
    <AlertDialogPrimitive.Description
      ref={ref}
      className={cn("whitespace-pre-line text-[13px] text-muted-foreground", className)}
      {...props}
    />
  )
);
AlertDialogDescription.displayName = AlertDialogPrimitive.Description.displayName;

const AlertDialogAction = React.forwardRef(
  ({ className, variant = "destructive", ...props }, ref) => (
    <AlertDialogPrimitive.Action
      ref={ref}
      className={cn(buttonVariants({ variant }), className)}
      {...props}
    />
  )
);
AlertDialogAction.displayName = AlertDialogPrimitive.Action.displayName;

const AlertDialogCancel = React.forwardRef(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Cancel
    ref={ref}
    className={cn(buttonVariants({ variant: "default" }), className)}
    {...props}
  />
));
AlertDialogCancel.displayName = AlertDialogPrimitive.Cancel.displayName;

// The shape every confirmation in the app actually needs, so callers
// don't reassemble the parts each time. `pending` holds whatever is
// being confirmed (null = closed); onConfirm receives it back.
function ConfirmDialog({ pending, title, description, confirmLabel = "Delete",
                         onConfirm, onCancel }) {
  return (
    <AlertDialog open={!!pending} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        <AlertDialogDescription>{description}</AlertDialogDescription>
        <div className="mt-1 flex justify-end gap-2">
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={() => onConfirm(pending)}>
            {confirmLabel}
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export { ConfirmDialog };
