import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// Tailwind + the shadcn theme variables load FIRST, then the original
// stylesheet -- so during the migration, hand-written rules still win
// over Tailwind's base layer for components not yet converted, and
// nothing visually breaks mid-way. styles.css shrinks as components move
// over, and goes away entirely once the last one does.
import "./theme.css";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
