// The help-center widget runs in an iframe served by our support vendor. When
// a member opens an article that links into the community, the widget asks
// the app to take them there.
const WIDGET_URL = "https://widget.helpdesk-vendor.example/embed?site=acme";

interface WidgetMessage {
  type?: string;
  url?: string;
}

export function mountHelpWidget(container: HTMLElement): () => void {
  const frame = document.createElement("iframe");
  frame.src = WIDGET_URL;
  frame.title = "Help";
  frame.className = "help-widget";
  container.appendChild(frame);

  const onMessage = (event: MessageEvent<WidgetMessage>) => {
    if (event.data?.type === "navigate" && event.data.url) {
      window.location.assign(event.data.url);
    }
  };
  window.addEventListener("message", onMessage);

  return () => {
    window.removeEventListener("message", onMessage);
    frame.remove();
  };
}
