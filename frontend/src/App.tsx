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

type Dig = {
  id: number;
  place_id: number;
  place_name: string;
  user_id: number;
  nickname: string;
  media_type: "image" | "video";
  content_type: string;
  original_filename: string;
  file_size: number;
  media_url: string;
  created_at: string;
  expires_at: string;
};

type DigFeedResponse = {
  digs: Dig[];
};

const TOKEN_KEY = "placepulse-session";

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) {
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

function DigMedia({ dig, token }: { dig: Dig; token: string }) {
  const [source, setSource] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    fetch(dig.media_url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Media is no longer available");
        }
        return response.blob();
      })
      .then((blob) => {
        if (active) {
          objectUrl = URL.createObjectURL(blob);
          setSource(objectUrl);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Media unavailable");
        }
      });

    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [dig.id, dig.media_url, token]);

  if (error) {
    return <p className="dig-media-state">{error}</p>;
  }
  if (!source) {
    return <p className="dig-media-state">Loading media...</p>;
  }
  if (dig.media_type === "video") {
    return <video className="dig-media" controls playsInline src={source} />;
  }
  return (
    <img
      alt={`DIG shared by ${dig.nickname} at ${dig.place_name}`}
      className="dig-media"
      src={source}
    />
  );
}

function DigPanel({
  token,
  places,
}: {
  token: string;
  places: CurrentPlace[];
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [digs, setDigs] = useState<Dig[]>([]);
  const [selectedPlaceId, setSelectedPlaceId] = useState("");
  const [refreshNumber, setRefreshNumber] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const placeKey = places.map((place) => place.id).join(",");

  useEffect(() => {
    if (!places.length) {
      setSelectedPlaceId("");
      return;
    }
    if (!places.some((place) => String(place.id) === selectedPlaceId)) {
      setSelectedPlaceId(String(places[places.length - 1].id));
    }
  }, [placeKey, places, selectedPlaceId]);

  useEffect(() => {
    if (!places.length) {
      setDigs([]);
      return;
    }

    let active = true;
    setError("");
    Promise.all(
      places.map((place) =>
        apiRequest<DigFeedResponse>(
          `/api/digs?place_id=${place.id}`,
          {},
          token,
        ),
      ),
    )
      .then((feeds) => {
        if (!active) {
          return;
        }
        const unique = new Map<number, Dig>();
        feeds.flatMap((feed) => feed.digs).forEach((dig) => unique.set(dig.id, dig));
        setDigs(
          [...unique.values()].sort(
            (left, right) =>
              new Date(right.created_at).getTime() -
              new Date(left.created_at).getTime(),
          ),
        );
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load DIGs");
        }
      });
    return () => {
      active = false;
    };
  }, [placeKey, places, refreshNumber, token]);

  async function uploadDig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedFile = inputRef.current?.files?.[0];
    if (!selectedFile || !selectedPlaceId) {
      setError("Choose a place and a media file.");
      return;
    }
    if (selectedFile.size > 10 * 1024 * 1024) {
      setError("DIG uploads cannot exceed 10 MB.");
      return;
    }

    setUploading(true);
    setError("");
    setNotice("");
    const form = new FormData();
    form.set("place_id", selectedPlaceId);
    form.set("file", selectedFile);
    try {
      await apiRequest<Dig>(
        "/api/digs",
        { method: "POST", body: form },
        token,
      );
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      setNotice("DIG published. It will disappear after 24 hours.");
      setRefreshNumber((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  if (!places.length) {
    return (
      <section className="knock-card knock-empty">
        <span className="knock-icon" aria-hidden="true">&#9673;</span>
        <h2>Nearby DIGs appear here</h2>
        <p>Share your location to view and post temporary media.</p>
      </section>
    );
  }

  return (
    <section className="knock-card dig-card">
      <header className="knock-heading">
        <div>
          <p className="eyebrow">Temporary nearby media</p>
          <h2>DIG</h2>
        </div>
        <span className="dig-lifetime">24 hours</span>
      </header>

      <form className="dig-composer" onSubmit={uploadDig}>
        <label>
          Post to
          <select
            onChange={(event) => setSelectedPlaceId(event.target.value)}
            required
            value={selectedPlaceId}
          >
            {places.map((place) => (
              <option key={place.id} value={place.id}>
                {place.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Image or short video
          <input
            accept="image/jpeg,image/png,image/webp,video/mp4,video/webm"
            ref={inputRef}
            required
            type="file"
          />
        </label>
        <div className="dig-upload-footer">
          <small>JPEG, PNG, WebP, MP4, or WebM. Up to 10 MB and 15 seconds.</small>
          <button className="button" disabled={uploading} type="submit">
            {uploading ? "Checking..." : "Post DIG"}
          </button>
        </div>
      </form>

      {notice && <p className="dig-notice">{notice}</p>}
      {error && <p className="knock-error">{error}</p>}

      <div className="dig-feed" aria-live="polite">
        {digs.length === 0 ? (
          <div className="feed-empty">
            <p>No active DIGs yet.</p>
            <span>Share the first view from this place.</span>
          </div>
        ) : (
          digs.map((dig) => (
            <article className="dig-item" key={dig.id}>
              <DigMedia dig={dig} token={token} />
              <div className="dig-meta">
                <div>
                  <strong>{dig.nickname}</strong>
                  <span>{dig.place_name}</span>
                </div>
                <time dateTime={dig.expires_at}>
                  Expires {new Date(dig.expires_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </div>
            </article>
          ))
        )}
      </div>
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
  const [mainView, setMainView] = useState<"knock" | "dig">("knock");

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

        <div className="main-pane">
          <nav className="main-tabs" aria-label="Place activity">
            <button
              className={mainView === "knock" ? "active" : ""}
              onClick={() => setMainView("knock")}
              type="button"
            >
              KNOCK
            </button>
            <button
              className={mainView === "dig" ? "active" : ""}
              onClick={() => setMainView("dig")}
              type="button"
            >
              DIG
            </button>
          </nav>
          {mainView === "knock" ? (
            <KnockPanel places={places} token={token} user={user} />
          ) : (
            <DigPanel places={places} token={token} />
          )}
        </div>
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
