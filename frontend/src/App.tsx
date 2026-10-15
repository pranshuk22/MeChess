import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { RouteError } from "@/components/RouteError";
import { Shell } from "@/components/Shell";
import { HomePage } from "@/features/home/Home";

const LibraryPage = lazy(() => import("@/features/library/Library").then((m) => ({ default: m.LibraryPage })));
const ReviewPage = lazy(() => import("@/features/review/Review").then((m) => ({ default: m.ReviewPage })));
const SettingsPage = lazy(() => import("@/features/settings/Settings").then((m) => ({ default: m.SettingsPage })));
const CoachPage = lazy(() => import("@/features/coach/Coach").then((m) => ({ default: m.CoachPage })));
const ExplorerPage = lazy(() => import("@/features/explorer/ExplorerPage").then((m) => ({ default: m.ExplorerPage })));
const BotPage = lazy(() => import("@/features/bot/BotPage").then((m) => ({ default: m.BotPage })));
const BooksPage = lazy(() => import("@/features/books/BooksPage").then((m) => ({ default: m.BooksPage })));
const PlayPage = lazy(() => import("@/features/play/Play").then((m) => ({ default: m.PlayPage })));
const InsightsPage = lazy(() => import("@/features/insights/Insights").then((m) => ({ default: m.InsightsPage })));
const ActivityPage = lazy(() => import("@/features/Activity").then((m) => ({ default: m.ActivityPage })));

const client = new QueryClient();
const wait = (el: React.ReactNode) => <Suspense fallback={<div className="p-8 text-muted">Loading…</div>}>{el}</Suspense>;

const router = createBrowserRouter([{
  element: <Shell />,
  errorElement: <RouteError />,
  children: [
    { path: "/", element: <HomePage /> },
    { path: "/library", element: wait(<LibraryPage />) },
    { path: "/review/:id?", element: wait(<ReviewPage />) },
    { path: "/settings", element: wait(<SettingsPage />) },
    { path: "/coach", element: wait(<CoachPage />) },
    { path: "/play", element: wait(<PlayPage />) },
    { path: "/explorer", element: wait(<ExplorerPage />) },
    { path: "/insights", element: wait(<InsightsPage />) },
    { path: "/books", element: wait(<BooksPage />) },
    { path: "/bot", element: wait(<BotPage />) },
    { path: "/activity", element: wait(<ActivityPage />) },
  ],
}]);

export function App() {
  return <QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>;
}
