import { useEffect, useRef } from "react";
import { Route, Routes } from "react-router-dom";

import { mountHelpWidget } from "./embed/helpWidget";
import { ProfilePage } from "./pages/ProfilePage";

function HelpDock() {
  const dock = useRef<HTMLDivElement>(null);
  useEffect(() => (dock.current ? mountHelpWidget(dock.current) : undefined), []);
  return <div ref={dock} className="help-dock" />;
}

export function App() {
  return (
    <>
      <Routes>
        <Route path="/members/:memberId" element={<ProfilePage />} />
      </Routes>
      <HelpDock />
    </>
  );
}
