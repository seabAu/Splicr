import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

// Variants map onto what this app actually uses, rather than shadcn's
// stock set: the old stylesheet had a "primary" action button, plain
// secondary buttons, small inline text buttons (the file browser's
// "choose", the timeline's controls), and destructive ones (delete a
// voice). Anything not covered here should get a new variant rather than
// a one-off className, so the set stays honest about what exists.
const buttonVariants = cva(
  cn(
    "inline-flex items-center justify-center gap-2 whitespace-nowrap",
    "rounded-md font-medium transition-colors focus-visible:outline-none",
    "focus-visible:ring-2 focus-visible:ring-ring",
    "disabled:pointer-events-none disabled:opacity-50"
  ),
  {
    variants: {
      variant: {
        default:
          "bg-secondary text-foreground border border-border hover:bg-accent",
        primary:
          "bg-primary text-primary-foreground font-semibold hover:opacity-90",
        destructive:
          "border border-border text-destructive hover:border-destructive",
        ghost:
          "text-muted-foreground hover:bg-secondary hover:text-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-3.5 py-2 text-[13px]",
        sm: "h-7 rounded px-2 text-[11px]",
        lg: "h-10 px-5 text-sm",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

const Button = React.forwardRef(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
