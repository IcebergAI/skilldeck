import { Route, Routes } from "react-router-dom";

import { ProfilePage } from "./pages/ProfilePage";

export function App() {
  return (
    <Routes>
      <Route path="/members/:memberId" element={<ProfilePage />} />
    </Routes>
  );
}
