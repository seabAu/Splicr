// Deliberately narrow: this exists to catch names that are USED but never
// defined or imported -- the bug class that shipped a crash in Publish
// (<Select> rendered without an import). Vite builds such code happily and
// it only fails at runtime, on whichever screen first renders it. This is
// not a style linter; add rules only for real, runtime-affecting mistakes.
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { react, "react-hooks": reactHooks },
    // The exhaustive-deps disable comments stay even with that rule off:
    // they mark each deliberately-omitted dependency, which matters the
    // day someone switches the rule on.
    linterOptions: { reportUnusedDisableDirectives: "off" },
    rules: {
      "no-undef": "error",
      "react/jsx-no-undef": "error",
      // Mark JSX usages as "used" so unused-import checks stay accurate.
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "error",
      // Hooks called conditionally or out of order break at runtime.
      "react-hooks/rules-of-hooks": "error",
      // Off: several effects intentionally omit deps (documented at each
      // site with a disable comment); turning this on would be noise.
      "react-hooks/exhaustive-deps": "off",
      // React treats whatever an effect RETURNS as its cleanup and calls
      // it on unmount/re-run. Passing a function reference that returns a
      // promise (useEffect(load, [])) made React call a promise -- it
      // blanked the whole app when the Dialogue tab's Providers panel was
      // hidden. Same risk for a concise arrow body: () => load().
      "no-restricted-syntax": ["error",
        {
          selector: "CallExpression[callee.name='useEffect'] > Identifier:first-child",
          message: "Wrap it: useEffect(() => { fn(); }, deps). A function reference's return value becomes the cleanup, and a returned promise crashes on unmount.",
        },
        {
          selector: "CallExpression[callee.name='useEffect'] > ArrowFunctionExpression:first-child[expression=true]",
          message: "Use a block body: useEffect(() => { ... }). A concise arrow returns its expression, which React then calls as cleanup.",
        },
      ],
      "no-unused-vars": ["warn", {
        varsIgnorePattern: "^(React|_)",
        // `const { a: _a, ...rest } = obj` is the idiom for omitting a key
        ignoreRestSiblings: true,
      }],
    },
  },
];
