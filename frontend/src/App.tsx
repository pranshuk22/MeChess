import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { RouteError } from "@/components/RouteError";
import { Shell } from "@/components/Shell";
import { Planned } from "@/features/Planned";
import { HomePage } from "@/features/home/Home";

const LibraryPage = lazy(() => import("@/features/library/Library").then((m) => ({ default: m.LibraryPage })));
const ReviewPage = lazy(() => import("@/features/review/Review").then((m) => ({ default: m.ReviewPage })));
const SettingsPage = lazy(() => import("@/features/settings/Settings").then((m) => ({ default: m.SettingsPage })));
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
    { path: "/coach", element: <Planned title="Coach" text="Practice that comes from your own games." items={["Positions from your mistakes, repeated at growing intervals", "Opening practice from your repertoire", "Endgames checked against tablebases", "Steered games that train a chosen weakness", "Where you give away points compared with players of your rating"]} milestone="milestone 4" /> },
    { path: "/play", element: wait(<PlayPage />) },
    { path: "/explorer", element: <Planned title="Opening explorer" text="What people of your rating play in any position." items={["By rating band and speed", "Frequency and score of every move"]} milestone="milestone 6" /> },
    { path: "/insights", element: wait(<InsightsPage />) },
    { path: "/books", element: <Planned title="Books" text="Search the public-domain chess books by idea." items={["Concept search", "Passages with the position they describe"]} milestone="milestone 6" /> },
    { path: "/activity", element: wait(<ActivityPage />) },
  ],
}]);

export function App() {
  return <QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>;
}
