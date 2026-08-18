import { useEffect, useState } from "react";

type HealthState = "checking" | "ready" | "unavailable";

function App() {
  const [health, setHealth] = useState<HealthState>("checking");

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/health", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Health check failed");
        }
        return response.json();
      })
      .then(() => setHealth("ready"))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setHealth("unavailable");
      });

    return () => controller.abort();
  }, []);

  const message = {
    checking: "Checking the backend…",
    ready: "Foundation is running",
    unavailable: "Backend is unavailable",
  }[health];

  return (
    <main className="page-shell">
      <section className="status-card" aria-live="polite">
        <p className="eyebrow">PlacePulse</p>
        <h1>Know what’s happening here.</h1>
        <p className="description">
          The project foundation is ready. Location, KNOCK, DIG, and Explore will
          be added one step at a time.
        </p>
        <div className={`health health--${health}`}>
          <span className="health__dot" aria-hidden="true" />
          {message}
        </div>
      </section>
    </main>
  );
}

export default App;

