import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// Every shadcn component uses this: clsx handles conditional classes,
// twMerge resolves Tailwind conflicts so a later class actually wins
// (e.g. a caller passing "p-0" overrides a component's built-in "p-4"
// instead of both landing in the class list and the CSS order deciding).
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
