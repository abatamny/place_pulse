import { type FormEvent, useEffect, useState } from "react";

type View = "login" | "register" | "verify";

type User = {
  id: number;
  phone: string;
  nickname: string;
};

type RegistrationResponse = {
  message: string;
  verification_code: string | null;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

type CurrentPlace = {
  id: number;
  osm_type: string;
  osm_id: number;
  name: string;
  parent_place_id: number | null;
  rank: "VISITOR" | "BELONG";
  completed_visits: number;
};

type PresenceResponse = {
  places: CurrentPlace[];
  expires_in_seconds: number;
};

const TOKEN_KEY = "placepulse-session";

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join(". ")
      : detail || "Something went wrong. Please try again.";
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function PresencePanel({ token }: { token: string }) {
  const [requestNumber, setRequestNumber] = useState(0);
  const [places, setPlaces] = useState<CurrentPlace[]>([]);
  const [status, setStatus] = useState<"idle" | "requesting" | "active">("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest<PresenceResponse>("/api/presence/current", {}, token)
      .then((response) => setPlaces(response.places))
      .catch(() => undefined);
  }, [token]);

  useEffect(() => {
    if (requestNumber === 0) {
      return;
    }
    if (!navigator.geolocation) {
      setError("This browser does not support location sharing.");
      return;
    }

    let active = true;
    let sending = false;
    let latestCoordinates: { latitude: number; longitude: number } | null = null;
    setStatus("requesting");
    setError("");

    async function sendHeartbeat(latitude: number, longitude: number) {
      if (sending) {
        return;
      }
      sending = true;
      try {
        const response = await apiRequest<PresenceResponse>(
          "/api/presence/heartbeat",
          {
            method: "POST",
            body: JSON.stringify({ latitude, longitude }),
          },
          token,
        );
        if (active) {
          setPlaces(response.places);
          setStatus("active");
          setError("");
        }
      } catch (caught) {
        if (active) {
          setError(
            caught instanceof Error ? caught.message : "Could not detect your place",
          );
          setStatus("idle");
        }
      } finally {
        sending = false;
      }
    }

    const watchId = navigator.geolocation.watchPosition(
      (position) => {
        latestCoordinates = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        void sendHeartbeat(
          latestCoordinates.latitude,
          latestCoordinates.longitude,
        );
      },
      (locationError) => {
        if (active) {
          setError(locationError.message || "Location permission was not granted.");
          setStatus("idle");
        }
      },
      { enableHighAccuracy: true, maximumAge: 15_000, timeout: 12_000 },
    );

    const intervalId = window.setInterval(() => {
      if (latestCoordinates) {
        void sendHeartbeat(
          latestCoordinates.latitude,
          latestCoordinates.longitude,
        );
      }
    }, 30_000);

    const leaveOnPageExit = () => {
      void fetch("/api/presence/leave", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        keepalive: true,
      });
    };
    window.addEventListener("pagehide", leaveOnPageExit);

    return () => {
      active = false;
      navigator.geolocation.clearWatch(watchId);
      window.clearInterval(intervalId);
      window.removeEventListener("pagehide", leaveOnPageExit);
    };
  }, [requestNumber, token]);

  return (
    <section className="presence-panel">
      <div className="presence-heading">
        <div>
          <p className="eyebrow">Your place</p>
          <h3>{places.length ? "Location detected" : "Share your location"}</h3>
        </div>
        {status === "active" && <span className="live-badge">Live</span>}
      </div>

      {places.length > 0 && (
        <ol className="place-list">
          {places.map((place) => (
            <li key={place.id}>
              <span>{place.name}</span>
              <small>{place.rank}</small>
            </li>
          ))}
        </ol>
      )}

      {error && <p className="location-error">{error}</p>}
      <button
        className="button"
        disabled={status === "requesting"}
        onClick={() => setRequestNumber((value) => value + 1)}
        type="button"
      >
        {status === "requesting"
          ? "Detecting place..."
          : status === "active"
            ? "Refresh location"
            : "Share my location"}
      </button>
      <p className="location-note">
        Location is sent only while this page is open. Presence expires after 90
        seconds without a heartbeat.
      </p>
    </section>
  );
}

function App() {
  const [view, setView] = useState<View>("login");
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY),
  );
  const [user, setUser] = useState<User | null>(null);
  const [checkingSession, setCheckingSession] = useState(Boolean(token));
  const [pendingPhone, setPendingPhone] = useState("");
  const [developmentCode, setDevelopmentCode] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      setCheckingSession(false);
      return;
    }

    setCheckingSession(true);
    apiRequest<User>("/api/auth/me", {}, token)
      .then(setUser)
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setUser(null);
      })
      .finally(() => setCheckingSession(false));
  }, [token]);

  function selectView(nextView: View) {
    setView(nextView);
    setError("");
    setNotice("");
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");

    const form = new FormData(event.currentTarget);
    const phone = String(form.get("phone") || "");

    try {
      const response = await apiRequest<RegistrationResponse>(
        "/api/auth/register",
        {
          method: "POST",
          body: JSON.stringify({
            phone,
            nickname: String(form.get("nickname") || ""),
            password: String(form.get("password") || ""),
          }),
        },
      );
      setPendingPhone(phone);
      setDevelopmentCode(response.verification_code);
      setNotice(response.message);
      setView("verify");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    const form = new FormData(event.currentTarget);
    try {
      await apiRequest<User>("/api/auth/verify", {
        method: "POST",
        body: JSON.stringify({
          phone: pendingPhone,
          code: String(form.get("code") || ""),
        }),
      });
      setDevelopmentCode(null);
      setNotice("Phone verified. You can now log in.");
      setView("login");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Verification failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setNotice("");

    const form = new FormData(event.currentTarget);
    try {
      const response = await apiRequest<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          phone: String(form.get("phone") || ""),
          password: String(form.get("password") || ""),
        }),
      });
      localStorage.setItem(TOKEN_KEY, response.access_token);
      setToken(response.access_token);
      setUser(response.user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    if (token) {
      await apiRequest<void>(
        "/api/presence/leave",
        { method: "POST" },
        token,
      ).catch(() => undefined);
      await apiRequest<void>("/api/auth/logout", { method: "POST" }, token).catch(
        () => undefined,
      );
    }
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setNotice("You have been logged out.");
    setView("login");
  }

  return (
    <main className="page-shell">
      <section className="auth-card">
        <header className="brand-block">
          <p className="eyebrow">PlacePulse</p>
          <h1>Know what is happening here.</h1>
          <p>
            Sign in and share your location to discover the OpenStreetMap places
            around you.
          </p>
        </header>

        <div className="form-block" aria-live="polite">
          {checkingSession ? (
            <p className="session-check">Checking your session...</p>
          ) : user ? (
            <div className="account-panel">
              <p className="eyebrow">Signed in</p>
              <h2>Welcome, {user.nickname}</h2>
              <dl>
                <div>
                  <dt>Phone</dt>
                  <dd>{user.phone}</dd>
                </div>
                <div>
                  <dt>Access</dt>
                  <dd>Authenticated</dd>
                </div>
              </dl>
              {token && <PresencePanel token={token} />}
              <button className="button button--secondary" onClick={handleLogout}>
                Log out
              </button>
            </div>
          ) : (
            <>
              {view !== "verify" && (
                <nav className="auth-tabs" aria-label="Authentication options">
                  <button
                    className={view === "login" ? "active" : ""}
                    onClick={() => selectView("login")}
                    type="button"
                  >
                    Log in
                  </button>
                  <button
                    className={view === "register" ? "active" : ""}
                    onClick={() => selectView("register")}
                    type="button"
                  >
                    Register
                  </button>
                </nav>
              )}

              {notice && <p className="message message--success">{notice}</p>}
              {error && <p className="message message--error">{error}</p>}

              {view === "login" && (
                <form onSubmit={handleLogin}>
                  <h2>Log in</h2>
                  <label>
                    Phone number
                    <input
                      name="phone"
                      type="tel"
                      inputMode="tel"
                      autoComplete="tel"
                      required
                    />
                  </label>
                  <label>
                    Password
                    <input
                      name="password"
                      type="password"
                      autoComplete="current-password"
                      required
                    />
                  </label>
                  <button className="button" disabled={loading} type="submit">
                    {loading ? "Logging in..." : "Log in"}
                  </button>
                </form>
              )}

              {view === "register" && (
                <form onSubmit={handleRegister}>
                  <h2>Create an account</h2>
                  <label>
                    Nickname
                    <input
                      name="nickname"
                      type="text"
                      minLength={2}
                      maxLength={30}
                      autoComplete="nickname"
                      required
                    />
                  </label>
                  <label>
                    Phone number
                    <input
                      name="phone"
                      type="tel"
                      inputMode="tel"
                      autoComplete="tel"
                      required
                    />
                  </label>
                  <label>
                    Password
                    <input
                      name="password"
                      type="password"
                      minLength={8}
                      maxLength={128}
                      autoComplete="new-password"
                      required
                    />
                  </label>
                  <p className="hint">Use at least 8 characters.</p>
                  <button className="button" disabled={loading} type="submit">
                    {loading ? "Creating account..." : "Register"}
                  </button>
                </form>
              )}

              {view === "verify" && (
                <form onSubmit={handleVerify}>
                  <p className="eyebrow">One more step</p>
                  <h2>Verify your phone</h2>
                  <p className="form-copy">Code sent for {pendingPhone}.</p>
                  {developmentCode && (
                    <p className="development-code">
                      Local verification code: <strong>{developmentCode}</strong>
                    </p>
                  )}
                  <label>
                    Six-digit code
                    <input
                      name="code"
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      autoComplete="one-time-code"
                      required
                    />
                  </label>
                  <button className="button" disabled={loading} type="submit">
                    {loading ? "Verifying..." : "Verify phone"}
                  </button>
                  <button
                    className="text-button"
                    onClick={() => selectView("register")}
                    type="button"
                  >
                    Start registration again
                  </button>
                </form>
              )}
            </>
          )}
        </div>
      </section>
    </main>
  );
}

export default App;
