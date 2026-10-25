import { Link, Route, Routes } from "react-router";
import { AppLayout } from "./components/Layout";
import { AnalyticsPage } from "./pages/Analytics";
import { LoginPage, SignupPage } from "./pages/Auth";
import { ConversationsPage } from "./pages/Conversations";
import { DocumentsPage } from "./pages/Documents";
import { KbListPage } from "./pages/KbList";
import { KbShell } from "./pages/KbShell";
import { PlaygroundPage } from "./pages/Playground";
import { PublicChatPage } from "./pages/PublicChat";
import { SettingsPage } from "./pages/Settings";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/chat/:slug" element={<PublicChatPage />} />
      <Route element={<AppLayout />}>
        <Route index element={<KbListPage />} />
        <Route path="kb/:kbId" element={<KbShell />}>
          <Route index element={<PlaygroundPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="conversations" element={<ConversationsPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route
          path="*"
          element={
            <p>
              Page not found. <Link to="/">Back to knowledge bases</Link>
            </p>
          }
        />
      </Route>
    </Routes>
  );
}
