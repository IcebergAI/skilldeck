// The help-center widget runs in an iframe served by our support vendor. When
// a member opens an article that links into the community, the widget asks
// the app to take them there.
const WIDGET_URL = "https://widget.helpdesk-vendor.example/embed?site=acme";
const WIDGET_ORIGIN = new URL(WIDGET_URL).origin;

interface WidgetMessage {
  type?: unknown;
  url?: unknown;
}

// Only paths inside the app: a relative URL that resolves to our own origin.
function inAppUrl(raw: unknown): URL | null {
  if (typeof raw !== "string") return null;
  try {
    const target = new URL(raw, window.location.origin);
    return target.origin === window.location.origin ? target : null;
  } catch {
    return null;
  }
}

export function mountHelpWidget(container: HTMLElement): () => void {
  const frame = document.createElement("iframe");
  frame.src = WIDGET_URL;
  frame.title = "Help";
  frame.className = "help-widget";
  container.appendChild(frame);

  const onMessage = (event: MessageEvent<WidgetMessage>) => {
    // only our own widget frame, served from the vendor's origin
    if (event.origin !== WIDGET_ORIGIN || event.source !== frame.contentWindow) {
      return;
    }
    if (event.data?.type !== "navigate") return;
    const target = inAppUrl(event.data.url);
    if (target) {
      window.location.assign(target.pathname + target.search + target.hash);
    }
  };
  window.addEventListener("message", onMessage);

  return () => {
    window.removeEventListener("message", onMessage);
    frame.remove();
  };
}
