import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from "react";

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

type KnockMessage = {
  id: number;
  place_id: number;
  place_name: string;
  user_id: number;
  nickname: string;
  author_rank: "VISITOR" | "BELONG";
  text: string;
  created_at: string;
};

type KnockHistoryResponse = {
  messages: KnockMessage[];
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

function mergeMessages(messages: KnockMessage[]): KnockMessage[] {
  const byId = new Map(messages.map((message) => [message.id, message]));
  return [...byId.values()]
    .sort(
      (left, right) =>
        new Date(left.created_at).getTime() -
        new Date(right.created_at).getTime(),
    )
    .slice(-100);
}

function PresencePanel({
  token,
  places,
  onPlacesChange,
}: {
  token: string;
  places: CurrentPlace[];
  onPlacesChange: (places: CurrentPlace[]) => void;
}) {
  const [requestNumber, setRequestNumber] = useState(0);
  const [status, setStatus] = useState<"idle" | "requesting" | "active">(
    "idle",
  );
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest<PresenceResponse>("/api/presence/current", {}, token)
      .then((response) => {
        onPlacesChange(response.places);
        if (response.places.length) {
          setStatus("active");
        }
      })
      .catch(() => undefined);
  }, [token, onPlacesChange]);

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
          onPlacesChange(response.places);
          setStatus("active");
          setError("");
        }
      } catch (caught) {
        if (active) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not detect your place",
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
          setError(
            locationError.message || "Location permission was not granted.",
          );
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
  }, [requestNumber, token, onPlacesChange]);

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
        Presence expires after 90 seconds without a location heartbeat.
      </p>
    </section>
  );
}

function KnockPanel({
  token,
  user,
  places,
}: {
  token: string;
  user: User;
  places: CurrentPlace[];
}) {
  const socketRef = useRef<WebSocket | null>(null);
  const [messages, setMessages] = useState<KnockMessage[]>([]);
  const [connection, setConnection] = useState<
    "waiting" | "connecting" | "connected" | "disconnected"
  >("waiting");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const placeKey = places.map((place) => place.id).join(",");

  useEffect(() => {
    if (!places.length) {
      setMessages([]);
      setConnection("waiting");
      setError("");
      return;
    }

    let active = true;
    let reconnectTimer: number | undefined;

    Promise.all(
      places.map((place) =>
        apiRequest<KnockHistoryResponse>(
          `/api/knock/history?place_id=${place.id}`,
          {},
          token,
        ),
      ),
    )
      .then((histories) => {
        if (active) {
          const historyMessages = histories.flatMap(
            (history) => history.messages,
          );
          setMessages((current) =>
            mergeMessages([...historyMessages, ...current]),
          );
        }
      })
      .catch((caught) => {
        if (active) {
          setError(
            caught instanceof Error ? caught.message : "Could not load history",
          );
        }
      });

    function connect() {
      if (!active) {
        return;
      }
      setConnection("connecting");
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(
        `${protocol}//${window.location.host}/ws/knock?token=${encodeURIComponent(token)}`,
      );
      socketRef.current = socket;

      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === "ready") {
          setConnection("connected");
          setError("");
        } else if (payload.type === "message") {
          setMessages((current) =>
            mergeMessages([...current, payload.message as KnockMessage]),
          );
          setError("");
        } else if (payload.type === "error") {
          setError(payload.detail || "The KNOCK could not be sent.");
        }
      };

      socket.onclose = (event) => {
        if (!active) {
          return;
        }
        setConnection("disconnected");
        if (event.code === 4401) {
          setError("Your session expired. Log in again.");
          return;
        }
        if (event.code === 4403) {
          setError("Share your location to join nearby KNOCKS.");
          return;
        }
        reconnectTimer = window.setTimeout(connect, 2_000);
      };
    }

    connect();
    return () => {
      active = false;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [token, placeKey]);

  function sendKnock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) {
      return;
    }
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      setError("KNOCK is reconnecting. Try again in a moment.");
      return;
    }
    socketRef.current.send(JSON.stringify({ type: "message", text }));
    setDraft("");
  }

  if (!places.length) {
    return (
      <section className="knock-card knock-empty">
        <span className="knock-icon" aria-hidden="true">◎</span>
        <h2>Nearby KNOCKS appear here</h2>
        <p>Share your location to join the live conversation at your place.</p>
      </section>
    );
  }

  return (
    <section className="knock-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Live nearby</p>
          <h2>KNOCK</h2>
        </div>
        <span className={`socket-status socket-status--${connection}`}>
          {connection === "connected" ? "Connected" : connection}
        </span>
      </header>

      <div className="place-chips" aria-label="Active place layers">
        {places.map((place) => (
          <span key={place.id}>{place.name}</span>
        ))}
      </div>

      <div className="knock-feed" aria-live="polite">
        {messages.length === 0 ? (
          <div className="feed-empty">
            <p>No KNOCKS yet.</p>
            <span>Start the conversation at this place.</span>
          </div>
        ) : (
          messages.map((message) => (
            <article
              className={`knock-message ${message.user_id === user.id ? "knock-message--own" : ""}`}
              key={message.id}
            >
              <div className="message-meta">
                <strong>{message.nickname}</strong>
                <span>{message.place_name}</span>
                <time dateTime={message.created_at}>
                  {new Date(message.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </div>
              <p>{message.text}</p>
            </article>
          ))
        )}
      </div>

      {error && <p className="knock-error">{error}</p>}
      <form className="knock-composer" onSubmit={sendKnock}>
        <label htmlFor="knock-message">Send a KNOCK</label>
        <textarea
          id="knock-message"
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="What is happening here?"
          rows={3}
          value={draft}
        />
        <div className="composer-footer">
          <small>{draft.length}/500</small>
          <button
            className="button"
            disabled={connection !== "connected" || !draft.trim()}
            type="submit"
          >
            KNOCK
          </button>
        </div>
      </form>
    </section>
  );
}

function SignedInApp({
  token,
  user,
  onLogout,
}: {
  token: string;
  user: User;
  onLogout: () => void;
}) {
  const [places, setPlaces] = useState<CurrentPlace[]>([]);

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">PlacePulse</p>
          <h1>What is happening here?</h1>
        </div>
        <div className="user-chip">
          <span>{user.nickname}</span>
          <small>Signed in</small>
        </div>
      </header>

      <div className="app-content">
        <aside className="app-sidebar">
          <PresencePanel
            onPlacesChange={setPlaces}
            places={places}
            token={token}
          />
          <section className="account-summary">
            <p className="eyebrow">Account</p>
            <strong>{user.nickname}</strong>
            <span>{user.phone}</span>
            <button
              className="button button--secondary"
              onClick={onLogout}
              type="button"
            >
              Log out
            </button>
          </section>
        </aside>

        <KnockPanel places={places} token={token} user={user} />
      </div>
    </main>
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

  if (checkingSession) {
    return (
      <main className="page-shell">
        <p className="session-check">Checking your session...</p>
      </main>
    );
  }

  if (user && token) {
    return <SignedInApp onLogout={handleLogout} token={token} user={user} />;
  }

  return (
    <main className="page-shell">
      <section className="auth-card">
        <header className="brand-block">
          <p className="eyebrow">PlacePulse</p>
          <h1>Know what is happening here.</h1>
          <p>
            Sign in and share your location to join live conversations around
            you.
          </p>
        </header>

        <div className="form-block" aria-live="polite">
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
        </div>
      </section>
    </main>
  );
}

export default App;
