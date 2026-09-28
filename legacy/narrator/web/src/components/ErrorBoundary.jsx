import React from "react";
import { Button } from "@/components/ui/button";

// One per tab. Without it, any error thrown while rendering or updating
// a component unmounts the ENTIRE React tree -- the page goes blank and
// every other tab's state is lost with it (which is exactly what hiding
// the Dialogue tab's Providers panel used to do). With it, only the
// failing tab shows this message; everything else keeps working.
//
// Only render/commit-time errors are caught; an error inside an event
// handler or a promise doesn't unmount anything, so it doesn't need to.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, attempt: 0 };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Kept in the console for diagnosis; the on-screen text stays short.
    console.error(`${this.props.label || "Tab"} crashed:`, error, info?.componentStack);
  }

  render() {
    if (!this.state.error) {
      // Bumping `attempt` remounts the children from scratch on reset.
      return <React.Fragment key={this.state.attempt}>{this.props.children}</React.Fragment>;
    }
    return (
      <div role="alert" className="my-4 rounded-md border border-destructive/50 bg-card p-4">
        <p className="font-semibold text-destructive">
          {this.props.label || "This tab"} hit an error and stopped.
        </p>
        <p className="mt-1 break-words font-mono text-xs text-muted-foreground">
          {String(this.state.error?.message || this.state.error)}
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          The other tabs are unaffected. Resetting reloads just this tab
          (anything half-typed in it is lost); the details are in the
          browser console.
        </p>
        <Button
          className="mt-3"
          onClick={() => this.setState((s) => ({ error: null, attempt: s.attempt + 1 }))}
        >
          Reset this tab
        </Button>
      </div>
    );
  }
}
